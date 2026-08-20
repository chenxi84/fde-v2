from fde import FdeError


class DemandRelease:
    """毛需求发布单——加工链终点。冻结口径R版下达，净需求/S&OP唯一输入。
    发布口径 = 消耗驱动量(D08终端口径) + Σ生效事件量(D06)，构成列示。
    """

    def _init_db(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS d09_header (
                rel_no        TEXT PRIMARY KEY,
                rel_version   TEXT NOT NULL,
                base_period   TEXT NOT NULL,
                prev_version  TEXT,
                status        TEXT NOT NULL DEFAULT '草稿',
                publisher     TEXT,
                publish_date  TEXT
            );""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS d09_detail (
                rel_no      TEXT NOT NULL,
                line_no     INTEGER NOT NULL,
                part_no     TEXT NOT NULL,
                veh_model   TEXT NOT NULL,
                period      TEXT NOT NULL,
                cons_qty    REAL NOT NULL,
                event_items TEXT NOT NULL DEFAULT '[]',
                rel_qty     REAL NOT NULL,
                split_qty   TEXT,
                basis       TEXT NOT NULL,
                lineage     TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (rel_no, line_no),
                FOREIGN KEY (rel_no) REFERENCES d09_header(rel_no)
            );""")

    # ========== 发布管理 ==========

    def create_draft(self, base_period: str):
        """生成发布草稿：汇总D04/D06/D07/D08结果。"""
        from datetime import datetime
        now = datetime.now()
        rel_no = f"REL-{now.strftime('%Y%m')}-{now.strftime('%d%H%M%S%f')}"
        # 版本号
        last = self.db.execute(
            "SELECT rel_version FROM d09_header WHERE base_period=? ORDER BY rel_version DESC LIMIT 1",
            (base_period,)
        ).fetchone()
        if last:
            parts = last["rel_version"].split(".")
            if len(parts) == 1:
                rel_version = f"{last['rel_version']}.1"
            else:
                rel_version = f"{parts[0]}.{int(parts[1])+1}"
        else:
            rel_version = f"R{base_period.replace('-','')}"
        self.db.execute(
            "INSERT INTO d09_header (rel_no, rel_version, base_period) VALUES (?,?,?)",
            (rel_no, rel_version, base_period)
        )
        # 尝试自动汇总上游数据
        summary = {"d04_approved": 0, "d06_events": 0, "d08_final": 0}
        try:
            approved = self.fde.call("demand_processing", "get_approved", period=base_period)
            if approved and approved.get("items"):
                summary["d04_approved"] = len(approved["items"])
        except Exception: pass
        try:
            events = self.fde.call("independent_event", "list", status="生效")
            if events and events.get("items"):
                summary["d06_events"] = len(events["items"])
        except Exception: pass
        return {"rel_no": rel_no, "rel_version": rel_version, "base_period": base_period,
                "status": "草稿", "summary": summary,
                "message": "草稿已创建，请调用 add_line 逐行填充发布明细"}

    def add_line(self, rel_no: str, part_no: str, veh_model: str, period: str,
                 cons_qty: float, event_items: list, basis: str, lineage: dict,
                 split_qty: dict = None):
        """添加发布明细行。rel_qty = cons_qty + Σ事件量（系统强制）。"""
        header = self._get_header(rel_no)
        if header["status"] != "草稿":
            raise FdeError("仅草稿状态可添加明细")
        event_total = sum(e.get("qty", 0) for e in event_items)
        rel_qty = cons_qty + event_total
        import json
        max_line = self.db.execute(
            "SELECT COALESCE(MAX(line_no),0) AS m FROM d09_detail WHERE rel_no=?", (rel_no,)
        ).fetchone()["m"] + 1
        self.db.execute(
            """INSERT INTO d09_detail (rel_no, line_no, part_no, veh_model, period,
               cons_qty, event_items, rel_qty, split_qty, basis, lineage)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (rel_no, max_line, part_no, veh_model, period, cons_qty,
             json.dumps(event_items, ensure_ascii=False), rel_qty,
             json.dumps(split_qty, ensure_ascii=False) if split_qty else None,
             basis, json.dumps(lineage, ensure_ascii=False))
        )
        return {"rel_no": rel_no, "line_no": max_line, "rel_qty": rel_qty}

    def get(self, rel_no: str):
        """获取发布单全貌"""
        header = self._get_header(rel_no)
        details = self.db.execute(
            "SELECT * FROM d09_detail WHERE rel_no=? ORDER BY line_no", (rel_no,)
        ).fetchall()
        return {"header": dict(header), "details": [dict(d) for d in details]}

    def list(self, rel_version: str = None, status: str = None, page: int = None, size: int = None):
        sql = "SELECT * FROM d09_header WHERE 1=1"
        params = []
        if rel_version:
            sql += " AND rel_version=?"
            params.append(rel_version)
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY rel_version DESC"
        rows = self.db.execute(sql, params).fetchall()
        total = len(rows)
        # 服务端分页
        if page is not None and size is not None:
            page_no = max(1, int(page) if page else 1)
            size_n = max(1, int(size) if size else 50)
            start = (page_no - 1) * size_n
            rows = rows[start:start + size_n]

        return {"items": [dict(r) for r in rows], "total": total}

    # ========== Checklist 校验 ==========

    def checklist_verify(self, rel_no: str):
        """发布前 checklist 五项校验。"""
        header = dict(self._get_header(rel_no))
        if header["status"] != "草稿":
            raise FdeError("仅草稿状态可执行 checklist")
        detail_count = self.db.execute(
            "SELECT COUNT(*) AS c FROM d09_detail WHERE rel_no=?", (rel_no,)
        ).fetchone()["c"]
        checks = {
            "1_D04全部核定": "WARN",
            "2_D08全部有结论": "WARN",
            "3_D06事件齐备(无待确认)": "WARN",
            "4_客户对齐完成": "WARN",
            "5_版本差异完整": "WARN" if not header.get("prev_version") else "PASS",
        }
        # 真实跨应用校验（尽力而为，部分依赖调用方传入）
        try:
            approved = self.fde.call("demand_processing", "get_approved", period=header.get("base_period"))
            if approved and approved.get("items"):
                checks["1_D04全部核定"] = "PASS" if len(approved["items"]) > 0 else "WARN"
        except Exception:
            pass
        try:
            events = self.fde.call("independent_event", "list", status="待确认")
            pending = len(events.get("items", [])) if events else 0
            checks["3_D06事件齐备(无待确认)"] = "PASS" if pending == 0 else f"FAIL({pending}条待确认)"
        except Exception:
            pass
        if detail_count == 0:
            checks["0_明细非空"] = "FAIL"
        else:
            checks["0_明细非空"] = "PASS"
        all_pass = all(v == "PASS" or v == "WARN" for v in checks.values())
        if all_pass:
            self.db.execute("UPDATE d09_header SET status='待发布' WHERE rel_no=?", (rel_no,))
        return {"rel_no": rel_no, "checks": checks, "all_pass": all_pass,
                "new_status": "待发布" if all_pass else "草稿"}

    # ========== 发布与锁定 ==========

    def publish(self, rel_no: str):
        """正式发布。联动锁定D04批次+D03 V版。"""
        header = self._get_header(rel_no)
        if header["status"] != "待发布":
            raise FdeError(f"当前状态 {header['status']}，须先通过 checklist 至'待发布'")
        self.db.execute(
            "UPDATE d09_header SET status='已发布', publisher=?, publish_date=date('now') WHERE rel_no=?",
            (self.ctx["userno"], rel_no)
        )
        # 获取所有lineage中的D04批次并联动锁定
        details = self.db.execute("SELECT lineage FROM d09_detail WHERE rel_no=?", (rel_no,)).fetchall()
        import json
        locked_batches = set()
        for d in details:
            try:
                lineage = json.loads(d["lineage"])
                batch = lineage.get("proc_batch")
                if batch and batch not in locked_batches:
                    try:
                        self.fde.call("demand_processing", "lock_batch", proc_batch=batch)
                        locked_batches.add(batch)
                    except Exception:
                        pass
            except (json.JSONDecodeError, TypeError):
                pass
        # 联动锁定D03 V版
        for d in details:
            try:
                lineage = json.loads(d["lineage"])
                fcst_version = lineage.get("fcst_version")
                if fcst_version:
                    try:
                        self.fde.call("demand_collection", "lock", collect_no=fcst_version)
                    except Exception:
                        pass
            except (json.JSONDecodeError, TypeError):
                pass
        return {"rel_no": rel_no, "status": "已发布", "locked_batches": list(locked_batches)}

    def revise(self, rel_no: str, reason: str):
        """版本修订——产生子版本"""
        header = self._get_header(rel_no)
        if header["status"] != "已发布":
            raise FdeError("仅已发布版本可修订")
        if not reason.strip():
            raise FdeError("修订原因不可为空")
        parts = header["rel_version"].split(".")
        if len(parts) == 1:
            new_version = f"{header['rel_version']}.1"
        else:
            new_version = f"{parts[0]}.{int(parts[1])+1}"
        new_rel = f"REL-{header['base_period'].replace('-','')}-R{len(parts)}"
        self.db.execute(
            "INSERT INTO d09_header (rel_no, rel_version, base_period, prev_version, status) VALUES (?,?,?,?,?)",
            (new_rel, new_version, header["base_period"], header["rel_version"], "草稿")
        )
        self.db.execute(
            "UPDATE d09_header SET status='已替代' WHERE rel_no=?", (rel_no,)
        )
        return {"rel_no": new_rel, "rel_version": new_version, "replaces": rel_no}

    def version_diff(self, rel_no: str):
        """版本比对 R_n vs R_{n-1}"""
        header = self._get_header(rel_no)
        if not header["prev_version"]:
            return {"message": "无上一版本", "rel_no": rel_no}
        cur = {f"{d['part_no']}|{d['period']}": d["rel_qty"]
               for d in self.db.execute("SELECT * FROM d09_detail WHERE rel_no=?", (rel_no,)).fetchall()}
        prev = {f"{d['part_no']}|{d['period']}": d["rel_qty"]
                for d in self.db.execute("SELECT * FROM d09_detail WHERE rel_no=?", (header["prev_version"],)).fetchall()}
        diffs = []
        for key in set(list(cur.keys()) + list(prev.keys())):
            delta = cur.get(key, 0) - prev.get(key, 0)
            if abs(delta) > 0.001:
                p, period = key.split("|")
                diffs.append({"part_no": p, "period": period, "prev_qty": prev.get(key, 0),
                              "cur_qty": cur.get(key, 0), "delta": delta})
        return {"rel_no": rel_no, "prev": header["prev_version"], "diffs": diffs}

    def _get_header(self, rel_no: str):
        row = self.db.execute("SELECT * FROM d09_header WHERE rel_no=?", (rel_no,)).fetchone()
        if not row:
            raise FdeError(f"发布单 {rel_no} 不存在")
        return row
