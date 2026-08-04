from fde import FdeError


class Member:
    """成员主数据聚合根。"""

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS member (
                member_no TEXT NOT NULL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_member_role ON member (role)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_member_name ON member (name)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_member_created_at ON member (created_at)")

    def create(self, member_no: str, name: str, email: str, role: str):
        member_no = self._clean(member_no)
        if not member_no:
            raise FdeError("member_no 必填，不能为空")

        if self._member_exists(member_no):
            raise FdeError("成员编号已存在")

        name = self._clean(name)
        if not name:
            raise FdeError("name 必填，不能为空")

        email = self._clean(email)
        if not email:
            raise FdeError("email 必填，不能为空")
        self._validate_email(email)

        if self._email_exists(email):
            raise FdeError("邮箱已存在")

        role = self._clean(role)
        if not role:
            raise FdeError("role 必填，不能为空")
        self._validate_role(role)

        self.db.execute(
            "INSERT INTO member (member_no, name, email, role) VALUES (?, ?, ?, ?)",
            (member_no, name, email, role),
        )

        return {
            "member_no": member_no,
            "name": name,
            "email": email,
            "role": role,
        }

    def get(self, member_no: str):
        member_no = self._clean(member_no)
        if not member_no:
            raise FdeError("member_no 必填，不能为空")

        row = self._row(member_no)
        if row is None:
            raise FdeError("成员不存在")

        return self._to_dict(row)

    def list(self, keyword: str = None, role: str = None, page: int = None, page_size: int = None):
        keyword = self._clean(keyword)
        role = self._clean(role)

        if role:
            self._validate_role(role)

        sql = "SELECT member_no, name, email, role FROM member"
        clauses = []
        params = []

        if keyword:
            clauses.append(
                "("
                "member_no LIKE '%' || ? || '%' "
                "OR name LIKE '%' || ? || '%' "
                "OR email LIKE '%' || ? || '%'"
                ")"
            )
            params.extend([keyword, keyword, keyword])

        if role:
            clauses.append("role = ?")
            params.append(role)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY created_at, member_no"
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

    def _validate_email(self, email):
        if email.count("@") != 1:
            raise FdeError("邮箱格式非法")

        local, domain = email.split("@")
        if not local or not domain:
            raise FdeError("邮箱格式非法")

    def _validate_role(self, role):
        if role not in ("admin", "member"):
            raise FdeError("角色只能为 admin 或 member")

    def _member_exists(self, member_no):
        return (
            self.db.execute(
                "SELECT 1 FROM member WHERE member_no = ?",
                (member_no,),
            ).fetchone()
            is not None
        )

    def _email_exists(self, email):
        return (
            self.db.execute(
                "SELECT 1 FROM member WHERE email = ?",
                (email,),
            ).fetchone()
            is not None
        )

    def _row(self, member_no):
        return self.db.execute(
            "SELECT member_no, name, email, role FROM member WHERE member_no = ?",
            (member_no,),
        ).fetchone()

    def _to_dict(self, row):
        return {
            "member_no": row["member_no"],
            "name": row["name"],
            "email": row["email"],
            "role": row["role"],
        }