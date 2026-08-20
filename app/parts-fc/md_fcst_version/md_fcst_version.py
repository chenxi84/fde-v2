from fde import FdeError


class MdFcstVersion:
    """预测版本主数据聚合根。版本号严格按月，格式 V+YYYYMM（如 V202601）。"""

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_fcst_version (
                version_code TEXT NOT NULL PRIMARY KEY,
                period       TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT '活跃'
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_fcst_version_period ON md_fcst_version (period)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_fcst_version_status ON md_fcst_version (status)")

    def create(self, version_code, period, status="活跃"):
        version_code = self._clean(version_code)
        if not version_code:
            raise FdeError("version_code 必填，不能为空")

        import re
        if not re.match(r'^V\d{6}$', version_code):
            raise FdeError("版本号格式须为 V+YYYYMM，如 V202601")

        if self._exists(version_code):
            raise FdeError("版本号已存在")

        period = self._clean(period)
        if not period:
            raise FdeError("period 必填，不能为空")
        if not re.match(r'^\d{4}-\d{2}$', period):
            raise FdeError("期间格式须为 YYYY-MM，如 2026-01")

        # 一致性校验：V202601 ↔ 2026-01
        expected_period = version_code[1:5] + "-" + version_code[5:7]
        if period != expected_period:
            raise FdeError(f"版本号 {version_code} 与期间 {period} 不匹配，期望 {expected_period}")

        status = self._clean(status)
        if not status:
            status = "活跃"

        self.db.execute(
            "INSERT INTO md_fcst_version (version_code, period, status) VALUES (?, ?, ?)",
            (version_code, period, status),
        )

        return self.get(version_code)

    def get(self, version_code):
        version_code = self._clean(version_code)
        if not version_code:
            raise FdeError("version_code 必填，不能为空")

        row = self._row(version_code)
        if row is None:
            raise FdeError("版本不存在")

        return self._to_dict(row)

    def list(self, keyword=None, status=None, page=None, page_size=None):
        keyword = self._clean(keyword)
        status = self._clean(status)

        sql = "SELECT version_code, period, status FROM md_fcst_version"
        clauses = []
        params = []

        if keyword:
            clauses.append(
                "(version_code LIKE '%' || ? || '%' OR period LIKE '%' || ? || '%')"
            )
            params.extend([keyword, keyword])

        if status:
            clauses.append("status = ?")
            params.append(status)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY version_code DESC"
        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [self._to_dict(row) for row in rows]
        total = len(items)

        if page is not None and page_size is not None:
            page_no = self._to_int(page, 1)
            size_n = self._to_int(page_size, 50)
            if page_no < 1:
                page_no = 1
            if size_n < 1:
                size_n = 50
            start = (page_no - 1) * size_n
            items = items[start:start + size_n]

        return {"total": total, "items": items}

    def update(self, version_code, period=None, status=None):
        version_code = self._clean(version_code)
        if not version_code:
            raise FdeError("version_code 必填，不能为空")

        row = self._row(version_code)
        if row is None:
            raise FdeError("版本不存在")

        sets = []
        params = []

        if period is not None:
            v = self._clean(period)
            if not v:
                raise FdeError("period 不能为空")
            import re
            if not re.match(r'^\d{4}-\d{2}$', v):
                raise FdeError("期间格式须为 YYYY-MM")
            sets.append("period = ?")
            params.append(v)

        if status is not None:
            v = self._clean(status)
            if not v:
                raise FdeError("status 不能为空")
            sets.append("status = ?")
            params.append(v)

        if not sets:
            return self.get(version_code)

        params.append(version_code)
        self.db.execute(
            "UPDATE md_fcst_version SET " + ", ".join(sets) + " WHERE version_code = ?",
            tuple(params),
        )

        return self.get(version_code)

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

    def _exists(self, version_code):
        return (
            self.db.execute(
                "SELECT 1 FROM md_fcst_version WHERE version_code = ?",
                (version_code,),
            ).fetchone()
            is not None
        )

    def _row(self, version_code):
        return self.db.execute(
            "SELECT version_code, period, status FROM md_fcst_version WHERE version_code = ?",
            (version_code,),
        ).fetchone()

    def _to_dict(self, row):
        return {
            "version_code": row["version_code"],
            "period": row["period"],
            "status": row["status"],
        }
