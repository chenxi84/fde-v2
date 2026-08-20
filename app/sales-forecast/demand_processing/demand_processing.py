from fde import FdeError


class DemandProcessing:
    """毛需求加工表——加工链总账。五层结构：
    D04-H 加工单头 / D04-B 基线明细 / D04-A 修正明细 / D04-C 核对明细 / D04-L 调整登记。
    """

    def _init_db(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS d04_header (
                proc_batch   TEXT PRIMARY KEY,
                oem_code     TEXT NOT NULL,
                plant_code   TEXT NOT NULL,
                fcst_version TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT '进行中',
                start_time   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                finish_time  TEXT
            );
            CREATE TABLE IF NOT EXISTS d04_baseline (
                proc_batch  TEXT NOT NULL,
                part_no     TEXT NOT NULL,
                veh_model   TEXT NOT NULL,
                period      TEXT NOT NULL,
                base_qty    REAL NOT NULL,
                base_path   TEXT NOT NULL,
                base_method TEXT NOT NULL,
                source_ref  TEXT NOT NULL,
                causal_qty  REAL,
                deviation   REAL,
                deviation_reason TEXT,
                generator   TEXT,
                gen_time    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (proc_batch, part_no, veh_model, period),
                FOREIGN KEY (proc_batch) REFERENCES d04_header(proc_batch)
            );
            CREATE TABLE IF NOT EXISTS d04_adjustment (
                proc_batch      TEXT NOT NULL,
                part_no         TEXT NOT NULL,
                veh_model       TEXT NOT NULL,
                period          TEXT NOT NULL,
                base_qty        REAL NOT NULL,
                adj_qty         REAL NOT NULL,
                adj_delta       REAL NOT NULL,
                adj_pct         REAL NOT NULL,
                adj_reason_cat  TEXT NOT NULL,
                adj_evidence    TEXT,
                adj_owner       TEXT NOT NULL,
                submit_status   TEXT NOT NULL DEFAULT '待提交',
                submit_time     TEXT,
                PRIMARY KEY (proc_batch, part_no, veh_model, period),
                FOREIGN KEY (proc_batch) REFERENCES d04_header(proc_batch)
            );
            CREATE TABLE IF NOT EXISTS d04_check (
                proc_batch    TEXT NOT NULL,
                part_no       TEXT NOT NULL,
                veh_model     TEXT NOT NULL,
                period        TEXT NOT NULL,
                chk_round     INTEGER NOT NULL DEFAULT 1,
                chk_result    TEXT NOT NULL,
                chk_reason    TEXT,
                chk_adj_qty   REAL,
                approved_qty  REAL,
                checker       TEXT NOT NULL,
                chk_time      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (proc_batch, part_no, veh_model, period, chk_round),
                FOREIGN KEY (proc_batch) REFERENCES d04_header(proc_batch)
            );
            CREATE TABLE IF NOT EXISTS d04_log (
                proc_batch  TEXT NOT NULL,
                part_no     TEXT NOT NULL,
                veh_model   TEXT NOT NULL,
                period      TEXT NOT NULL,
                adj_seq     INTEGER NOT NULL,
                actor_role  TEXT NOT NULL,
                before_qty  REAL NOT NULL,
                after_qty   REAL NOT NULL,
                reason_cat  TEXT NOT NULL,
                evidence    TEXT,
                actor       TEXT NOT NULL,
                action_time TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (proc_batch, part_no, veh_model, period, adj_seq),
                FOREIGN KEY (proc_batch) REFERENCES d04_header(proc_batch)
            );
        """)

    # ========== 批次管理 ==========

    def create_batch(self, fcst_version: str, oem_code: str, plant_code: str):
        """创建加工批次。由拆解确认后触发。"""
        from datetime import datetime
        now = datetime.now().strftime("%Y%m%d%H%M%S")
        proc_batch = f"PRC-{now[:6]}-{now[6:]}"
        self.db.execute(
            "INSERT INTO d04_header (proc_batch, oem_code, plant_code, fcst_version) VALUES (?,?,?,?)",
            (proc_batch, oem_code, plant_code, fcst_version)
        )
        return {"proc_batch": proc_batch}

    def get(self, proc_batch: str):
        """获取批次全貌"""
        h = self._get_header(proc_batch)
        b = self.db.execute("SELECT * FROM d04_baseline WHERE proc_batch=?", (proc_batch,)).fetchall()
        a = self.db.execute("SELECT * FROM d04_adjustment WHERE proc_batch=?", (proc_batch,)).fetchall()
        c = self.db.execute("SELECT * FROM d04_check WHERE proc_batch=? ORDER BY chk_round", (proc_batch,)).fetchall()
        ll = self.db.execute("SELECT * FROM d04_log WHERE proc_batch=? ORDER BY adj_seq", (proc_batch,)).fetchall()
        return {"header": dict(h), "baselines": [dict(r) for r in b],
                "adjustments": [dict(r) for r in a], "checks": [dict(r) for r in c],
                "logs": [dict(r) for r in ll]}

    def list(self, oem_code: str = None, status: str = None):
        sql = "SELECT * FROM d04_header WHERE 1=1"
        params = []
        if oem_code:
            sql += " AND oem_code=?"
            params.append(oem_code)
        if status:
            sql += " AND status=?"
            params.append(status)
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ========== 基线生成（步骤2） ==========

    def generate_baseline(self, proc_batch: str):
        """系统预计算双路径基线。从D03取true_qty，从D10/D05取策略。"""
        header = self._get_header(proc_batch)
        if header["status"] != "进行中":
            raise FdeError("仅进行中批次可生成基线")
        # 取D03收集数据
        try:
            coll_result = self.fde.call("demand_collection", "get", collect_no=header["fcst_version"])
        except Exception as e:
            raise FdeError(f"获取收集数据失败：{e}")
        details = coll_result.get("details", [])
        snapshots = {(s["line_no"], s["period"]): s for s in coll_result.get("snapshots", [])}
        generated = 0
        for d in details:
            if d["data_flag"] == "OEM未提供":
                continue
            period = d["period"]
            snap = snapshots.get((d["line_no"], period))
            if not snap:
                continue
            true_qty = snap.get("true_qty", d["orig_qty"])
            # 尝试取D10策略
            strategy = None
            try:
                strat = self.fde.call("strategy_simulation", "get_strategy",
                                      part_no=d["part_no"], veh_model=d["veh_model"])
                if strat:
                    strategy = strat
            except Exception:
                pass
            if strategy:
                base_path = "时序外推"
                base_method = strategy.get("strategy", "移动平均(3期)")
                source_ref = strategy.get("fit_no", "")
                base_qty = true_qty  # 简化：直接用true_qty做基线值（实际应外推）
            else:
                # 历史不足，查D05借用
                base_path = "借用"
                base_method = "借用基线"
                source_ref = ""
                base_qty = true_qty
            causal_qty = base_qty * 1.02  # 简化因果路径
            deviation = abs(base_qty - causal_qty) / max(abs(base_qty), 0.01) if base_qty else 0
            self.db.execute(
                """INSERT OR REPLACE INTO d04_baseline
                   (proc_batch, part_no, veh_model, period, base_qty, base_path, base_method,
                    source_ref, causal_qty, deviation, generator)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (proc_batch, d["part_no"], d["veh_model"], period, base_qty, base_path, base_method,
                 source_ref, causal_qty, deviation, self.ctx["userno"])
            )
            generated += 1
        return {"proc_batch": proc_batch, "lines_generated": generated}

    def confirm_baseline(self, proc_batch: str, part_no: str, veh_model: str, period: str,
                         base_qty: float = None, deviation_reason: str = None):
        """人工确认/裁决基线"""
        row = self.db.execute(
            "SELECT * FROM d04_baseline WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=?",
            (proc_batch, part_no, veh_model, period)
        ).fetchone()
        if not row:
            raise FdeError("基线行不存在，请先生成基线")
        if base_qty is not None:
            self.db.execute(
                "UPDATE d04_baseline SET base_qty=? WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=?",
                (base_qty, proc_batch, part_no, veh_model, period)
            )
        if deviation_reason:
            self.db.execute(
                "UPDATE d04_baseline SET deviation_reason=? WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=?",
                (deviation_reason, proc_batch, part_no, veh_model, period)
            )
        # 同步创建待修正行
        base = self.db.execute(
            "SELECT base_qty FROM d04_baseline WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=?",
            (proc_batch, part_no, veh_model, period)
        ).fetchone()
        self.db.execute(
            """INSERT OR IGNORE INTO d04_adjustment
               (proc_batch, part_no, veh_model, period, base_qty, adj_qty, adj_delta, adj_pct,
                adj_reason_cat, adj_owner, submit_status)
               VALUES (?,?,?,?,?,?,0,0,'','','待提交')""",
            (proc_batch, part_no, veh_model, period, base["base_qty"], base["base_qty"])
        )
        return {"proc_batch": proc_batch, "part_no": part_no, "period": period}

    # ========== 销售修正（步骤3） ==========

    def submit_adjustment(self, proc_batch: str, part_no: str, veh_model: str, period: str,
                          adj_qty: float, adj_reason_cat: str, adj_evidence: str = ""):
        """销售提交修正值。三件套强制。超θ_rev(20%)强制举证。"""
        header = self._get_header(proc_batch)
        if header["status"] != "进行中":
            raise FdeError("仅进行中批次可提交修正")
        base = self.db.execute(
            "SELECT * FROM d04_baseline WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=?",
            (proc_batch, part_no, veh_model, period)
        ).fetchone()
        if not base:
            raise FdeError("基线未生成，无法修正")
        base_qty = base["base_qty"]
        adj_delta = adj_qty - base_qty
        adj_pct = abs(adj_delta) / max(abs(base_qty), 0.01) if base_qty else 0
        # BR-03: 超θ_rev强制举证
        if adj_pct > 0.20 and not adj_evidence.strip():
            raise FdeError(f"修正幅度率 {adj_pct:.1%} 超过20%阈值，必须附数据依据（客户函件/邮件记录/数据截图）")
        if not adj_reason_cat.strip():
            raise FdeError("原因类别不可为空（三件套强制）")
        # 记录调整日志（D04-L）
        current = self.db.execute(
            "SELECT adj_qty FROM d04_adjustment WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=?",
            (proc_batch, part_no, veh_model, period)
        ).fetchone()
        before_qty = current["adj_qty"] if current else base_qty
        seq = self._next_log_seq(proc_batch, part_no, veh_model, period)
        self.db.execute(
            """INSERT INTO d04_log (proc_batch, part_no, veh_model, period, adj_seq,
               actor_role, before_qty, after_qty, reason_cat, evidence, actor)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (proc_batch, part_no, veh_model, period, seq, "销售", before_qty, adj_qty,
             adj_reason_cat, adj_evidence, self.ctx["userno"])
        )
        # 更新修正明细
        self.db.execute(
            """INSERT OR REPLACE INTO d04_adjustment
               (proc_batch, part_no, veh_model, period, base_qty, adj_qty, adj_delta, adj_pct,
                adj_reason_cat, adj_evidence, adj_owner, submit_status, submit_time)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
            (proc_batch, part_no, veh_model, period, base_qty, adj_qty, adj_delta, adj_pct,
             adj_reason_cat, adj_evidence, self.ctx["userno"], "已提交")
        )
        return {"proc_batch": proc_batch, "part_no": part_no, "period": period, "adj_qty": adj_qty}

    # ========== 修正核对（步骤4） ==========

    def check_line(self, proc_batch: str, part_no: str, veh_model: str, period: str,
                   chk_result: str, chk_reason: str = "", chk_adj_qty: float = None):
        """核对：通过/退回。退回须附书面理由。"""
        if chk_result not in ("通过", "退回"):
            raise FdeError("核对结论必须为'通过'或'退回'")
        if chk_result == "退回" and not chk_reason.strip():
            raise FdeError("退回必须附书面理由（哪个视角不通过+需要什么证据）")
        adj = self.db.execute(
            "SELECT * FROM d04_adjustment WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=?",
            (proc_batch, part_no, veh_model, period)
        ).fetchone()
        if not adj:
            raise FdeError("修正行不存在")
        # 确定轮次
        last_round = self.db.execute(
            "SELECT MAX(chk_round) AS m FROM d04_check WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=?",
            (proc_batch, part_no, veh_model, period)
        ).fetchone()["m"] or 0
        chk_round = last_round + 1
        # BR-04: 2轮升级预警
        if chk_round > 2 and chk_result == "退回":
            pass  # 系统提示升级（由调用方处理）
        # 核对人调数登记（BR-02: 三件套双向约束）
        if chk_adj_qty is not None and chk_result == "通过":
            seq = self._next_log_seq(proc_batch, part_no, veh_model, period)
            self.db.execute(
                """INSERT INTO d04_log (proc_batch, part_no, veh_model, period, adj_seq,
                   actor_role, before_qty, after_qty, reason_cat, evidence, actor)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (proc_batch, part_no, veh_model, period, seq, "核对人",
                 adj["adj_qty"], chk_adj_qty, "核对校准", chk_reason, self.ctx["userno"])
            )
            approved_qty = chk_adj_qty
        else:
            approved_qty = adj["adj_qty"] if chk_result == "通过" else None
        self.db.execute(
            """INSERT INTO d04_check (proc_batch, part_no, veh_model, period, chk_round,
               chk_result, chk_reason, chk_adj_qty, approved_qty, checker)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (proc_batch, part_no, veh_model, period, chk_round, chk_result, chk_reason,
             chk_adj_qty, approved_qty, self.ctx["userno"])
        )
        if chk_result == "退回":
            # 重置修正提交状态
            self.db.execute(
                "UPDATE d04_adjustment SET submit_status='已退回·待重报' WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=?",
                (proc_batch, part_no, veh_model, period)
            )
        return {"proc_batch": proc_batch, "part_no": part_no, "period": period,
                "chk_result": chk_result, "chk_round": chk_round, "approved_qty": approved_qty}

    def get_line_status(self, proc_batch: str, part_no: str, veh_model: str, period: str):
        """查看行级状态"""
        adj = self.db.execute(
            "SELECT * FROM d04_adjustment WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=?",
            (proc_batch, part_no, veh_model, period)
        ).fetchone()
        checks = self.db.execute(
            "SELECT * FROM d04_check WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=? ORDER BY chk_round",
            (proc_batch, part_no, veh_model, period)
        ).fetchall()
        return {"adjustment": dict(adj) if adj else None, "checks": [dict(c) for c in checks]}

    def lock_batch(self, proc_batch: str):
        """锁定批次（D09发布联动触发）"""
        header = self._get_header(proc_batch)
        if header["status"] != "全部核定":
            raise FdeError(f"批次状态 {header['status']}，非全部核定不可锁定")
        self.db.execute(
            "UPDATE d04_header SET status='已锁定', finish_time=datetime('now','localtime') WHERE proc_batch=?",
            (proc_batch,)
        )
        return {"proc_batch": proc_batch, "status": "已锁定"}

    # ========== 内部辅助 ==========

    def _get_header(self, proc_batch: str):
        row = self.db.execute("SELECT * FROM d04_header WHERE proc_batch=?", (proc_batch,)).fetchone()
        if not row:
            raise FdeError(f"加工批次 {proc_batch} 不存在")
        return row

    def _next_log_seq(self, proc_batch: str, part_no: str, veh_model: str, period: str):
        row = self.db.execute(
            "SELECT COALESCE(MAX(adj_seq),0) AS m FROM d04_log WHERE proc_batch=? AND part_no=? AND veh_model=? AND period=?",
            (proc_batch, part_no, veh_model, period)
        ).fetchone()
        return (row["m"] if row else 0) + 1
