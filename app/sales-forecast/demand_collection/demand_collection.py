from fde import FdeError
import json


class DemandCollection:
    """主机厂原始需求收集表——加工链入口。OEM滚动预测的版本化收集+信号拆解。
    三层结构：收集单头(D03-H) → 明细(D03-D, 纵表) → 拆解快照(D03-S, 1:1)。
    """

    def _init_db(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS d03_header (
                collect_no      TEXT PRIMARY KEY,
                oem_code        TEXT NOT NULL,
                plant_code      TEXT NOT NULL,
                fcst_version    TEXT NOT NULL,
                base_period     TEXT NOT NULL,
                demand_type     TEXT NOT NULL DEFAULT '月度滚动预测',
                source_channel  TEXT NOT NULL,
                recv_date       TEXT NOT NULL,
                collector       TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT '草稿',
                prev_version    TEXT,
                remark          TEXT,
                UNIQUE(oem_code, plant_code, fcst_version)
            );
            CREATE TABLE IF NOT EXISTS d03_detail (
                collect_no  TEXT NOT NULL,
                line_no     INTEGER NOT NULL,
                part_no     TEXT NOT NULL,
                project_no  TEXT NOT NULL,
                veh_model   TEXT NOT NULL,
                proj_stage  TEXT NOT NULL DEFAULT '进行中',
                period      TEXT NOT NULL,
                orig_qty    REAL NOT NULL,
                uom         TEXT NOT NULL DEFAULT '件',
                data_flag   TEXT NOT NULL DEFAULT '正常',
                PRIMARY KEY (collect_no, line_no),
                FOREIGN KEY (collect_no) REFERENCES d03_header(collect_no)
            );
            CREATE TABLE IF NOT EXISTS d03_snapshot (
                collect_no      TEXT NOT NULL,
                line_no         INTEGER NOT NULL,
                period          TEXT NOT NULL,
                noise_adj       REAL NOT NULL DEFAULT 0,
                pulse_qty       REAL NOT NULL DEFAULT 0,
                true_qty        REAL NOT NULL,
                has_pulse       INTEGER NOT NULL DEFAULT 0,
                event_no        TEXT,
                method          TEXT NOT NULL,
                basis           TEXT NOT NULL,
                decomposer      TEXT,
                decompose_date  TEXT,
                PRIMARY KEY (collect_no, line_no, period),
                FOREIGN KEY (collect_no, line_no) REFERENCES d03_detail(collect_no, line_no)
            );
        """)

    # ============ 收集单管理 ============

    def create(self, oem_code: str, plant_code: str, fcst_version: str, base_period: str,
               demand_type: str = "月度滚动预测", source_channel: str = "",
               recv_date: str = "", remark: str = ""):
        """新建收集单头。客户+工厂+版本唯一。"""
        existing = self.db.execute(
            "SELECT 1 FROM d03_header WHERE oem_code=? AND plant_code=? AND fcst_version=?",
            (oem_code, plant_code, fcst_version)
        ).fetchone()
        if existing:
            raise FdeError(f"客户 {oem_code} 工厂 {plant_code} 版本 {fcst_version} 已存在收集单")
        # 生成 collect_no
        from datetime import datetime
        now = datetime.now().strftime("%Y%m%d%H%M%S")
        collect_no = f"COL-{now[:6]}-{now[6:]}"
        # 查上一版本
        prev = self.db.execute(
            "SELECT collect_no FROM d03_header WHERE oem_code=? AND plant_code=? AND fcst_version < ? ORDER BY fcst_version DESC LIMIT 1",
            (oem_code, plant_code, fcst_version)
        ).fetchone()
        prev_version = prev["collect_no"] if prev else None
        self.db.execute(
            """INSERT INTO d03_header (collect_no, oem_code, plant_code, fcst_version, base_period,
               demand_type, source_channel, recv_date, collector, prev_version, remark)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (collect_no, oem_code, plant_code, fcst_version, base_period,
             demand_type, source_channel, recv_date or datetime.now().strftime("%Y-%m-%d"),
             self.ctx["userno"], prev_version, remark)
        )
        return {"collect_no": collect_no}

    def add_lines(self, collect_no: str, lines: list):
        """批量录入明细。lines=[{part_no, project_no, veh_model, period, orig_qty, ...}]"""
        header = self._get_header(collect_no)
        if header["status"] != "草稿":
            raise FdeError("仅草稿状态可录入明细")
        max_line = self.db.execute(
            "SELECT COALESCE(MAX(line_no),0) AS m FROM d03_detail WHERE collect_no=?", (collect_no,)
        ).fetchone()["m"]
        for item in lines:
            max_line += 1
            proj_stage = item.get("proj_stage", "进行中")
            if proj_stage != "进行中":
                # 非进行中项目录入警告（不阻断，记录日志）
                pass
            self.db.execute(
                """INSERT INTO d03_detail (collect_no, line_no, part_no, project_no, veh_model,
                   proj_stage, period, orig_qty, uom, data_flag)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (collect_no, max_line,
                 item["part_no"], item["project_no"], item["veh_model"],
                 proj_stage, item["period"], item["orig_qty"],
                 item.get("uom", "件"), item.get("data_flag", "正常"))
            )
        return {"collect_no": collect_no, "lines_added": len(lines)}

    def get(self, collect_no: str):
        """获取收集单全貌（单头+明细+拆解快照）"""
        header = self._get_header(collect_no)
        details = self.db.execute(
            "SELECT * FROM d03_detail WHERE collect_no=? ORDER BY line_no", (collect_no,)
        ).fetchall()
        snapshots = self.db.execute(
            "SELECT * FROM d03_snapshot WHERE collect_no=? ORDER BY line_no, period", (collect_no,)
        ).fetchall()
        return {
            "header": dict(header),
            "details": [dict(d) for d in details],
            "snapshots": [dict(s) for s in snapshots]
        }

    def list(self, oem_code: str = None, fcst_version: str = None, status: str = None):
        sql = "SELECT * FROM d03_header WHERE 1=1"
        params = []
        if oem_code:
            sql += " AND oem_code = ?"
            params.append(oem_code)
        if fcst_version:
            sql += " AND fcst_version = ?"
            params.append(fcst_version)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY fcst_version DESC"
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ============ 信号拆解 ============

    def set_decomposition(self, collect_no: str, line_no: int, period: str,
                          noise_adj: float, pulse_qty: float, method: str, basis: str):
        """记录单行拆解结果。true_qty = orig_qty - pulse_qty - noise_adj（系统强制）。"""
        header = self._get_header(collect_no)
        if header["status"] != "草稿":
            raise FdeError("仅草稿状态可设置拆解")
        detail = self.db.execute(
            "SELECT * FROM d03_detail WHERE collect_no=? AND line_no=?", (collect_no, line_no)
        ).fetchone()
        if not detail:
            raise FdeError(f"明细行 {collect_no}/{line_no} 不存在")
        if detail["data_flag"] == "OEM未提供":
            return {"skipped": True, "reason": "OEM未提供期间不拆解"}
        orig_qty = detail["orig_qty"]
        true_qty = orig_qty - pulse_qty - noise_adj
        has_pulse = 1 if abs(pulse_qty) > 0.001 else 0
        self.db.execute(
            """INSERT OR REPLACE INTO d03_snapshot
               (collect_no, line_no, period, noise_adj, pulse_qty, true_qty, has_pulse, method, basis, decomposer, decompose_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,date('now'))""",
            (collect_no, line_no, period, noise_adj, pulse_qty, true_qty, has_pulse, method, basis, self.ctx["userno"])
        )
        return {"collect_no": collect_no, "line_no": line_no, "period": period,
                "orig_qty": orig_qty, "noise_adj": noise_adj, "pulse_qty": pulse_qty, "true_qty": true_qty}

    def confirm_decomposition(self, collect_no: str):
        """拆解确认：恒等式 + 噪声守恒校验后冻结版本。脉冲确认→生成D06事件。"""
        header = self._get_header(collect_no)
        if header["status"] != "草稿":
            raise FdeError("仅草稿状态可确认拆解")
        # 校验：必须有明细
        detail_count = self.db.execute(
            "SELECT COUNT(*) AS c FROM d03_detail WHERE collect_no=?", (collect_no,)
        ).fetchone()["c"]
        if detail_count == 0:
            raise FdeError("无明细数据，无法确认拆解")
        # 校验每条有数据的明细都有拆解快照
        details = self.db.execute(
            "SELECT * FROM d03_detail WHERE collect_no=? AND data_flag!='OEM未提供'", (collect_no,)
        ).fetchall()
        for d in details:
            snap = self.db.execute(
                "SELECT * FROM d03_snapshot WHERE collect_no=? AND line_no=? AND period=?",
                (collect_no, d["line_no"], d["period"])
            ).fetchone()
            if not snap:
                raise FdeError(f"明细行 {d['line_no']} 期间 {d['period']} 缺少拆解快照")
            # 恒等式校验
            expected = d["orig_qty"] - snap["pulse_qty"] - snap["noise_adj"]
            if abs(snap["true_qty"] - expected) > 0.01:
                raise FdeError(f"行{d['line_no']}期间{d['period']}拆解恒等式不成立：{snap['true_qty']} ≠ {d['orig_qty']}−{snap['pulse_qty']}−{snap['noise_adj']}")
            # 脉冲确认 → 生成事件
            if snap["has_pulse"] and not snap["event_no"]:
                try:
                    result = self.fde.call("independent_event", "create",
                        event_type="水位脉冲",
                        part_no=d["part_no"],
                        oem_code=header["oem_code"],
                        veh_model=d["veh_model"],
                        period=d["period"],
                        event_qty=snap["pulse_qty"],
                        source_basis=f"阶跃检测：{snap['basis']}",
                        source_ref=f"{collect_no}/{d['line_no']}"
                    )
                    self.db.execute(
                        "UPDATE d03_snapshot SET event_no=? WHERE collect_no=? AND line_no=? AND period=?",
                        (result["event_no"], collect_no, d["line_no"], d["period"])
                    )
                except Exception:
                    pass  # 事件创建失败不阻断拆解确认
        # 噪声守恒校验（跨行）
        noise_sum = self.db.execute(
            "SELECT SUM(noise_adj) AS s FROM d03_snapshot WHERE collect_no=?", (collect_no,)
        ).fetchone()["s"]
        if noise_sum and abs(noise_sum) > 0.1:
            raise FdeError(f"噪声调整跨期总额不守恒：Σnoise_adj={noise_sum}，拆解不通过")
        # 确认
        self.db.execute(
            "UPDATE d03_header SET status='已拆解' WHERE collect_no=?", (collect_no,)
        )
        return {"collect_no": collect_no, "status": "已拆解"}

    # ============ 版本管理 ============

    def lock(self, collect_no: str):
        """锁定版本（由D09发布联动触发）"""
        header = self._get_header(collect_no)
        if header["status"] not in ("已拆解",):
            raise FdeError(f"当前状态 {header['status']} 不可锁定")
        self.db.execute("UPDATE d03_header SET status='已锁定' WHERE collect_no=?", (collect_no,))
        return {"collect_no": collect_no, "status": "已锁定"}

    def supersede(self, collect_no: str, new_collect_no: str):
        """版本替代"""
        self.db.execute("UPDATE d03_header SET status='已替代' WHERE collect_no=?", (collect_no,))
        return {"collect_no": collect_no, "status": "已替代", "replaced_by": new_collect_no}

    def cancel(self, collect_no: str, reason: str):
        """作废收集单"""
        if not reason or not reason.strip():
            raise FdeError("作废必须填写原因")
        header = self._get_header(collect_no)
        if header["status"] not in ("草稿",):
            raise FdeError(f"当前状态 {header['status']} 不可作废")
        self.db.execute("UPDATE d03_header SET status='已作废', remark=? WHERE collect_no=?", (reason, collect_no))
        return {"collect_no": collect_no, "status": "已作废"}

    def version_diff(self, collect_no: str):
        """版本比对：当前版本 vs 上一版本逐零件×期间差异"""
        header = self._get_header(collect_no)
        if not header["prev_version"]:
            return {"message": "无上一版本，无法比对", "collect_no": collect_no}
        prev_details = self.db.execute(
            "SELECT part_no, veh_model, period, orig_qty FROM d03_detail WHERE collect_no=? ORDER BY part_no, period",
            (header["prev_version"],)
        ).fetchall()
        cur_details = self.db.execute(
            "SELECT part_no, veh_model, period, orig_qty FROM d03_detail WHERE collect_no=? ORDER BY part_no, period",
            (collect_no,)
        ).fetchall()
        prev_map = {(d["part_no"], d["veh_model"], d["period"]): d["orig_qty"] for d in prev_details}
        cur_map = {(d["part_no"], d["veh_model"], d["period"]): d["orig_qty"] for d in cur_details}
        diffs = []
        for key in set(list(prev_map.keys()) + list(cur_map.keys())):
            prev_qty = prev_map.get(key, 0)
            cur_qty = cur_map.get(key, 0)
            delta = cur_qty - prev_qty
            if abs(delta) > 0.001:
                diffs.append({"part_no": key[0], "veh_model": key[1], "period": key[2],
                              "prev_qty": prev_qty, "cur_qty": cur_qty, "delta": delta})
        return {"collect_no": collect_no, "prev_version": header["prev_version"], "diffs": diffs}

    # ============ 内部辅助 ============
    def _get_header(self, collect_no: str):
        row = self.db.execute("SELECT * FROM d03_header WHERE collect_no=?", (collect_no,)).fetchone()
        if not row:
            raise FdeError(f"收集单 {collect_no} 不存在")
        return row
