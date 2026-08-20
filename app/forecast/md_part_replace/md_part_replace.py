from fde import FdeError


class MdPartReplace:
    """替换关系聚合根。管理零件间替换/替代关系与ECN依据。"""

    VALID_REL_TYPES = ("替换", "替代")
    VALID_STATUSES = ("生效", "失效")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_part_replace (
                rel_no TEXT NOT NULL PRIMARY KEY,
                rel_type TEXT NOT NULL CHECK (rel_type IN ('替换', '替代')),
                old_part TEXT NOT NULL,
                new_part TEXT NOT NULL,
                switch_date TEXT DEFAULT '',
                ecn_no TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT '生效' CHECK (status IN ('生效', '失效'))
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_pr_old_part ON md_part_replace (old_part)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_pr_new_part ON md_part_replace (new_part)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_pr_rel_type ON md_part_replace (rel_type)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_pr_status ON md_part_replace (status)")

    def create(self, rel_no: str, rel_type: str, old_part: str, new_part: str, switch_date: str = None, ecn_no: str = None):
        rel_no = self._clean(rel_no)
        if not rel_no:
            raise FdeError("关系号必填，不能为空")
        if self._exists(rel_no):
            raise FdeError(f"替换关系 {rel_no} 已存在")
        rel_type = self._clean(rel_type)
        if rel_type not in self.VALID_REL_TYPES:
            raise FdeError(f"关系类型只能为 {'/'.join(self.VALID_REL_TYPES)}")
        old_part = self._clean(old_part)
        new_part = self._clean(new_part)
        if not old_part or not new_part:
            raise FdeError("旧件号和新件号必填")
        if rel_type == "替换" and old_part == new_part:
            raise FdeError("替换关系中旧件号与新件号不能相同")

        try:
            self.fde.call("md_material", "get", part_no=old_part)
        except FdeError:
            raise FdeError(f"旧件物料 {old_part} 不存在") from None
        try:
            self.fde.call("md_material", "get", part_no=new_part)
        except FdeError:
            raise FdeError(f"新件物料 {new_part} 不存在") from None

        self.db.execute(
            "INSERT INTO md_part_replace (rel_no, rel_type, old_part, new_part, switch_date, ecn_no, status) VALUES (?, ?, ?, ?, ?, ?, '生效')",
            (rel_no, rel_type, old_part, new_part, self._clean(switch_date), self._clean(ecn_no)),
        )
        return self.get(rel_no)

    def get(self, rel_no: str):
        rel_no = self._clean(rel_no)
        if not rel_no:
            raise FdeError("关系号必填")
        row = self._row(rel_no)
        if row is None:
            raise FdeError(f"替换关系 {rel_no} 不存在")
        return dict(row)

    def list(self, rel_type: str = None, old_part: str = None, new_part: str = None, status: str = None, page: int = None, page_size: int = None):
        rel_type = self._clean(rel_type)
        old_part = self._clean(old_part)
        new_part = self._clean(new_part)
        status = self._clean(status)
        sql = "SELECT rel_no, rel_type, old_part, new_part, switch_date, ecn_no, status FROM md_part_replace"
        clauses, params = [], []
        if rel_type:
            if rel_type not in self.VALID_REL_TYPES:
                raise FdeError("关系类型筛选不合法")
            clauses.append("rel_type = ?")
            params.append(rel_type)
        if old_part:
            clauses.append("old_part LIKE '%' || ? || '%'")
            params.append(old_part)
        if new_part:
            clauses.append("new_part LIKE '%' || ? || '%'")
            params.append(new_part)
        if status:
            if status not in self.VALID_STATUSES:
                raise FdeError("状态筛选不合法")
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rel_no"
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

    def update(self, rel_no: str, rel_type: str = None, old_part: str = None, new_part: str = None,
               switch_date: str = None, ecn_no: str = None, status: str = None):
        rel_no = self._clean(rel_no)
        if not rel_no:
            raise FdeError("关系号必填")
        if not self._exists(rel_no):
            raise FdeError(f"替换关系 {rel_no} 不存在")
        updates, params = [], []
        if rel_type is not None:
            v = self._clean(rel_type)
            if v not in self.VALID_REL_TYPES:
                raise FdeError("关系类型不合法")
            updates.append("rel_type = ?")
            params.append(v)
        if old_part is not None:
            v = self._clean(old_part)
            if not v:
                raise FdeError("旧件号不能为空")
            updates.append("old_part = ?")
            params.append(v)
        if new_part is not None:
            v = self._clean(new_part)
            if not v:
                raise FdeError("新件号不能为空")
            updates.append("new_part = ?")
            params.append(v)
        for col, val in [("switch_date", switch_date), ("ecn_no", ecn_no)]:
            if val is not None:
                updates.append(f"{col} = ?")
                params.append(self._clean(val))
        if status is not None:
            v = self._clean(status)
            if v not in self.VALID_STATUSES:
                raise FdeError("状态不合法")
            updates.append("status = ?")
            params.append(v)
        if updates:
            params.append(rel_no)
            self.db.execute(f"UPDATE md_part_replace SET {', '.join(updates)} WHERE rel_no = ?", tuple(params))
        return self.get(rel_no)

    def disable(self, rel_no: str):
        rel_no = self._clean(rel_no)
        if not rel_no:
            raise FdeError("关系号必填")
        row = self._row(rel_no)
        if row is None:
            raise FdeError(f"替换关系 {rel_no} 不存在")
        if row["status"] == "失效":
            raise FdeError("替换关系已失效")
        self.db.execute("UPDATE md_part_replace SET status = '失效' WHERE rel_no = ?", (rel_no,))
        return self.get(rel_no)

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

    def _exists(self, rel_no):
        return self.db.execute("SELECT 1 FROM md_part_replace WHERE rel_no = ?", (rel_no,)).fetchone() is not None

    def _row(self, rel_no):
        return self.db.execute(
            "SELECT rel_no, rel_type, old_part, new_part, switch_date, ecn_no, status FROM md_part_replace WHERE rel_no = ?",
            (rel_no,),
        ).fetchone()
