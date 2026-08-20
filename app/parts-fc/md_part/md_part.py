from fde import FdeError


class MdPart:
    """物料主数据聚合根。"""

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_part (
                part_no TEXT NOT NULL PRIMARY KEY,
                part_name TEXT NOT NULL,
                part_type TEXT NOT NULL,
                unit TEXT NOT NULL,
                status TEXT NOT NULL
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_part_name ON md_part (part_name)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_part_type ON md_part (part_type)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_part_status ON md_part (status)")

    def create(self, part_no, part_name, part_type, unit, status):
        part_no = self._clean(part_no)
        if not part_no:
            raise FdeError("part_no 必填，不能为空")

        if self._exists(part_no):
            raise FdeError("物料编码已存在")

        part_name = self._clean(part_name)
        if not part_name:
            raise FdeError("part_name 必填，不能为空")

        part_type = self._clean(part_type)
        if not part_type:
            raise FdeError("part_type 必填，不能为空")

        unit = self._clean(unit)
        if not unit:
            raise FdeError("unit 必填，不能为空")

        status = self._clean(status)
        if not status:
            raise FdeError("status 必填，不能为空")

        self.db.execute(
            "INSERT INTO md_part (part_no, part_name, part_type, unit, status) VALUES (?, ?, ?, ?, ?)",
            (part_no, part_name, part_type, unit, status),
        )

        return self.get(part_no)

    def get(self, part_no):
        part_no = self._clean(part_no)
        if not part_no:
            raise FdeError("part_no 必填，不能为空")

        row = self._row(part_no)
        if row is None:
            raise FdeError("物料不存在")

        return self._to_dict(row)

    def list(self, keyword=None, part_type=None, status=None, page=None, page_size=None):
        keyword = self._clean(keyword)
        part_type = self._clean(part_type)
        status = self._clean(status)

        sql = "SELECT part_no, part_name, part_type, unit, status FROM md_part"
        clauses = []
        params = []

        if keyword:
            clauses.append(
                "("
                "part_no LIKE '%' || ? || '%' "
                "OR part_name LIKE '%' || ? || '%'"
                ")"
            )
            params.extend([keyword, keyword])

        if part_type:
            clauses.append("part_type = ?")
            params.append(part_type)

        if status:
            clauses.append("status = ?")
            params.append(status)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY part_no"
        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [self._to_dict(row) for row in rows]
        total = len(items)

        if page is None and page_size is None:
            return {"total": total, "items": items}

        page_no = self._to_int(page, 1)
        page_size = self._to_int(page_size, 50)

        if page_no < 1:
            page_no = 1
        if page_size < 1:
            page_size = 50

        start = (page_no - 1) * page_size
        return {"total": total, "items": items[start:start + page_size]}

    def update(self, part_no, part_name=None, part_type=None, unit=None, status=None):
        part_no = self._clean(part_no)
        if not part_no:
            raise FdeError("part_no 必填，不能为空")

        row = self._row(part_no)
        if row is None:
            raise FdeError("物料不存在")

        sets = []
        params = []

        if part_name is not None:
            v = self._clean(part_name)
            if not v:
                raise FdeError("part_name 不能为空")
            sets.append("part_name = ?")
            params.append(v)

        if part_type is not None:
            v = self._clean(part_type)
            if not v:
                raise FdeError("part_type 不能为空")
            sets.append("part_type = ?")
            params.append(v)

        if unit is not None:
            v = self._clean(unit)
            if not v:
                raise FdeError("unit 不能为空")
            sets.append("unit = ?")
            params.append(v)

        if status is not None:
            v = self._clean(status)
            if not v:
                raise FdeError("status 不能为空")
            sets.append("status = ?")
            params.append(v)

        if not sets:
            return self.get(part_no)

        params.append(part_no)
        self.db.execute(
            "UPDATE md_part SET " + ", ".join(sets) + " WHERE part_no = ?",
            tuple(params),
        )

        return self.get(part_no)

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

    def _exists(self, part_no):
        return (
            self.db.execute(
                "SELECT 1 FROM md_part WHERE part_no = ?",
                (part_no,),
            ).fetchone()
            is not None
        )

    def _row(self, part_no):
        return self.db.execute(
            "SELECT part_no, part_name, part_type, unit, status FROM md_part WHERE part_no = ?",
            (part_no,),
        ).fetchone()

    def _to_dict(self, row):
        return {
            "part_no": row["part_no"],
            "part_name": row["part_name"],
            "part_type": row["part_type"],
            "unit": row["unit"],
            "status": row["status"],
        }
