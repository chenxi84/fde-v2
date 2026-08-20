from fde import FdeError


class MdCalendar:
    """日历主数据聚合根。"""

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_calendar (
                date TEXT NOT NULL PRIMARY KEY,
                is_workday INTEGER NOT NULL DEFAULT 1,
                holiday_name TEXT NOT NULL DEFAULT ''
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_calendar_workday ON md_calendar (is_workday)")

    def create(self, date, is_workday, holiday_name):
        date = self._clean(date)
        if not date:
            raise FdeError("date 必填，不能为空")

        if self._exists(date):
            raise FdeError("该日期已存在")

        if is_workday is None:
            raise FdeError("is_workday 必填，不能为空")
        try:
            is_workday = int(is_workday)
        except (TypeError, ValueError):
            raise FdeError("is_workday 必须为 0 或 1")
        if is_workday not in (0, 1):
            raise FdeError("is_workday 只能为 0 或 1")

        holiday_name = self._clean(holiday_name)
        if is_workday == 0 and not holiday_name:
            raise FdeError("非工作日时 holiday_name 必填，不能为空")

        self.db.execute(
            "INSERT INTO md_calendar (date, is_workday, holiday_name) VALUES (?, ?, ?)",
            (date, is_workday, holiday_name),
        )

        return self.get(date)

    def get(self, date):
        date = self._clean(date)
        if not date:
            raise FdeError("date 必填，不能为空")

        row = self._row(date)
        if row is None:
            raise FdeError("日期不存在")

        return self._to_dict(row)

    def list(self, keyword=None, is_workday=None, page=None, page_size=None):
        keyword = self._clean(keyword)

        sql = "SELECT date, is_workday, holiday_name FROM md_calendar"
        clauses = []
        params = []

        if keyword:
            clauses.append(
                "("
                "date LIKE '%' || ? || '%' "
                "OR holiday_name LIKE '%' || ? || '%'"
                ")"
            )
            params.extend([keyword, keyword])

        if is_workday is not None:
            try:
                is_workday = int(is_workday)
            except (TypeError, ValueError):
                raise FdeError("is_workday 必须为 0 或 1")
            if is_workday not in (0, 1):
                raise FdeError("is_workday 只能为 0 或 1")
            clauses.append("is_workday = ?")
            params.append(is_workday)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY date"
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

    def update(self, date, is_workday=None, holiday_name=None):
        date = self._clean(date)
        if not date:
            raise FdeError("date 必填，不能为空")

        row = self._row(date)
        if row is None:
            raise FdeError("日期不存在")

        sets = []
        params = []

        if is_workday is not None:
            try:
                is_workday = int(is_workday)
            except (TypeError, ValueError):
                raise FdeError("is_workday 必须为 0 或 1")
            if is_workday not in (0, 1):
                raise FdeError("is_workday 只能为 0 或 1")
            sets.append("is_workday = ?")
            params.append(is_workday)

        if holiday_name is not None:
            v = self._clean(holiday_name)
            sets.append("holiday_name = ?")
            params.append(v)

        if not sets:
            return self.get(date)

        params.append(date)
        self.db.execute(
            "UPDATE md_calendar SET " + ", ".join(sets) + " WHERE date = ?",
            tuple(params),
        )

        return self.get(date)

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

    def _exists(self, date):
        return (
            self.db.execute(
                "SELECT 1 FROM md_calendar WHERE date = ?",
                (date,),
            ).fetchone()
            is not None
        )

    def _row(self, date):
        return self.db.execute(
            "SELECT date, is_workday, holiday_name FROM md_calendar WHERE date = ?",
            (date,),
        ).fetchone()

    def _to_dict(self, row):
        return {
            "date": row["date"],
            "is_workday": row["is_workday"],
            "holiday_name": row["holiday_name"],
        }
