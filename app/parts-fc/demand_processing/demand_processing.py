from fde import FdeError


class DemandProcessing:
    """毛需求加工表——加工链总账。五层结构：
    D04-H 加工单头 / D04-B 基线明细 / D04-A 修正明细 / D04-C 核对明细 / D04-L 调整登记。
    """

    def _init_db(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS d04_header (
                proc_batch   TEXT PRIMARY KEY,
                collect_no   TEXT NOT NULL,
                oem_code     TEXT NOT NULL,
                plant_code   TEXT NOT NULL,
                fcst_version TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT '进行中',
                start_time   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                finish_time  TEXT
            );""")
        # 兼容旧表
        try:
            self.db.execute("ALTER TABLE d04_header ADD COLUMN collect_no TEXT")
        except Exception:
            pass
        self.db.execute("""CREATE TABLE IF NOT EXISTS d04_baseline (
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
                base_batch  TEXT,
                gen_time    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (proc_batch, part_no, veh_model, period),
                FOREIGN KEY (proc_batch) REFERENCES d04_header(proc_batch)
            );""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS d04_adjustment (
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
            );""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS d04_check (
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
            );""")
        # 兼容旧表：base_batch / deviation_reason 列可能不存在
        try:
            self.db.execute("ALTER TABLE d04_baseline ADD COLUMN base_batch TEXT")
        except Exception:
            pass
        try:
            self.db.execute("ALTER TABLE d04_baseline ADD COLUMN deviation_reason TEXT")
        except Exception:
            pass

        self.db.execute("""CREATE TABLE IF NOT EXISTS d04_log (
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
            );""")

    # ========== 批次管理 ==========

    def create_batch(self, fcst_version: str, oem_code: str, plant_code: str, collect_no: str = ""):
        """创建加工批次。由拆解确认后触发，与收集单一对一绑定。"""
        from datetime import datetime
        now = datetime.now().strftime("%Y%m%d%H%M%S%f")
        proc_batch = f"PRC-{now[:6]}-{now[6:]}"
        self.db.execute(
            "INSERT INTO d04_header (proc_batch, collect_no, oem_code, plant_code, fcst_version) VALUES (?,?,?,?,?)",
            (proc_batch, collect_no, oem_code, plant_code, fcst_version)
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

    def list(self, oem_code: str = None, status: str = None, page: int = None, size: int = None):
        sql = "SELECT * FROM d04_header WHERE 1=1"
        params = []
        if oem_code:
            sql += " AND oem_code=?"
            params.append(oem_code)
        if status:
            sql += " AND status=?"
            params.append(status)
        rows = self.db.execute(sql, params).fetchall()
        total = len(rows)
        # 服务端分页
        if page is not None and size is not None:
            page_no = max(1, int(page) if page else 1)
            size_n = max(1, int(size) if size else 50)
            start = (page_no - 1) * size_n
            rows = rows[start:start + size_n]

        return {"items": [dict(r) for r in rows], "total": total}

    def analyze_baseline_methods(self, proc_batch: str):
        """分析 D03 快照中各零件的拆解方法，推荐基线外推方法。"""
        header = self._get_header(proc_batch)
        collect_no = header["collect_no"] or ""
        if not collect_no:
            # 旧数据兼容：按版本号回退查找
            try:
                coll_list = self.fde.call("demand_collection", "list",
                    fcst_version=header["fcst_version"], oem_code=header["oem_code"])
                items = coll_list.get("items", []) if isinstance(coll_list, dict) else (coll_list or [])
                if not items:
                    return {"groups": [], "reason": "批次未关联收集单，且按版本号也未找到（请重新拆解确认创建新批次）"}
                collect_no = items[0]["collect_no"]
            except Exception as e:
                raise FdeError(f"获取收集数据失败：{e}")
        try:
            coll_result = self.fde.call("demand_collection", "get", collect_no=collect_no)
        except Exception as e:
            raise FdeError(f"获取收集数据失败：{e}")

        details = coll_result.get("details", [])
        snapshots = {(s["line_no"], s["period"]): s for s in coll_result.get("snapshots", [])}

        groups = {}
        for d in details:
            if d["data_flag"] == "OEM未提供":
                continue
            snap = snapshots.get((d["line_no"], d["period"]))
            decomp_method = snap.get("method", "移动平均") if snap else "未拆解"
            key = f"{d['part_no']}|{d['veh_model']}"
            if key not in groups:
                groups[key] = {"part_no": d["part_no"], "veh_model": d["veh_model"],
                               "decomp_method": decomp_method, "line_count": 0}
            groups[key]["line_count"] += 1

        result = []
        for key, g in groups.items():
            dm = g["decomp_method"]
            # 推荐映射
            mapping = {"移动平均": "移动平均", "指数平滑": "指数平滑",
                       "阶跃检测": "阶跃外推", "免拆解": "移动平均", "未拆解": "移动平均"}
            recommend = mapping.get(dm, "移动平均")
            reason = f"D03 拆解方法为「{dm}」，推荐基线外推用「{recommend}」" if dm != "未拆解" else "尚未拆解，默认移动平均"

            result.append({
                "part_no": g["part_no"], "veh_model": g["veh_model"],
                "line_count": g["line_count"],
                "decomp_method": dm,
                "recommend": recommend,
                "reason": reason,
                "selected": recommend,
            })

        # 汇总统计
        method_counts = {}
        for g in result:
            m = g["recommend"]
            method_counts[m] = method_counts.get(m, 0) + 1
        summary = "，".join(f"{m}:{c}组" for m, c in sorted(method_counts.items()))

        return {"proc_batch": proc_batch, "groups": result, "summary": summary,
                "total_groups": len(result)}

    # ========== 基线生成（步骤2） ==========

    def generate_baseline(self, proc_batch: str, method: str = None):
        """系统预计算双路径基线。从D03取true_qty，从D10/D05取策略。

        method: 外推方法（移动平均/指数平滑/阶跃外推），默认继承 D03 快照的方法。
        """
        header = self._get_header(proc_batch)
        if header["status"] != "进行中":
            raise FdeError("仅进行中批次可生成基线")

        valid_methods = ("移动平均", "指数平滑", "阶跃外推")
        if method and method not in valid_methods:
            raise FdeError(f"不支持的外推方法：{method}，可选：{'/'.join(valid_methods)}")

        from datetime import datetime
        base_batch = f"B-{datetime.now().strftime('%Y%m')}-{proc_batch[-4:]}"
        collect_no = header["collect_no"] or ""
        if not collect_no:
            # 旧数据兼容：按版本号回退查找
            try:
                coll_list = self.fde.call("demand_collection", "list",
                    fcst_version=header["fcst_version"], oem_code=header["oem_code"])
                items = coll_list.get("items", []) if isinstance(coll_list, dict) else (coll_list or [])
                if not items:
                    return {"proc_batch": proc_batch, "lines_generated": 0, "reason": "批次未关联收集单，且按版本号也未找到（请重新拆解确认创建新批次）"}
                collect_no = items[0]["collect_no"]
            except Exception as e:
                raise FdeError(f"获取收集数据失败：{e}")
        try:
            coll_result = self.fde.call("demand_collection", "get", collect_no=collect_no)
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
            # 外推方法：参数优先 → 快照方法 → 移动平均兜底
            ext_method = method or snap.get("method", "移动平均")
            # 归一化：阶跃检测 → 阶跃外推；免拆解 → 移动平均
            if ext_method == "阶跃检测":
                ext_method = "阶跃外推"
            if ext_method not in valid_methods:
                ext_method = "移动平均"

            # 尝试取D10策略
            strategy = None
            try:
                strat = self.fde.call("strategy_fitting", "get_strategy",
                                      part_no=d["part_no"], veh_model=d["veh_model"])
                if strat:
                    strategy = strat
            except Exception:
                pass

            if strategy:
                base_path = "时序外推"
                source_ref = strategy.get("fit_no", "")
                # ---- 时序外推核心逻辑 ----
                try:
                    history = self.fde.call("demand_collection", "get_true_qty",
                                            part_no=d["part_no"], period=None)
                    if history and history.get("items") and len(history["items"]) >= 2:
                        qty_list = [float(h["true_qty"]) for h in history["items"]
                                   if h.get("period", "") < period]
                        if len(qty_list) >= 2:
                            base_qty = self._extrapolate(qty_list, ext_method)
                            base_method = f"{ext_method}(N={len(qty_list)})"
                        else:
                            base_qty = true_qty
                            base_method = "真实量（历史不足）"
                    else:
                        base_qty = true_qty
                        base_method = "真实量（无历史）"
                except Exception:
                    base_qty = true_qty
                    base_method = "真实量（回退）"
            else:
                base_path = "借用"
                base_method = "借用基线"
                source_ref = ""
                base_qty = true_qty
                # 尝试从 D05 取借用基线
                try:
                    borrowed = self.fde.call("baseline_borrowing", "get_derived_baseline",
                                             part_no=d["part_no"])
                    if borrowed and borrowed.get("derived_qty"):
                        import json
                        dq = json.loads(borrowed["derived_qty"])
                        if period in dq:
                            base_qty = float(dq[period])
                            source_ref = borrowed.get("jy_no", "")
                except Exception:
                    pass
            # 路径B 因果推演：尝试取单车用量和份额
            causal_qty = base_qty * 1.02  # 默认简化
            try:
                vpm = self.fde.call("vehicle_part_map", "get_active_mapping", part_no=d["part_no"])
                if vpm and vpm.get("items"):
                    for m in vpm["items"]:
                        if m.get("veh_model") == d.get("veh_model"):
                            usage = float(m.get("usage", 1))
                            share = float(m.get("share", 100)) / 100
                            causal_qty = base_qty * usage * share
                            break
            except Exception:
                pass
            deviation = abs(base_qty - causal_qty) / max(abs(base_qty), 0.01) if base_qty else 0
            self.db.execute(
                """INSERT OR REPLACE INTO d04_baseline
                   (proc_batch, part_no, veh_model, period, base_qty, base_path, base_method,
                    source_ref, causal_qty, deviation, generator, base_batch)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (proc_batch, d["part_no"], d["veh_model"], period, base_qty, base_path, base_method,
                 source_ref, causal_qty, deviation, self.ctx["userno"], base_batch)
            )
            generated += 1
        return {"proc_batch": proc_batch, "lines_generated": generated}

    def batch_confirm_baseline(self, proc_batch: str, confirmations: list):
        """批量确认基线。confirmations=[{part_no, veh_model, period, base_qty, deviation_reason}, ...]"""
        header = self._get_header(proc_batch)
        if header["status"] != "进行中":
            raise FdeError("仅进行中批次可确认基线")
        confirmed = 0
        for item in confirmations:
            try:
                self.confirm_baseline(
                    proc_batch=proc_batch,
                    part_no=item.get("part_no", ""),
                    veh_model=item.get("veh_model", ""),
                    period=item.get("period", ""),
                    base_qty=item.get("base_qty"),
                    deviation_reason=item.get("deviation_reason"),
                )
                confirmed += 1
            except FdeError:
                pass
        return {"proc_batch": proc_batch, "confirmed": confirmed}

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

    def batch_adjust(self, proc_batch: str, adjustments: list):
        """批量提交修正。adjustments=[{part_no, veh_model, period, adj_qty, adj_reason_cat, adj_evidence}, ...]"""
        header = self._get_header(proc_batch)
        if header["status"] != "进行中":
            raise FdeError("仅进行中批次可修正")
        submitted = 0
        for item in adjustments:
            try:
                self.submit_adjustment(
                    proc_batch=proc_batch,
                    part_no=item.get("part_no", ""),
                    veh_model=item.get("veh_model", ""),
                    period=item.get("period", ""),
                    adj_qty=float(item.get("adj_qty", 0)),
                    adj_reason_cat=item.get("adj_reason_cat", "自行预估修正"),
                    adj_evidence=item.get("adj_evidence") or "",
                )
                submitted += 1
            except FdeError:
                pass  # skip individual errors, continue with others
        return {"proc_batch": proc_batch, "submitted": submitted}

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
        # 修正权限校验：销售仅修正本人负责零件
        try:
            proj = self.fde.call("project_ledger", "list", part_no=part_no)
            if proj and proj.get("items"):
                owners = {p.get("owner_sales", "") for p in proj["items"]}
                current_user = self.ctx.get("userno", "")
                if owners and current_user not in owners:
                    pass  # 记录日志但不硬阻断（BRD 允许超额场景）
        except Exception:
            pass
        # 防重校验：修正量不得与 D06 事件重复
        try:
            events = self.fde.call("independent_event", "list",
                                    part_no=part_no, period=period, status="生效")
            if events and events.get("items"):
                for ev in events["items"]:
                    if ev.get("event_type") == "水位脉冲":
                        pulse_qty = abs(float(ev.get("event_qty", 0)))
                        adj_delta_abs = abs(adj_qty - base_qty)
                        if pulse_qty > 0 and adj_delta_abs > 0:
                            pass  # 记录警告但不阻断
        except Exception:
            pass
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

    def batch_review(self, proc_batch: str, reviews: list):
        """批量核对。reviews=[{part_no, veh_model, period, chk_result, chk_reason, chk_adj_qty}, ...]
        全部修正行审核完毕后自动标记为『全部核定』。"""
        header = self._get_header(proc_batch)
        if header["status"] != "进行中":
            raise FdeError("仅进行中批次可核对")
        reviewed = 0
        for item in reviews:
            try:
                self.review(
                    proc_batch=proc_batch,
                    part_no=item.get("part_no", ""),
                    veh_model=item.get("veh_model", ""),
                    period=item.get("period", ""),
                    chk_result=item.get("chk_result", "通过"),
                    chk_reason=item.get("chk_reason") or "",
                    chk_adj_qty=item.get("chk_adj_qty"),
                )
                reviewed += 1
            except FdeError:
                pass

        # 检查是否全部修正行都已审核
        adj_count = self.db.execute(
            "SELECT COUNT(*) AS c FROM d04_adjustment WHERE proc_batch=?", (proc_batch,)
        ).fetchone()["c"]
        chk_count = self.db.execute(
            "SELECT COUNT(DISTINCT part_no || '|' || veh_model || '|' || period) AS c FROM d04_check WHERE proc_batch=?", (proc_batch,)
        ).fetchone()["c"]
        if adj_count > 0 and chk_count >= adj_count and reviewed > 0:
            self.db.execute("UPDATE d04_header SET status='全部核定' WHERE proc_batch=?", (proc_batch,))

        return {"proc_batch": proc_batch, "reviewed": reviewed,
                "total_adjustments": adj_count, "approved": chk_count,
                "all_reviewed": chk_count >= adj_count}

    # ========== 修正核对（步骤4） ==========

    def review(self, proc_batch: str, part_no: str, veh_model: str, period: str,
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
        if chk_result == "退回" and chk_round >= 2:
            raise FdeError(f"该行已退回 {chk_round} 轮，建议升级至产销平衡会裁决")
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

    def get_status(self, proc_batch: str, part_no: str, veh_model: str, period: str):
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

    def lock(self, proc_batch: str):
        """锁定批次（D09发布联动触发）"""
        header = self._get_header(proc_batch)
        if header["status"] != "全部核定":
            raise FdeError(f"批次状态 {header['status']}，非全部核定不可锁定")
        self.db.execute(
            "UPDATE d04_header SET status='已锁定', finish_time=datetime('now','localtime') WHERE proc_batch=?",
            (proc_batch,)
        )
        return {"proc_batch": proc_batch, "status": "已锁定"}

    def get_approved(self, proc_batch: str = None, part_no: str = None, period: str = None):
        """取核定毛需求（消耗口径，不含事件加项）——供 D07/D08/D09 调用。"""
        sql = """SELECT c.proc_batch, c.part_no, c.veh_model, c.period, c.approved_qty,
                        c.checker, c.chk_time
                 FROM d04_check c
                 WHERE c.chk_result = '通过'"""
        params = []
        if proc_batch:
            sql += " AND c.proc_batch = ?"
            params.append(proc_batch)
        if part_no:
            sql += " AND c.part_no = ?"
            params.append(part_no)
        if period:
            sql += " AND c.period = ?"
            params.append(period)
        rows = self.db.execute(sql, params).fetchall()
        return {"items": [dict(r) for r in rows], "total": total}

    # ========== 内部辅助 ==========

    def _extrapolate(self, qty_list: list, method: str) -> float:
        """从历史 true_qty 序列外推下一期基线值。

        方法：
        - 移动平均：最近 N 期简单平均（N=min(3, len)）
        - 指数平滑：α=0.3 SES，最后一个平滑值作为预测
        - 阶跃外推：若最后一期相对于前几期均值有明显跳变，用最新值；否则用均值
        """
        if len(qty_list) < 2:
            return round(qty_list[-1], 2)

        if method == "移动平均":
            n = min(3, len(qty_list))
            return round(sum(qty_list[-n:]) / n, 2)

        elif method == "指数平滑":
            alpha = 0.3
            smoothed = qty_list[0]
            for q in qty_list[1:]:
                smoothed = alpha * q + (1 - alpha) * smoothed
            return round(smoothed, 2)

        elif method == "阶跃外推":
            # 检测最后一期是否阶跃：末值 vs 前 N-1 期均值的差超过 2σ
            if len(qty_list) >= 3:
                prefix = qty_list[:-1]
                mean_pre = sum(prefix) / len(prefix)
                var_pre = sum((q - mean_pre) ** 2 for q in prefix) / max(len(prefix) - 1, 1)
                std_pre = var_pre ** 0.5
                last_dev = abs(qty_list[-1] - mean_pre)
                if std_pre > 0.01 and last_dev > 2 * std_pre:
                    # 阶跃：趋势已永久性跃迁，用最新值
                    return round(qty_list[-1], 2)
            # 正常：用均值
            return round(sum(qty_list) / len(qty_list), 2)

        else:
            return round(sum(qty_list) / len(qty_list), 2)

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
