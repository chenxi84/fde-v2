from fde import FdeError


class MdProjectPart:
    """项目-零件映射聚合根。管理项目×零件×车型的量纲关系，是通用件识别与断点定量的依据。"""

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_project_part (
                project_no TEXT NOT NULL,
                part_no TEXT NOT NULL,
                veh_model TEXT DEFAULT '',
                usage REAL DEFAULT 0,
                share REAL DEFAULT 1.0,
                eff_from TEXT DEFAULT '',
                eff_to TEXT DEFAULT '',
                PRIMARY KEY (project_no, part_no)
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_pp_part_no ON md_project_part (part_no)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_pp_project_no ON md_project_part (project_no)")

    def create(self, project_no: str, part_no: str, veh_model: str = None, usage: float = None, share: float = None,
               eff_from: str = None, eff_to: str = None):
        project_no = self._clean(project_no)
        part_no = self._clean(part_no)
        if not project_no:
            raise FdeError("项目号必填，不能为空")
        if not part_no:
            raise FdeError("零件号必填，不能为空")
        if self._exists(project_no, part_no):
            raise FdeError(f"项目 {project_no} 与零件 {part_no} 的映射已存在")

        try:
            self.fde.call("md_project", "get", project_no=project_no)
        except FdeError:
            raise FdeError(f"项目 {project_no} 不存在") from None
        try:
            self.fde.call("md_material", "get", part_no=part_no)
        except FdeError:
            raise FdeError(f"物料 {part_no} 不存在") from None

        usage = self._to_float(usage, 0)
        share = self._to_float(share, 1.0)
        if not 0 <= share <= 1:
            raise FdeError("供应份额必须在 0~1 之间")

        self.db.execute(
            "INSERT INTO md_project_part (project_no, part_no, veh_model, usage, share, eff_from, eff_to) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_no, part_no, self._clean(veh_model), usage, share, self._clean(eff_from), self._clean(eff_to)),
        )
        return self.get(project_no, part_no)

    def get(self, project_no: str, part_no: str):
        project_no = self._clean(project_no)
        part_no = self._clean(part_no)
        if not project_no or not part_no:
            raise FdeError("项目号和零件号必填")
        row = self._row(project_no, part_no)
        if row is None:
            raise FdeError(f"项目 {project_no} 与零件 {part_no} 的映射不存在")
        return dict(row)

    def list(self, project_no: str = None, part_no: str = None, veh_model: str = None, page: int = None, page_size: int = None):
        project_no = self._clean(project_no)
        part_no = self._clean(part_no)
        veh_model = self._clean(veh_model)
        sql = "SELECT project_no, part_no, veh_model, usage, share, eff_from, eff_to FROM md_project_part"
        clauses, params = [], []
        if project_no:
            clauses.append("project_no LIKE '%' || ? || '%'")
            params.append(project_no)
        if part_no:
            clauses.append("part_no LIKE '%' || ? || '%'")
            params.append(part_no)
        if veh_model:
            clauses.append("veh_model LIKE '%' || ? || '%'")
            params.append(veh_model)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY project_no, part_no"
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

    def list_active(self):
        """取进行中项目的全部零件映射（供快照 opening 用）"""
        # 通过跨应用调用取活跃项目列表，再过滤本地数据（避免跨库 JOIN）
        try:
            active_projects = self.fde.call("md_project", "list_active")
        except FdeError:
            return []
        active_nos = [p.get("project_no", "") for p in active_projects if p.get("project_no")]
        if not active_nos:
            return []
        placeholders = ",".join(["?" for _ in active_nos])
        rows = self.db.execute(
            f"SELECT project_no, part_no, veh_model, usage, share, eff_from, eff_to FROM md_project_part WHERE project_no IN ({placeholders}) ORDER BY project_no, part_no",
            tuple(active_nos),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_by_part(self, part_no: str):
        """按零件查所有项目映射（通用件识别：同 part_no 出现在 ≥2 个不同客户的项目中）"""
        part_no = self._clean(part_no)
        if not part_no:
            raise FdeError("零件号必填")
        rows = self.db.execute(
            "SELECT project_no, part_no, veh_model, usage, share, eff_from, eff_to FROM md_project_part WHERE part_no = ? ORDER BY project_no",
            (part_no,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update(self, project_no: str, part_no: str, veh_model: str = None, usage: float = None, share: float = None,
               eff_from: str = None, eff_to: str = None):
        project_no = self._clean(project_no)
        part_no = self._clean(part_no)
        if not project_no or not part_no:
            raise FdeError("项目号和零件号必填")
        if not self._exists(project_no, part_no):
            raise FdeError(f"项目 {project_no} 与零件 {part_no} 的映射不存在")
        updates, params = [], []
        for col, val in [("veh_model", veh_model), ("eff_from", eff_from), ("eff_to", eff_to)]:
            if val is not None:
                updates.append(f"{col} = ?")
                params.append(self._clean(val))
        if usage is not None:
            updates.append("usage = ?")
            params.append(self._to_float(usage, 0))
        if share is not None:
            v = self._to_float(share, 1.0)
            if not 0 <= v <= 1:
                raise FdeError("供应份额必须在 0~1 之间")
            updates.append("share = ?")
            params.append(v)
        if updates:
            params.extend([project_no, part_no])
            self.db.execute(f"UPDATE md_project_part SET {', '.join(updates)} WHERE project_no = ? AND part_no = ?", tuple(params))
        return self.get(project_no, part_no)

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

    def _to_float(self, value, default):
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            raise FdeError("数值参数非法")

    def _exists(self, project_no, part_no):
        return self.db.execute(
            "SELECT 1 FROM md_project_part WHERE project_no = ? AND part_no = ?", (project_no, part_no)
        ).fetchone() is not None

    def _row(self, project_no, part_no):
        return self.db.execute(
            "SELECT project_no, part_no, veh_model, usage, share, eff_from, eff_to FROM md_project_part WHERE project_no = ? AND part_no = ?",
            (project_no, part_no),
        ).fetchone()
