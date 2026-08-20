from fde import FdeError
import json


class DemandRelease:
    """毛需求发布聚合根。加工链终点，物料×期间平铺，按版本管理。"""

    VALID_STATUSES = ("草稿", "已发布", "已替代")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS demand_release (
                fcst_version TEXT NOT NULL,
                part_no TEXT NOT NULL,
                period TEXT NOT NULL,
                prelim_qty REAL NOT NULL DEFAULT 0,
                part_adj TEXT DEFAULT '[]',
                onetime_items TEXT DEFAULT '[]',
                rel_qty REAL NOT NULL DEFAULT 0,
                basis TEXT DEFAULT '',
                lineage TEXT DEFAULT '{}',
                status TEXT NOT NULL DEFAULT '草稿' CHECK (status IN ('草稿', '已发布', '已替代')),
                publisher TEXT DEFAULT '',
                published_at TEXT DEFAULT '',
                prev_version TEXT DEFAULT '',
                PRIMARY KEY (fcst_version, part_no, period)
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_dr_part ON demand_release (part_no)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_dr_period ON demand_release (period)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_dr_status ON demand_release (status)")

    def create_draft(self, fcst_version: str):
        """从已锁定加工数据创建发布草稿：汇总→初步毛需求"""
        fcst_version = self._clean(fcst_version)
        if not fcst_version:
            raise FdeError("版本号必填")

        try:
            proc = self.fde.call("forecast_processing", "get_version", fcst_version=fcst_version)
        except FdeError:
            raise FdeError(f"版本 {fcst_version} 无加工数据") from None

        if proc.get("status") != "已锁定":
            raise FdeError(f"版本 {fcst_version} 加工未锁定（当前状态：{proc.get('status')}），无法创建发布")

        existing = self.db.execute(
            "SELECT COUNT(*) as cnt FROM demand_release WHERE fcst_version = ?", (fcst_version,)
        ).fetchone()
        if existing and existing["cnt"] > 0:
            raise FdeError(f"版本 {fcst_version} 已存在发布数据")

        # 汇总加工明细：按物料×期间汇总 indep_qty → 初步毛需求
        lines = proc.get("lines", [])
        agg = {}
        for line in lines:
            key = (line.get("part_no", ""), line.get("period", ""))
            if key not in agg: agg[key] = 0
            agg[key] += line.get("indep_qty", 0) or 0

        created = 0
        lineage = json.dumps({"fcst_version": fcst_version}, ensure_ascii=False)
        for (part_no, period), prelim_qty in sorted(agg.items()):
            self.db.execute(
                "INSERT INTO demand_release (fcst_version, part_no, period, prelim_qty, rel_qty, lineage) VALUES (?, ?, ?, ?, ?, ?)",
                (fcst_version, part_no, period, round(prelim_qty, 2), round(prelim_qty, 2), lineage),
            )
            created += 1

        return {"fcst_version": fcst_version, "created": created, "status": "草稿"}

    def apply_part_adj(self, fcst_version: str, part_no: str, period: str, adj_qty: float, func_type: str, basis: str):
        """应用零件级处理量"""
        fcst_version = self._clean(fcst_version); part_no = self._clean(part_no); period = self._clean(period)
        if not all([fcst_version, part_no, period]):
            raise FdeError("版本号、零件号、期间均必填")

        row = self._row(fcst_version, part_no, period)
        if row is None:
            raise FdeError(f"发布行不存在：{fcst_version}/{part_no}/{period}")
        if row["status"] == "已发布":
            raise FdeError("发布单已发布，不可修改")

        part_adj_list = json.loads(row["part_adj"]) if row["part_adj"] else []
        part_adj_list.append({"func_type": func_type, "basis": basis, "qty": adj_qty})
        total_adj = sum(item.get("qty", 0) for item in part_adj_list)
        new_rel_qty = round(row["prelim_qty"] + total_adj, 2)

        self.db.execute(
            "UPDATE demand_release SET part_adj = ?, rel_qty = ? WHERE fcst_version = ? AND part_no = ? AND period = ?",
            (json.dumps(part_adj_list, ensure_ascii=False), new_rel_qty, fcst_version, part_no, period),
        )
        return self.get(fcst_version, part_no, period)

    def publish(self, fcst_version: str):
        """发布：状态→已发布；联动锁定快照与月度版本"""
        fcst_version = self._clean(fcst_version)
        rows = self.db.execute(
            "SELECT status FROM demand_release WHERE fcst_version = ?", (fcst_version,)
        ).fetchall()
        if not rows:
            raise FdeError("版本无发布数据")
        statuses = set(r["status"] for r in rows)
        if "已发布" in statuses:
            raise FdeError("该版本已发布")

        now = self._now()
        publisher = self.ctx.get("userno", "")
        self.db.execute(
            "UPDATE demand_release SET status = '已发布', publisher = ?, published_at = ? WHERE fcst_version = ?",
            (publisher, now, fcst_version),
        )

        # 联动锁定
        try: self.fde.call("forecast_snapshot", "lock_version", fcst_version=fcst_version)
        except FdeError: pass
        try: self.fde.call("md_fcst_version", "set_linked", fcst_version=fcst_version, rel_no=fcst_version)
        except FdeError: pass

        # 标记上一版本
        prev_rows = self.db.execute(
            "SELECT DISTINCT fcst_version FROM demand_release WHERE status = '已发布' AND fcst_version < ? ORDER BY fcst_version DESC LIMIT 1",
            (fcst_version,)
        ).fetchall()
        if prev_rows:
            prev = prev_rows[0]["fcst_version"]
            self.db.execute("UPDATE demand_release SET status = '已替代' WHERE fcst_version = ?", (prev,))

        return {"fcst_version": fcst_version, "status": "已发布"}

    def get(self, fcst_version: str, part_no: str, period: str):
        row = self._row(fcst_version, part_no, period)
        if row is None:
            raise FdeError(f"发布行不存在：{fcst_version}/{part_no}/{period}")
        d = dict(row)
        for f in ["part_adj", "onetime_items", "lineage"]:
            try: d[f] = json.loads(d[f]) if isinstance(d[f], str) else d[f]
            except: d[f] = [] if f != "lineage" else {}
        return d

    def get_version(self, fcst_version: str):
        """取版本全部发布行"""
        rows = self.db.execute(
            "SELECT fcst_version, part_no, period, prelim_qty, part_adj, onetime_items, rel_qty, basis, lineage, status, publisher, published_at FROM demand_release WHERE fcst_version = ? ORDER BY part_no, period",
            (fcst_version,),
        ).fetchall()
        if not rows:
            raise FdeError(f"版本 {fcst_version} 无发布数据")
        lines = []
        for r in rows:
            d = dict(r)
            for f in ["part_adj", "onetime_items", "lineage"]:
                try: d[f] = json.loads(d[f]) if isinstance(d[f], str) else d[f]
                except: d[f] = [] if f != "lineage" else {}
            lines.append(d)
        return {
            "fcst_version": fcst_version,
            "status": rows[0]["status"],
            "publisher": rows[0]["publisher"],
            "published_at": rows[0]["published_at"],
            "lines": lines,
        }

    def list(self, fcst_version: str = None, part_no: str = None, period: str = None, status: str = None,
             page: int = None, page_size: int = None):
        fcst_version = self._clean(fcst_version); part_no = self._clean(part_no)
        period = self._clean(period); status = self._clean(status)
        if status and status not in self.VALID_STATUSES: raise FdeError("状态筛选不合法")

        sql = "SELECT fcst_version, part_no, period, prelim_qty, part_adj, onetime_items, rel_qty, basis, lineage, status, publisher, published_at FROM demand_release"
        clauses, params = [], []
        for col, val in [("fcst_version", fcst_version), ("part_no", part_no), ("period", period), ("status", status)]:
            if val: clauses.append(f"{col} = ?"); params.append(val)
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY fcst_version DESC, part_no, period"
        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [dict(r) for r in rows]
        total = len(items)
        if page is None and page_size is None: return {"total": total, "items": items}
        page_no = self._to_int(page, 1); page_sz = self._to_int(page_size, 50)
        if page_no < 1: page_no = 1
        if page_sz < 1: page_sz = 50
        start = (page_no - 1) * page_sz
        return {"total": total, "items": items[start:start + page_sz]}

    def add_onetime_item(self, fcst_version: str, part_no: str, period: str, onetime_adj: float, reason: str):
        """月中附加一次性调整"""
        fcst_version = self._clean(fcst_version); part_no = self._clean(part_no)
        period = self._clean(period); reason = self._clean(reason)
        if not all([fcst_version, part_no, period, reason]):
            raise FdeError("版本号、零件号、期间、原因均必填")

        row = self._row(fcst_version, part_no, period)
        items = json.loads(row["onetime_items"]) if row and row["onetime_items"] else []
        items.append({"qty": onetime_adj, "reason": reason})
        new_rel_qty = round((row["rel_qty"] if row else 0) + onetime_adj, 2)

        if row:
            self.db.execute(
                "UPDATE demand_release SET onetime_items = ?, rel_qty = ? WHERE fcst_version = ? AND part_no = ? AND period = ?",
                (json.dumps(items, ensure_ascii=False), new_rel_qty, fcst_version, part_no, period),
            )
        else:
            self.db.execute(
                "INSERT INTO demand_release (fcst_version, part_no, period, prelim_qty, part_adj, onetime_items, rel_qty, basis, lineage) VALUES (?, ?, ?, 0, '[]', ?, ?, '月中附加', '{}')",
                (fcst_version, part_no, period, json.dumps(items, ensure_ascii=False), onetime_adj),
            )
        return self.get(fcst_version, part_no, period)

    def _clean(self, value):
        if value is None: return ""
        return str(value).strip()

    def _to_int(self, value, default):
        if value is None: return default
        if isinstance(value, str) and not value.strip(): return default
        try: return int(value)
        except (TypeError, ValueError): raise FdeError("分页参数非法")

    def _now(self):
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def _row(self, fcst_version, part_no, period):
        return self.db.execute(
            "SELECT fcst_version, part_no, period, prelim_qty, part_adj, onetime_items, rel_qty, basis, lineage, status, publisher, published_at FROM demand_release WHERE fcst_version = ? AND part_no = ? AND period = ?",
            (fcst_version, part_no, period),
        ).fetchone()
