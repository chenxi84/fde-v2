from fde import FdeError


class PartLevelAdj:
    """零件级处理聚合根。通用件合并/替换件合并/断点处理，产出 delta 作用回初步毛需求。"""

    VALID_FUNC_TYPES = ("通用件合并", "替换件合并", "断点处理")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS part_level_adj (
                adj_no TEXT NOT NULL PRIMARY KEY,
                func_type TEXT NOT NULL CHECK (func_type IN ('通用件合并', '替换件合并', '断点处理')),
                part_no TEXT NOT NULL,
                fcst_version TEXT NOT NULL,
                period TEXT NOT NULL,
                adj_qty REAL NOT NULL DEFAULT 0,
                basis TEXT NOT NULL DEFAULT '',
                pair_no TEXT DEFAULT '',
                owner TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_pla_version ON part_level_adj (fcst_version)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_pla_func ON part_level_adj (func_type)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_pla_part ON part_level_adj (part_no)")

    def create_generic_merge(self, fcst_version: str, period: str, part_no: str, adj_qty: float, basis: str):
        """通用件合并调整"""
        return self._create_adj(fcst_version, period, part_no, "通用件合并", adj_qty, basis)

    def create_replace_merge(self, fcst_version: str, period: str, part_no: str, adj_qty: float, basis: str):
        """替换件合并调整"""
        return self._create_adj(fcst_version, period, part_no, "替换件合并", adj_qty, basis)

    def create_breakpoint_adj(self, fcst_version: str, period: str, old_part: str, new_part: str,
                               old_adj: float, new_adj: float, ecn_no: str):
        """断点成对调整：旧件截断负量 + 新件启动正量"""
        fcst_version = self._clean(fcst_version)
        period = self._clean(period)
        ecn_no = self._clean(ecn_no)
        if not fcst_version or not period:
            raise FdeError("版本号和期间必填")
        if not ecn_no:
            raise FdeError("ECN号必填（断点依据）")

        pair_no = f"BP-{fcst_version}-{self._next_pair_seq():03d}"
        now = self._now()

        # 旧件截断（负量）
        old_adj_no = f"PAD-{fcst_version}-{self._next_seq(fcst_version):03d}"
        self.db.execute(
            "INSERT INTO part_level_adj (adj_no, func_type, part_no, fcst_version, period, adj_qty, basis, pair_no, owner, created_at) VALUES (?, '断点处理', ?, ?, ?, ?, ?, ?, ?, ?)",
            (old_adj_no, old_part, fcst_version, period, self._to_float(old_adj), f"ECN-{ecn_no} 旧件截断", pair_no, self.ctx.get("userno", ""), now),
        )

        # 新件启动（正量）
        new_adj_no = f"PAD-{fcst_version}-{self._next_seq(fcst_version):03d}"
        self.db.execute(
            "INSERT INTO part_level_adj (adj_no, func_type, part_no, fcst_version, period, adj_qty, basis, pair_no, owner, created_at) VALUES (?, '断点处理', ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_adj_no, new_part, fcst_version, period, self._to_float(new_adj), f"ECN-{ecn_no} 新件启动", pair_no, self.ctx.get("userno", ""), now),
        )

        return {
            "pair_no": pair_no,
            "old": self.get(old_adj_no),
            "new": self.get(new_adj_no),
        }

    def get(self, adj_no: str):
        adj_no = self._clean(adj_no)
        if not adj_no:
            raise FdeError("处理单号必填")
        row = self._row(adj_no)
        if row is None:
            raise FdeError(f"零件级处理 {adj_no} 不存在")
        return dict(row)

    def list(self, fcst_version: str = None, func_type: str = None, part_no: str = None, period: str = None,
             page: int = None, page_size: int = None):
        fcst_version = self._clean(fcst_version)
        func_type = self._clean(func_type)
        part_no = self._clean(part_no)
        period = self._clean(period)
        if func_type and func_type not in self.VALID_FUNC_TYPES:
            raise FdeError(f"功能类型只能为 {'/'.join(self.VALID_FUNC_TYPES)}")

        sql = "SELECT adj_no, func_type, part_no, fcst_version, period, adj_qty, basis, pair_no, owner, created_at FROM part_level_adj"
        clauses, params = [], []
        if fcst_version:
            clauses.append("fcst_version = ?")
            params.append(fcst_version)
        if func_type:
            clauses.append("func_type = ?")
            params.append(func_type)
        if part_no:
            clauses.append("part_no = ?")
            params.append(part_no)
        if period:
            clauses.append("period = ?")
            params.append(period)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY adj_no"
        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [dict(r) for r in rows]
        total = len(items)
        if page is None and page_size is None:
            return {"total": total, "items": items}
        page_no = self._to_int(page, 1)
        page_sz = self._to_int(page_size, 50)
        if page_no < 1:
            page_no = 1
        if page_sz < 1:
            page_sz = 50
        start = (page_no - 1) * page_sz
        return {"total": total, "items": items[start:start + page_sz]}

    def summarize(self, fcst_version: str):
        """汇总：按物料×期间聚合全部 delta"""
        fcst_version = self._clean(fcst_version)
        if not fcst_version:
            raise FdeError("版本号必填")
        rows = self.db.execute(
            "SELECT part_no, period, func_type, SUM(adj_qty) as total_adj, GROUP_CONCAT(basis, '; ') as reasons FROM part_level_adj WHERE fcst_version = ? GROUP BY part_no, period, func_type ORDER BY part_no, period",
            (fcst_version,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _create_adj(self, fcst_version, period, part_no, func_type, adj_qty, basis):
        fcst_version = self._clean(fcst_version)
        period = self._clean(period)
        part_no = self._clean(part_no)
        basis = self._clean(basis)
        if not all([fcst_version, period, part_no]):
            raise FdeError("版本号、期间、零件号均必填")
        if not basis:
            raise FdeError("原因/依据必填")

        adj_no = f"PAD-{fcst_version}-{self._next_seq(fcst_version):03d}"
        self.db.execute(
            "INSERT INTO part_level_adj (adj_no, func_type, part_no, fcst_version, period, adj_qty, basis, owner, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (adj_no, func_type, part_no, fcst_version, period, self._to_float(adj_qty), basis, self.ctx.get("userno", ""), self._now()),
        )
        return self.get(adj_no)

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _to_int(self, value, default):
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise FdeError("分页参数非法")

    def _to_float(self, value, default=0):
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            raise FdeError("数值参数非法")

    def _now(self):
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def _row(self, adj_no):
        return self.db.execute(
            "SELECT adj_no, func_type, part_no, fcst_version, period, adj_qty, basis, pair_no, owner, created_at FROM part_level_adj WHERE adj_no = ?",
            (adj_no,),
        ).fetchone()

    def _next_seq(self, fcst_version):
        row = self.db.execute(
            "SELECT COUNT(*) as cnt FROM part_level_adj WHERE fcst_version = ?", (fcst_version,)
        ).fetchone()
        return (row["cnt"] if row else 0) + 1

    def _next_pair_seq(self):
        row = self.db.execute("SELECT COUNT(*) as cnt FROM part_level_adj WHERE pair_no != ''").fetchone()
        return (row["cnt"] if row else 0) + 1
