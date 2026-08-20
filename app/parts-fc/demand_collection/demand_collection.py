from fde import FdeError
import json


class DemandCollection:
    """主机厂原始需求收集表——加工链入口。OEM滚动预测的版本化收集+信号拆解。
    三层结构：收集单头(D03-H) → 明细(D03-D, 纵表) → 拆解快照(D03-S, 1:1)。
    """

    def _init_db(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS d03_header (
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
                replaced_by     TEXT,
                remark          TEXT,
                UNIQUE(oem_code, plant_code, fcst_version)
            );""")
        # 兼容旧表：replaced_by 列可能不存在
        try:
            self.db.execute("ALTER TABLE d03_header ADD COLUMN replaced_by TEXT")
        except Exception:
            pass
        self.db.execute("""CREATE TABLE IF NOT EXISTS d03_detail (
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
                forecast_source TEXT NOT NULL DEFAULT '主机厂预告',
                PRIMARY KEY (collect_no, line_no),
                FOREIGN KEY (collect_no) REFERENCES d03_header(collect_no)
            );""")
        # 兼容旧表
        try:
            self.db.execute("ALTER TABLE d03_detail ADD COLUMN forecast_source TEXT NOT NULL DEFAULT '主机厂预告'")
        except Exception:
            pass
        self.db.execute("""CREATE TABLE IF NOT EXISTS d03_snapshot (
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
            );""")

    # ============ 收集单管理 ============

    def create(self, oem_code: str, plant_code: str, fcst_version: str, base_period: str,
               demand_type: str = "月度滚动预测", source_channel: str = "",
               recv_date: str = "", remark: str = ""):
        """新建收集单头。客户+工厂+版本唯一。仅允许当月版本。自动从进行中项目填充 N+1/+2/+3 明细行。"""
        from datetime import datetime

        # 版本限制：仅当月
        current_month = datetime.now().strftime("V%Y%m")
        if fcst_version != current_month:
            raise FdeError(f"仅允许创建当月版本 {current_month}，当前输入 {fcst_version}")

        existing = self.db.execute(
            "SELECT collect_no, status FROM d03_header WHERE oem_code=? AND plant_code=? AND fcst_version=? AND status NOT IN ('已作废','已替代')",
            (oem_code, plant_code, fcst_version)
        ).fetchone()
        if existing:
            return {"collect_no": existing["collect_no"], "existing": True, "status": existing["status"]}

        # 生成 collect_no
        now = datetime.now().strftime("%Y%m%d%H%M%S%f")
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

        # 自动填充：从进行中项目带出零件明细（N+1/+2/+3 三个月）
        auto_lines = 0
        try:
            projects = self.fde.call("project_ledger", "get_active_projects", oem_code=oem_code)
            if projects and projects.get("items"):
                curr_year = datetime.now().year
                curr_month = datetime.now().month
                line_no = 0
                for proj in projects["items"]:
                    part_no = proj.get("part_no", "")
                    project_no = proj.get("project_no", "")
                    veh_model = proj.get("veh_model", "")
                    if not part_no:
                        continue
                    for offset in range(1, 4):  # N+1, N+2, N+3
                        m = curr_month + offset
                        y = curr_year
                        if m > 12:
                            m -= 12
                            y += 1
                        period = f"{y}-{m:02d}"
                        line_no += 1
                        self.db.execute(
                            """INSERT INTO d03_detail (collect_no, line_no, part_no, project_no, veh_model,
                               proj_stage, period, orig_qty, uom, data_flag, forecast_source)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (collect_no, line_no, part_no, project_no, veh_model,
                             proj.get("stage", "进行中"), period, 0, "件", "正常", "主机厂预告")
                        )
                        auto_lines += 1
        except Exception:
            pass  # 项目同步失败不阻断创建

        return {"collect_no": collect_no, "auto_lines": auto_lines}

    def sync_from_projects(self, collect_no: str):
        """刷新明细：从进行中项目同步新增的零件（不重复添加已有的 part+project+period）。"""
        header = self._get_header(collect_no)
        if header["status"] != "草稿":
            raise FdeError("仅草稿状态可刷新明细")

        from datetime import datetime
        try:
            projects = self.fde.call("project_ledger", "get_active_projects", oem_code=header["oem_code"])
        except Exception:
            raise FdeError("获取进行中项目失败")

        if not projects or not projects.get("items"):
            return {"collect_no": collect_no, "added": 0, "message": "无进行中项目"}

        # 已有明细的去重键
        existing = set()
        rows = self.db.execute(
            "SELECT part_no, project_no, period FROM d03_detail WHERE collect_no=?", (collect_no,)
        ).fetchall()
        for r in rows:
            existing.add((r["part_no"], r["project_no"], r["period"]))

        curr_year = datetime.now().year
        curr_month = datetime.now().month
        max_line = self.db.execute(
            "SELECT COALESCE(MAX(line_no),0) AS m FROM d03_detail WHERE collect_no=?", (collect_no,)
        ).fetchone()["m"]
        added = 0

        for proj in projects["items"]:
            part_no = proj.get("part_no", "")
            project_no = proj.get("project_no", "")
            veh_model = proj.get("veh_model", "")
            if not part_no:
                continue
            for offset in range(1, 4):
                m = curr_month + offset
                y = curr_year
                if m > 12:
                    m -= 12
                    y += 1
                period = f"{y}-{m:02d}"
                if (part_no, project_no, period) in existing:
                    continue
                max_line += 1
                self.db.execute(
                    """INSERT INTO d03_detail (collect_no, line_no, part_no, project_no, veh_model,
                       proj_stage, period, orig_qty, uom, data_flag, forecast_source)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (collect_no, max_line, part_no, project_no, veh_model,
                     proj.get("stage", "进行中"), period, 0, "件", "正常", "主机厂预告")
                )
                existing.add((part_no, project_no, period))
                added += 1

        return {"collect_no": collect_no, "added": added,
                "message": f"已同步 {added} 行新明细" if added else "明细已是最新，无新增零件"}

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
            # 校验项目阶段（非进行中项目录入时警告）
            proj_stage = item.get("proj_stage", "进行中")
            if proj_stage != "进行中":
                pass  # 非进行中项目录入已在上方处理，此处仅标注
            self.db.execute(
                """INSERT INTO d03_detail (collect_no, line_no, part_no, project_no, veh_model,
                   proj_stage, period, orig_qty, uom, data_flag, forecast_source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (collect_no, max_line,
                 item["part_no"], item["project_no"], item["veh_model"],
                 proj_stage, item["period"], item["orig_qty"],
                 item.get("uom", "件"), item.get("data_flag", "正常"),
                 item.get("forecast_source", "主机厂预告"))
            )
        return {"collect_no": collect_no, "lines_added": len(lines),
                "note": "已录入；若零件量与车型量×用量×份额偏离较大，请人工确认"}

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

    def list(self, oem_code: str = None, fcst_version: str = None, status: str = None, page: int = None, size: int = None):
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
        total = len(rows)
        # 服务端分页
        if page is not None and size is not None:
            page_no = max(1, int(page) if page else 1)
            size_n = max(1, int(size) if size else 50)
            start = (page_no - 1) * size_n
            rows = rows[start:start + size_n]

        return {"items": [dict(r) for r in rows], "total": total}

    def analyze_groups(self, collect_no: str):
        """分析明细数据，按 (part_no, veh_model) 分组推荐拆解方法。"""
        header = self._get_header(collect_no)
        details = self.db.execute(
            "SELECT * FROM d03_detail WHERE collect_no=? ORDER BY part_no, veh_model, period",
            (collect_no,)
        ).fetchall()
        if not details:
            raise FdeError("无明细数据")

        groups = {}
        for d in details:
            if d["data_flag"] == "OEM未提供":
                continue
            key = f"{d['part_no']}|{d['veh_model']}"
            groups.setdefault(key, {"part_no": d["part_no"], "veh_model": d["veh_model"], "periods": []})
            groups[key]["periods"].append({"line_no": d["line_no"], "period": d["period"], "orig_qty": d["orig_qty"]})

        result = []
        for key, g in groups.items():
            periods_data = sorted(g["periods"], key=lambda x: x["period"])
            quantities = [p["orig_qty"] for p in periods_data]
            n = len(quantities)

            # 查历史数据
            hist = self._get_historical_series(collect_no, g["part_no"], g["veh_model"])
            hist_n = len(hist)
            total_n = hist_n + n
            total_label = f"（历史 {hist_n} 期 + 本期 {n} 期）" if hist_n else ""

            # 智能推荐（基于总期数）
            if total_n < 2:
                recommend = "免拆解"
                reason = f"仅 {total_n} 期数据{total_label}，无法检测趋势/脉冲"
            elif n == 2:
                # 2期：检测差异是否显著
                diff_pct = abs(quantities[1] - quantities[0]) / max(abs(quantities[0]), 1) if quantities[0] else 0
                if diff_pct > 0.5:
                    recommend = "阶跃检测"
                    reason = f"2期间差异 {diff_pct:.0%}，疑似阶跃"
                else:
                    recommend = "指数平滑"
                    reason = f"2期间差异 {diff_pct:.0%}，数据偏少用指数平滑"
            else:
                # >=3期：检测趋势、波动特征
                mean_qty = sum(quantities) / n
                variance = sum((q - mean_qty) ** 2 for q in quantities) / max(n - 1, 1)
                cv = (variance ** 0.5) / max(abs(mean_qty), 0.01)  # 变异系数

                # 检测单调趋势（连续上涨或连续下跌）
                increasing = all(quantities[i] >= quantities[i - 1] for i in range(1, n))
                decreasing = all(quantities[i] <= quantities[i - 1] for i in range(1, n))

                if increasing or decreasing:
                    direction = "持续增长" if increasing else "持续下降"
                    recommend = "阶跃检测"
                    reason = f"{direction}趋势（{quantities[0]}→{quantities[-1]}），用阶跃检测分离趋势变化"
                elif cv > 0.5:
                    recommend = "移动平均"
                    reason = f"高波动 CV={cv:.1%}，移动平均检测脉冲"
                else:
                    recommend = "移动平均"
                    reason = f"平稳 CV={cv:.1%}，移动平均通用处理"

            result.append({
                "part_no": g["part_no"],
                "veh_model": g["veh_model"],
                "period_count": n,
                "hist_count": hist_n,
                "periods": g["periods"],
                "recommend": recommend,
                "reason": reason + total_label,
                "selected": recommend,
            })

        return {"collect_no": collect_no, "groups": result}

    def auto_decompose(self, collect_no: str, method: str = "移动平均",
                       group_methods: dict = None):
        """自动预拆解：对全部明细逐行生成初始快照。

        method: 统一方法（group_methods 为空时生效）
        group_methods: 按 'part_no|veh_model' 指定方法，优先级高于 method
        """
        header = self._get_header(collect_no)
        if header["status"] != "草稿":
            raise FdeError("仅草稿状态可自动预拆解")

        valid_methods = ("移动平均", "指数平滑", "阶跃检测", "发运结算倒推", "免拆解")
        if method not in valid_methods:
            raise FdeError(f"不支持的拆解方法：{method}，可选：{'/'.join(valid_methods)}")

        details = self.db.execute(
            "SELECT * FROM d03_detail WHERE collect_no=? ORDER BY part_no, veh_model, period",
            (collect_no,)
        ).fetchall()

        if not details:
            raise FdeError("无明细数据，无法预拆解")

        # 预加载历史序列缓存：key=(part_no, veh_model) → [{period, true_qty}, ...]
        history_cache = {}
        for d in details:
            k = (d["part_no"], d["veh_model"])
            if k not in history_cache:
                history_cache[k] = self._get_historical_series(collect_no, d["part_no"], d["veh_model"])

        # 按 (part_no, veh_model) 分组
        groups = {}
        for d in details:
            if d["data_flag"] == "OEM未提供":
                continue
            key = (d["part_no"], d["veh_model"])
            groups.setdefault(key, []).append(d)

        total_lines = 0
        pulse_lines = 0

        for (part_no, veh_model), group in groups.items():
            periods_data = sorted(group, key=lambda x: x["period"])
            quantities = [d["orig_qty"] for d in periods_data]
            n = len(quantities)

            # 每组可独立指定方法
            key = f"{part_no}|{veh_model}"
            grp_method = (group_methods or {}).get(key, method)

            # 合并历史序列：（历史 true_qty ...）+（本期 orig_qty ...）
            hist = history_cache.get((part_no, veh_model), [])
            hist_quantities = [h["true_qty"] for h in hist]
            all_quantities = hist_quantities + quantities
            all_n = len(all_quantities)
            h_len = len(hist_quantities)

            if grp_method == "免拆解":
                for d in periods_data:
                    self._upsert_snapshot(collect_no, d["line_no"], d["period"],
                        noise_adj=0, pulse_qty=0, true_qty=d["orig_qty"],
                        has_pulse=0, method="免拆解",
                        basis="免拆解模式，全部归零，请人工逐行拆解")
                    total_lines += 1
                continue

            # 含历史仍不足 2 期 → 回退免拆解
            if all_n < 2:
                for d in periods_data:
                    self._upsert_snapshot(collect_no, d["line_no"], d["period"],
                        noise_adj=0, pulse_qty=0, true_qty=d["orig_qty"],
                        has_pulse=0, method="免拆解",
                        basis=f"含历史仅 {all_n} 期数据，无法检测趋势/脉冲，自动免拆解，请人工覆核")
                    total_lines += 1
                continue

            if grp_method == "发运结算倒推":
                # 需外部结算数据，自动回退
                for d in periods_data:
                    self._upsert_snapshot(collect_no, d["line_no"], d["period"],
                        noise_adj=0, pulse_qty=0, true_qty=d["orig_qty"],
                        has_pulse=0, method="免拆解",
                        basis="发运结算倒推需外部结算数据，已自动回退为免拆解，请人工逐行拆解")
                    total_lines += 1
                continue

            # 统计量：优先用历史数据计算正常波动范围（避免本期异常值污染阈值）
            hist_label = f"（含 {h_len} 期历史 + {n} 期本期）" if h_len else ""
            if h_len >= 2:
                hist_mean = sum(hist_quantities) / h_len
                hist_var = sum((q - hist_mean) ** 2 for q in hist_quantities) / max(h_len - 1, 1)
                hist_std = hist_var ** 0.5
                # 历史方差极小（稳定需求）→ 设定最小阈值 = 均值的 5%
                min_std = abs(hist_mean) * 0.05 if abs(hist_mean) > 0 else 0.1
                std_dev = hist_std if hist_std > min_std else min_std
            else:
                mean_qty = sum(all_quantities) / all_n
                variance = sum((q - mean_qty) ** 2 for q in all_quantities) / max(all_n - 1, 1)
                std_dev = variance ** 0.5
            hist_label = f"（含 {h_len} 期历史 + {n} 期本期）" if h_len else ""

            if grp_method == "移动平均":
                for i, d in enumerate(periods_data):
                    idx = h_len + i  # 在完整序列中的位置
                    start = max(0, idx - 1)
                    end = min(all_n, idx + 2)
                    window = all_quantities[start:end]
                    baseline = sum(window) / len(window)
                    deviation = round(d["orig_qty"] - baseline, 2)
                    is_pulse = std_dev > 0.01 and abs(deviation) > 2 * std_dev
                    pulse_qty = deviation if is_pulse else 0
                    noise_adj = 0 if is_pulse else deviation
                    has_pulse = 1 if is_pulse else 0
                    if is_pulse:
                        pulse_lines += 1
                    basis = (
                        f"移动平均{hist_label}（窗口MA={baseline:.1f}），异常跳变偏差{deviation}（{abs(deviation/std_dev):.1f}σ），标记为疑似脉冲"
                        if is_pulse else
                        f"移动平均{hist_label}（窗口MA={baseline:.1f}），偏差{deviation}在正常范围（{abs(deviation/std_dev):.1f}σ）"
                    )
                    self._upsert_snapshot(collect_no, d["line_no"], d["period"],
                        noise_adj=noise_adj, pulse_qty=pulse_qty,
                        true_qty=round(d["orig_qty"] - pulse_qty - noise_adj, 2),
                        has_pulse=has_pulse, method=grp_method, basis=basis + "，请人工覆核")
                    total_lines += 1

            elif grp_method == "指数平滑":
                alpha = 0.3
                smoothed = all_quantities[0]
                smoothed_series = [smoothed]
                for q in all_quantities[1:]:
                    smoothed = alpha * q + (1 - alpha) * smoothed
                    smoothed_series.append(smoothed)

                for i, d in enumerate(periods_data):
                    idx = h_len + i
                    baseline = smoothed_series[idx]
                    deviation = round(d["orig_qty"] - baseline, 2)
                    is_pulse = std_dev > 0.01 and abs(deviation) > 2 * std_dev
                    pulse_qty = deviation if is_pulse else 0
                    noise_adj = 0 if is_pulse else deviation
                    has_pulse = 1 if is_pulse else 0
                    if is_pulse:
                        pulse_lines += 1
                    basis = (
                        f"指数平滑{hist_label}（α=0.3，S={baseline:.1f}），异常跳变偏差{deviation}（{abs(deviation/std_dev):.1f}σ），标记为疑似脉冲"
                        if is_pulse else
                        f"指数平滑{hist_label}（α=0.3，S={baseline:.1f}），偏差{deviation}在正常范围（{abs(deviation/std_dev):.1f}σ）"
                    )
                    self._upsert_snapshot(collect_no, d["line_no"], d["period"],
                        noise_adj=noise_adj, pulse_qty=pulse_qty,
                        true_qty=round(d["orig_qty"] - pulse_qty - noise_adj, 2),
                        has_pulse=has_pulse, method=grp_method, basis=basis + "，请人工覆核")
                    total_lines += 1

            elif grp_method == "阶跃检测":
                for i, d in enumerate(periods_data):
                    idx = h_len + i
                    if idx == 0:
                        deviation = 0
                        is_step = False
                    else:
                        deviation = round(d["orig_qty"] - all_quantities[idx - 1], 2)
                        is_step = std_dev > 0.01 and abs(deviation) > 2 * std_dev

                    if is_step:
                        noise_adj = deviation
                        pulse_qty = 0
                        has_pulse = 0
                        basis = f"阶跃检测{hist_label}：相邻期差{deviation}（{abs(deviation/std_dev):.1f}σ），判定为阶跃（趋势变化），归入噪声"
                    else:
                        noise_adj = 0
                        pulse_qty = 0
                        has_pulse = 0
                        basis = f"阶跃检测{hist_label}：未检测到显著阶跃，偏差在正常范围"

                    self._upsert_snapshot(collect_no, d["line_no"], d["period"],
                        noise_adj=noise_adj, pulse_qty=pulse_qty,
                        true_qty=round(d["orig_qty"] - pulse_qty - noise_adj, 2),
                        has_pulse=has_pulse, method=grp_method, basis=basis + "，请人工覆核")
                    total_lines += 1

        return {
            "collect_no": collect_no,
            "method": method,
            "lines_processed": total_lines,
            "pulse_detected": pulse_lines,
            "message": f"已完成 {total_lines} 行预拆解（{method}）" + (f"，其中 {pulse_lines} 行检测到疑似脉冲" if pulse_lines else ""),
        }

    def decompose(self, collect_no: str, line_no: int, period: str,
                          noise_adj: float, pulse_qty: float, method: str, basis: str):
        """人工覆核单行拆解：覆盖自动预拆解结果。"""
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
        self._upsert_snapshot(collect_no, line_no, period,
            noise_adj=noise_adj, pulse_qty=pulse_qty, true_qty=true_qty,
            has_pulse=has_pulse, method=method, basis=basis)
        return {"collect_no": collect_no, "line_no": line_no, "period": period,
                "orig_qty": orig_qty, "noise_adj": noise_adj, "pulse_qty": pulse_qty, "true_qty": true_qty}

    def _get_historical_series(self, collect_no, part_no, veh_model, max_versions=6):
        """沿 prev_version 链回溯，收集同零件+车型的历史 true_qty 序列。"""
        series = []
        visited = set()
        current = collect_no
        for _ in range(max_versions):
            if current in visited:
                break
            visited.add(current)
            h = self.db.execute(
                "SELECT prev_version, fcst_version FROM d03_header WHERE collect_no=?",
                (current,)
            ).fetchone()
            if not h or not h["prev_version"]:
                break
            prev = h["prev_version"]
            # 取上一版本的拆解快照 true_qty（已确认的干净信号）
            rows = self.db.execute(
                """SELECT s.period, s.true_qty, d.part_no, d.veh_model
                   FROM d03_snapshot s
                   JOIN d03_detail d ON s.collect_no=d.collect_no AND s.line_no=d.line_no
                   WHERE s.collect_no=? AND d.part_no=? AND d.veh_model=?
                   ORDER BY s.period""",
                (prev, part_no, veh_model)
            ).fetchall()
            for r in rows:
                series.append({"period": r["period"], "true_qty": r["true_qty"]})
            current = prev
        # 按期间排序，去重（同期间取最新版本的值）
        seen = {}
        for s in sorted(series, key=lambda x: x["period"]):
            seen[s["period"]] = s["true_qty"]
        return [{"period": p, "true_qty": q} for p, q in sorted(seen.items())]

    def _upsert_snapshot(self, collect_no, line_no, period, noise_adj, pulse_qty, true_qty, has_pulse, method, basis):
        self.db.execute(
            """INSERT OR REPLACE INTO d03_snapshot
               (collect_no, line_no, period, noise_adj, pulse_qty, true_qty, has_pulse, method, basis, decomposer, decompose_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,date('now'))""",
            (collect_no, line_no, period, noise_adj, pulse_qty, true_qty, has_pulse, method, basis, self.ctx.get("userno", "系统"))
        )

    def confirm_decompose(self, collect_no: str):
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
        # 噪声守恒校验（跨行）：警告但不阻断
        noise_sum = self.db.execute(
            "SELECT SUM(noise_adj) AS s FROM d03_snapshot WHERE collect_no=?", (collect_no,)
        ).fetchone()["s"]
        noise_warning = ""
        if noise_sum is not None and abs(noise_sum) > 0.1:
            noise_warning = f"⚠ 噪声跨期总额不守恒：Σnoise_adj={round(noise_sum,2)}（噪声应跨期抵消趋零；人工覆核阶跃等场景可忽略此警告）"
        # 确认
        self.db.execute(
            "UPDATE d03_header SET status='已拆解' WHERE collect_no=?", (collect_no,)
        )
        # 自动触发 D04 创建加工批次
        batch_no = None
        try:
            result = self.fde.call("demand_processing", "create_batch",
                fcst_version=header["fcst_version"],
                oem_code=header["oem_code"], plant_code=header["plant_code"],
                collect_no=collect_no)
            batch_no = result.get("proc_batch")
        except Exception:
            pass  # 批次创建失败不阻断拆解确认
        return {"collect_no": collect_no, "status": "已拆解", "proc_batch": batch_no, "warning": noise_warning or None}

    # ============ 版本管理 ============

    def lock(self, collect_no: str):
        """锁定版本（由D09发布联动触发）"""
        header = self._get_header(collect_no)
        if header["status"] not in ("已拆解",):
            raise FdeError(f"当前状态 {header['status']} 不可锁定")
        self.db.execute("UPDATE d03_header SET status='已锁定' WHERE collect_no=?", (collect_no,))
        return {"collect_no": collect_no, "status": "已锁定"}

    def supersede(self, collect_no: str):
        """版本替代：将旧单标记为已替代，复制全部明细和拆解快照到新单，供分析员修正。"""
        old = self._get_header(collect_no)
        if old["status"] not in ("已拆解", "已锁定"):
            raise FdeError(f"当前状态 {old['status']} 不可替代，仅已拆解/已锁定可替代")

        # 取旧单完整数据
        old_details = self.db.execute(
            "SELECT * FROM d03_detail WHERE collect_no=? ORDER BY line_no", (collect_no,)
        ).fetchall()
        old_snapshots = self.db.execute(
            "SELECT * FROM d03_snapshot WHERE collect_no=? ORDER BY line_no, period", (collect_no,)
        ).fetchall()

        # 生成新单号
        from datetime import datetime
        now = datetime.now().strftime("%Y%m%d%H%M%S%f")
        new_no = f"COL-{now[:6]}-{now[6:]}"

        # 旧单让出唯一约束：version 加后缀，记录替代单号
        self.db.execute(
            "UPDATE d03_header SET fcst_version = fcst_version || '_已替代', status = '已替代', replaced_by = ? WHERE collect_no = ?",
            (new_no, collect_no,)
        )

        # 插入新单头（继承旧单字段，prev_version 指向旧单的前版）
        self.db.execute(
            """INSERT INTO d03_header (collect_no, oem_code, plant_code, fcst_version, base_period,
               demand_type, source_channel, recv_date, collector, prev_version, remark)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (new_no, old["oem_code"], old["plant_code"], old["fcst_version"], old["base_period"],
             old["demand_type"], old["source_channel"],
             datetime.now().strftime("%Y-%m-%d"),
             self.ctx.get("userno") or "系统",
             old["prev_version"],  # 新单指向前版，而非旧单
             f"替代 {collect_no} — {old['remark'] or ''}")
        )

        # 复制明细行
        line_map = {}  # old_line_no → new_line_no
        for i, dl in enumerate(old_details, 1):
            self.db.execute(
                """INSERT INTO d03_detail (collect_no, line_no, part_no, project_no, veh_model,
                   proj_stage, period, orig_qty, uom, data_flag, forecast_source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (new_no, i, dl["part_no"], dl["project_no"], dl["veh_model"],
                 dl["proj_stage"], dl["period"], dl["orig_qty"], dl["uom"], dl["data_flag"],
                 dl["forecast_source"] if "forecast_source" in dl.keys() else "主机厂预告")
            )
            line_map[dl["line_no"]] = i

        # 复制拆解快照
        for s in old_snapshots:
            new_line = line_map.get(s["line_no"], s["line_no"])
            self.db.execute(
                """INSERT INTO d03_snapshot (collect_no, line_no, period,
                   noise_adj, pulse_qty, true_qty, has_pulse, event_no, method, basis, decomposer, decompose_date)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (new_no, new_line, s["period"],
                 s["noise_adj"], s["pulse_qty"], s["true_qty"], s["has_pulse"],
                 None, s["method"], s["basis"], s["decomposer"], s["decompose_date"])
            )

        return {
            "collect_no": new_no,
            "superseded": collect_no,
            "lines_copied": len(old_details),
            "snapshots_copied": len(old_snapshots),
            "message": f"已替代 {collect_no}，新单 {new_no} 已创建并继承 {len(old_details)} 行明细 + {len(old_snapshots)} 条快照",
        }

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
        return {"collect_no": collect_no, "prev_version": header["prev_version"], "diffs": diffs, "diff_count": len(diffs)}

    def get_true_qty(self, collect_no: str = None, part_no: str = None, period: str = None):
        """取真实消耗量——供 D04 基线生成取数（基线只取 true_qty）。"""
        sql = """SELECT s.collect_no, d.part_no, d.veh_model, s.period, s.true_qty, d.orig_qty
                 FROM d03_snapshot s
                 JOIN d03_detail d ON s.collect_no=d.collect_no AND s.line_no=d.line_no
                 JOIN d03_header h ON s.collect_no=h.collect_no
                 WHERE h.status IN ('已拆解', '已锁定')"""
        params = []
        if collect_no:
            sql += " AND s.collect_no = ?"
            params.append(collect_no)
        if part_no:
            sql += " AND d.part_no = ?"
            params.append(part_no)
        if period:
            sql += " AND s.period = ?"
            params.append(period)
        rows = self.db.execute(sql, params).fetchall()
        return {"items": [dict(r) for r in rows], "total": len(rows)}

    # ============ 内部辅助 ============
    def _get_header(self, collect_no: str):
        row = self.db.execute("SELECT * FROM d03_header WHERE collect_no=?", (collect_no,)).fetchone()
        if not row:
            raise FdeError(f"收集单 {collect_no} 不存在")
        return row
