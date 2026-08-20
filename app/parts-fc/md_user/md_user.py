from fde import FdeError


class MdUser:
    """组织用户主数据聚合根。"""

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_user (
                user_code TEXT NOT NULL PRIMARY KEY,
                user_name TEXT NOT NULL,
                department TEXT NOT NULL,
                role TEXT NOT NULL
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_user_name ON md_user (user_name)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_user_department ON md_user (department)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_user_role ON md_user (role)")

    def create(self, user_code, user_name, department, role):
        user_code = self._clean(user_code)
        if not user_code:
            raise FdeError("user_code 必填，不能为空")

        if self._exists(user_code):
            raise FdeError("用户编码已存在")

        user_name = self._clean(user_name)
        if not user_name:
            raise FdeError("user_name 必填，不能为空")

        department = self._clean(department)
        if not department:
            raise FdeError("department 必填，不能为空")

        role = self._clean(role)
        if not role:
            raise FdeError("role 必填，不能为空")

        self.db.execute(
            "INSERT INTO md_user (user_code, user_name, department, role) VALUES (?, ?, ?, ?)",
            (user_code, user_name, department, role),
        )

        return self.get(user_code)

    def get(self, user_code):
        user_code = self._clean(user_code)
        if not user_code:
            raise FdeError("user_code 必填，不能为空")

        row = self._row(user_code)
        if row is None:
            raise FdeError("用户不存在")

        return self._to_dict(row)

    def list(self, keyword=None, department=None, role=None, page=None, page_size=None):
        keyword = self._clean(keyword)
        department = self._clean(department)
        role = self._clean(role)

        sql = "SELECT user_code, user_name, department, role FROM md_user"
        clauses = []
        params = []

        if keyword:
            clauses.append(
                "("
                "user_code LIKE '%' || ? || '%' "
                "OR user_name LIKE '%' || ? || '%'"
                ")"
            )
            params.extend([keyword, keyword])

        if department:
            clauses.append("department = ?")
            params.append(department)

        if role:
            clauses.append("role = ?")
            params.append(role)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY user_code"
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

    def update(self, user_code, user_name=None, department=None, role=None):
        user_code = self._clean(user_code)
        if not user_code:
            raise FdeError("user_code 必填，不能为空")

        row = self._row(user_code)
        if row is None:
            raise FdeError("用户不存在")

        sets = []
        params = []

        if user_name is not None:
            v = self._clean(user_name)
            if not v:
                raise FdeError("user_name 不能为空")
            sets.append("user_name = ?")
            params.append(v)

        if department is not None:
            v = self._clean(department)
            if not v:
                raise FdeError("department 不能为空")
            sets.append("department = ?")
            params.append(v)

        if role is not None:
            v = self._clean(role)
            if not v:
                raise FdeError("role 不能为空")
            sets.append("role = ?")
            params.append(v)

        if not sets:
            return self.get(user_code)

        params.append(user_code)
        self.db.execute(
            "UPDATE md_user SET " + ", ".join(sets) + " WHERE user_code = ?",
            tuple(params),
        )

        return self.get(user_code)

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

    def _exists(self, user_code):
        return (
            self.db.execute(
                "SELECT 1 FROM md_user WHERE user_code = ?",
                (user_code,),
            ).fetchone()
            is not None
        )

    def _row(self, user_code):
        return self.db.execute(
            "SELECT user_code, user_name, department, role FROM md_user WHERE user_code = ?",
            (user_code,),
        ).fetchone()

    def _to_dict(self, row):
        return {
            "user_code": row["user_code"],
            "user_name": row["user_name"],
            "department": row["department"],
            "role": row["role"],
        }
