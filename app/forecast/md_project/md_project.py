from fde import FdeError


class MdProject:
    """项目台账聚合根。管理项目生命周期信息，定义活跃行集（进行中项目）。"""

    VALID_STAGES = ("待定点", "定点中", "进行中", "EOP关闭")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_project (
                project_no TEXT NOT NULL PRIMARY KEY,
                project_name TEXT NOT NULL,
                stage TEXT NOT NULL CHECK (stage IN ('待定点', '定点中', '进行中', 'EOP关闭')),
                oem_code TEXT NOT NULL,
                plant_code TEXT NOT NULL,
                veh_model TEXT DEFAULT '',
                platform TEXT DEFAULT '',
                sop TEXT DEFAULT '',
                eop TEXT DEFAULT '',
                owner TEXT DEFAULT ''
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_project_stage ON md_project (stage)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_project_oem ON md_project (oem_code, plant_code)")

    def create(self, project_no: str, project_name: str, stage: str, oem_code: str, plant_code: str,
               veh_model: str = None, platform: str = None, sop: str = None, eop: str = None, owner: str = None):
        project_no = self._clean(project_no)
        if not project_no:
            raise FdeError("项目号必填，不能为空")
        if self._exists(project_no):
            raise FdeError(f"项目 {project_no} 已存在")
        project_name = self._clean(project_name)
        if not project_name:
            raise FdeError("项目名称必填，不能为空")
        stage = self._clean(stage)
        if stage not in self.VALID_STAGES:
            raise FdeError(f"项目阶段只能为 {'/'.join(self.VALID_STAGES)}")
        oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code)
        if not oem_code or not plant_code:
            raise FdeError("客户编码和工厂编码必填")
        try:
            self.fde.call("md_customer", "get", oem_code=oem_code, plant_code=plant_code)
        except FdeError:
            raise FdeError(f"客户 {oem_code}/{plant_code} 不存在") from None

        self.db.execute(
            "INSERT INTO md_project (project_no, project_name, stage, oem_code, plant_code, veh_model, platform, sop, eop, owner) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (project_no, project_name, stage, oem_code, plant_code, self._clean(veh_model), self._clean(platform), self._clean(sop), self._clean(eop), self._clean(owner)),
        )
        return self.get(project_no)

    def get(self, project_no: str):
        project_no = self._clean(project_no)
        if not project_no:
            raise FdeError("项目号必填")
        row = self._row(project_no)
        if row is None:
            raise FdeError(f"项目 {project_no} 不存在")
        return dict(row)

    def list(self, project_no: str = None, stage: str = None, oem_code: str = None, plant_code: str = None, page: int = None, page_size: int = None):
        project_no = self._clean(project_no)
        stage = self._clean(stage)
        oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code)
        sql = "SELECT project_no, project_name, stage, oem_code, plant_code, veh_model, platform, sop, eop, owner FROM md_project"
        clauses, params = [], []
        if project_no:
            clauses.append("project_no LIKE '%' || ? || '%'")
            params.append(project_no)
        if stage:
            if stage not in self.VALID_STAGES:
                raise FdeError("项目阶段筛选不合法")
            clauses.append("stage = ?")
            params.append(stage)
        if oem_code:
            clauses.append("oem_code LIKE '%' || ? || '%'")
            params.append(oem_code)
        if plant_code:
            clauses.append("plant_code LIKE '%' || ? || '%'")
            params.append(plant_code)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY project_no"
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
        """取进行中项目——活跃行集定义来源，供快照 opening 用"""
        rows = self.db.execute(
            "SELECT project_no, project_name, stage, oem_code, plant_code, veh_model, platform, sop, eop, owner FROM md_project WHERE stage = '进行中' ORDER BY project_no"
        ).fetchall()
        return [dict(r) for r in rows]

    def update(self, project_no: str, project_name: str = None, stage: str = None,
               veh_model: str = None, platform: str = None, sop: str = None, eop: str = None, owner: str = None):
        project_no = self._clean(project_no)
        if not project_no:
            raise FdeError("项目号必填")
        if not self._exists(project_no):
            raise FdeError(f"项目 {project_no} 不存在")
        updates, params = [], []
        if project_name is not None:
            v = self._clean(project_name)
            if not v:
                raise FdeError("项目名称不能为空")
            updates.append("project_name = ?")
            params.append(v)
        if stage is not None:
            v = self._clean(stage)
            if v not in self.VALID_STAGES:
                raise FdeError(f"项目阶段只能为 {'/'.join(self.VALID_STAGES)}")
            updates.append("stage = ?")
            params.append(v)
        for col, val in [("veh_model", veh_model), ("platform", platform), ("sop", sop), ("eop", eop), ("owner", owner)]:
            if val is not None:
                updates.append(f"{col} = ?")
                params.append(self._clean(val))
        if updates:
            params.append(project_no)
            self.db.execute(f"UPDATE md_project SET {', '.join(updates)} WHERE project_no = ?", tuple(params))
        return self.get(project_no)

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

    def _exists(self, project_no):
        return self.db.execute("SELECT 1 FROM md_project WHERE project_no = ?", (project_no,)).fetchone() is not None

    def _row(self, project_no):
        return self.db.execute(
            "SELECT project_no, project_name, stage, oem_code, plant_code, veh_model, platform, sop, eop, owner FROM md_project WHERE project_no = ?",
            (project_no,),
        ).fetchone()
