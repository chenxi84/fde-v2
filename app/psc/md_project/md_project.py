from fde import FdeError
import re
from datetime import datetime


class MdProject:
    """项目台账聚合根。管理项目生命周期信息（阶段/SOP/EOP），为阶跃检测、爬坡期识别与清尾管理提供项目阶段基准。"""

    VALID_STAGES = ("进行中", "SOP", "EOP")

    _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    _STAGE_NEXT = {
        "进行中": "SOP",
        "SOP": "EOP",
        "EOP": None,
    }

    def create(self, project_no: str, project_name: str, owner: str, stage: str = None,
               sop_date: str = None, eop_date: str = None, veh_model: str = None, share=None):
        """新建项目台账。project_no 全局唯一，stage 默认「进行中」。"""
        project_no = self._clean(project_no)
        if not project_no:
            raise FdeError("项目号不能为空")
        if self._exists(project_no):
            raise FdeError("该项目号已存在")

        project_name = self._clean(project_name)
        if not project_name:
            raise FdeError("项目名称不能为空")

        owner = self._clean(owner)
        if not owner:
            raise FdeError("责任销售不能为空")

        stage = self._clean(stage) or "进行中"
        self._validate_stage(stage)
        self._validate_transition(None, stage)

        sop_date = self._validate_date(sop_date, "SOP")
        eop_date = self._validate_date(eop_date, "EOP")
        self._validate_date_order(sop_date, eop_date)

        veh_model = self._clean(veh_model)
        share = self._validate_share(share)

        self.db.execute(
            "INSERT INTO md_project (project_no, project_name, stage, sop_date, eop_date, owner, veh_model, share) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (project_no, project_name, stage, sop_date, eop_date, owner, veh_model, share),
        )
        return self.get(project_no)

    def get(self, project_no: str):
        """按项目号查询项目台账详情。"""
        project_no = self._clean(project_no)
        if not project_no:
            raise FdeError("项目号不能为空")
        row = self._row(project_no)
        if row is None:
            raise FdeError("项目记录不存在")
        return dict(row)

    def list(self, project_no: str = None, project_name: str = None, stage: str = None, page: int = None, size: int = None):
        """按项目号（模糊）、项目名称（模糊）、阶段（精确）筛选项目台账，支持分页。"""
        project_no = self._clean(project_no)
        project_name = self._clean(project_name)
        stage = self._clean(stage)
        if stage and stage not in self.VALID_STAGES:
            raise FdeError("阶段仅支持进行中/SOP/EOP")

        sql = "SELECT project_no, project_name, stage, sop_date, eop_date, owner, veh_model, share FROM md_project"
        clauses, params = [], []
        if project_no:
            clauses.append("project_no LIKE ?")
            params.append(f"%{project_no}%")
        if project_name:
            clauses.append("project_name LIKE ?")
            params.append(f"%{project_name}%")
        if stage:
            clauses.append("stage = ?")
            params.append(stage)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY project_no"

        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [dict(r) for r in rows]
        total = len(items)

        if page is None and size is None:
            return {"items": items, "total": total}

        page_no = self._to_int(page, 1)
        size_n = self._to_int(size, 20)
        if page_no < 1:
            raise FdeError("页码必须大于等于1")
        if size_n < 1:
            raise FdeError("每页条数必须大于等于1")
        start = (page_no - 1) * size_n
        return {"items": items[start:start + size_n], "total": total}

    def update(self, project_no: str, project_name: str = None, stage: str = None, sop_date: str = None,
               eop_date: str = None, owner: str = None, veh_model: str = None, share=None):
        """更新项目台账（project_no 为主键不可修改）。stage 遵循单向流转，禁止跳级/回退。"""
        project_no = self._clean(project_no)
        if not project_no:
            raise FdeError("项目号不能为空")
        current = self._row(project_no)
        if current is None:
            raise FdeError("项目记录不存在")
        current = dict(current)

        new_name = current["project_name"]
        new_stage = current["stage"]
        new_sop = current["sop_date"] or ""
        new_eop = current["eop_date"] or ""
        new_owner = current["owner"]
        new_veh = current.get("veh_model") or ""
        new_share = current.get("share")

        if project_name is not None:
            new_name = self._clean(project_name)
            if not new_name:
                raise FdeError("项目名称不能为空")
        if owner is not None:
            new_owner = self._clean(owner)
            if not new_owner:
                raise FdeError("责任销售不能为空")
        if stage is not None:
            new_stage = self._clean(stage)
            self._validate_stage(new_stage)
            self._validate_transition(current["stage"], new_stage)
        if sop_date is not None:
            new_sop = self._validate_date(sop_date, "SOP")
        if eop_date is not None:
            new_eop = self._validate_date(eop_date, "EOP")
        if veh_model is not None:
            new_veh = self._clean(veh_model)
        if share is not None:
            new_share = self._validate_share(share)

        self._validate_date_order(new_sop, new_eop)

        if new_stage == "SOP" and not new_sop:
            raise FdeError("推进到 SOP 阶段须填写 SOP 时间")
        if new_stage == "EOP" and not new_eop:
            raise FdeError("推进到 EOP 阶段须填写 EOP 时间")

        self.db.execute(
            "UPDATE md_project SET project_name = ?, stage = ?, sop_date = ?, eop_date = ?, owner = ?, "
            "veh_model = ?, share = ? WHERE project_no = ?",
            (new_name, new_stage, new_sop, new_eop, new_owner, new_veh, new_share, project_no),
        )
        return self.get(project_no)

    def import_batch(self, rows):
        """批量导入/更新项目台账（upsert）。已存在主键行更新，新行新增；逐行校验，失败行记录错误明细。"""
        if not rows:
            raise FdeError("导入数据不能为空")
        total = len(rows)
        created, updated, errors = 0, 0, []
        for i, r in enumerate(rows):
            row_no = i + 1
            try:
                if not isinstance(r, dict):
                    raise FdeError("行数据须为对象")
                project_no = self._clean(r.get("project_no"))
                if not project_no:
                    raise FdeError("项目号不能为空")
                project_name = self._clean(r.get("project_name"))
                owner = self._clean(r.get("owner"))
                stage = self._clean(r.get("stage"))
                sop_date = self._clean(r.get("sop_date"))
                eop_date = self._clean(r.get("eop_date"))
                veh_model = self._clean(r.get("veh_model"))
                share = r.get("share")
                if self._exists(project_no):
                    self.update(
                        project_no,
                        project_name=project_name,
                        owner=owner,
                        stage=stage or None,
                        sop_date=sop_date or None,
                        eop_date=eop_date or None,
                        veh_model=veh_model or None,
                        share=share,
                    )
                    updated += 1
                else:
                    self.create(
                        project_no,
                        project_name=project_name,
                        owner=owner,
                        stage=stage or None,
                        sop_date=sop_date or None,
                        eop_date=eop_date or None,
                        veh_model=veh_model or None,
                        share=share,
                    )
                    created += 1
            except FdeError as e:
                errors.append({"row": row_no, "message": str(e)})
        return {
            "total": total,
            "success": created + updated,
            "fail": len(errors),
            "created": created,
            "updated": updated,
            "errors": errors,
        }

    # ---- 内部辅助（_ 前缀，不对外暴露）----

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
        return self.db.execute(
            "SELECT 1 FROM md_project WHERE project_no = ?", (project_no,)
        ).fetchone() is not None

    def _row(self, project_no):
        return self.db.execute(
            "SELECT project_no, project_name, stage, sop_date, eop_date, owner, veh_model, share "
            "FROM md_project WHERE project_no = ?",
            (project_no,),
        ).fetchone()

    def _validate_stage(self, stage):
        if stage not in self.VALID_STAGES:
            raise FdeError("阶段仅支持进行中/SOP/EOP")

    def _validate_transition(self, from_stage, to_stage):
        if from_stage is None:
            if to_stage != "进行中":
                raise FdeError("阶段仅可单向推进（进行中→SOP→EOP）")
            return
        if from_stage == to_stage:
            return
        if self._STAGE_NEXT.get(from_stage) != to_stage:
            raise FdeError("阶段仅可单向推进（进行中→SOP→EOP）")

    def _validate_share(self, value):
        """供应份额：空 → None；否则 0~1 的小数（如 0.3 表示 30%）。"""
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise FdeError("份额须为 0~1 的数字（如 0.3）")
        if f < 0 or f > 1:
            raise FdeError("份额须在 0~1 之间")
        return f

    def _validate_date(self, value, label):
        value = self._clean(value)
        if not value:
            return ""
        if not self._DATE_RE.match(value):
            raise FdeError(f"{label} 时间格式须为 YYYY-MM-DD")
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise FdeError(f"{label} 时间格式须为 YYYY-MM-DD")
        return value

    def _validate_date_order(self, sop_date, eop_date):
        if sop_date and eop_date and eop_date <= sop_date:
            raise FdeError("EOP 时间须晚于 SOP 时间")
