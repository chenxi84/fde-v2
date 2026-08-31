from fde import FdeError


class MdProjectPart:
    """项目零件映射聚合根：定义「项目 × 零件 × 车型」的用量/份额量纲关系。"""

    def create(self, project_no: str, material_no: str, usage):
        """新建项目×物料映射，校验项目/物料引用存在与单车用量范围。车型/份额由项目关联，不入库。"""
        data, err = self._validate_fields({
            "project_no": project_no,
            "material_no": material_no,
            "usage": usage,
        })
        if err:
            raise FdeError(err["message"])

        if self._row(data["project_no"], data["material_no"]) is not None:
            raise FdeError("该项目-物料映射已存在")

        self._check_project(data["project_no"])
        self._check_material(data["material_no"])

        self.db.execute(
            "INSERT INTO md_project_part (project_no, material_no, usage) VALUES (?, ?, ?)",
            (data["project_no"], data["material_no"], data["usage"]),
        )
        return {
            "project_no": data["project_no"],
            "material_no": data["material_no"],
            "usage": data["usage"],
        }

    def get(self, project_no: str, material_no: str):
        """按复合主键查看单条映射。"""
        project_no = self._clean(project_no)
        if not project_no:
            raise FdeError("项目号不能为空")
        material_no = self._clean(material_no)
        if not material_no:
            raise FdeError("物料号不能为空")

        row = self._row(project_no, material_no)
        if row is None:
            raise FdeError("映射记录不存在")

        return self._to_dict(row)

    def list(self, project_no: str = None, material_no: str = None,
             page: int = None, size: int = None):
        """按项目号/物料号模糊筛选的分页列表。"""
        project_no = self._clean(project_no)
        material_no = self._clean(material_no)

        sql = "SELECT project_no, material_no, usage FROM md_project_part"
        clauses = []
        params = []

        if project_no:
            clauses.append("project_no LIKE '%' || ? || '%'")
            params.append(project_no)
        if material_no:
            clauses.append("material_no LIKE '%' || ? || '%'")
            params.append(material_no)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY project_no, material_no"
        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [self._to_dict(row) for row in rows]
        total = len(items)

        if page is None and size is None:
            return {"items": items, "total": total}

        page_no = self._to_int(page, 1)
        page_size = self._to_int(size, 20)
        if page_no < 1:
            page_no = 1
        if page_size < 1:
            page_size = 20

        start = (page_no - 1) * page_size
        return {"items": items[start:start + page_size], "total": total}

    def update(self, project_no: str, material_no: str, usage=None):
        """更新映射的单车用量；project_no+material_no 不可修改。车型/份额由项目关联，不入库。"""
        project_no = self._clean(project_no)
        if not project_no:
            raise FdeError("项目号不能为空")
        material_no = self._clean(material_no)
        if not material_no:
            raise FdeError("物料号不能为空")

        if self._row(project_no, material_no) is None:
            raise FdeError("映射记录不存在")

        self._check_project(project_no)
        self._check_material(material_no)

        updates = {}
        if usage is not None:
            usage, err = self._usage_int(usage)
            if err:
                raise FdeError(err)
            updates["usage"] = usage

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            params = list(updates.values()) + [project_no, material_no]
            self.db.execute(
                f"UPDATE md_project_part SET {set_clause} WHERE project_no = ? AND material_no = ?",
                tuple(params),
            )

        return self.get(project_no, material_no)

    def list_by_material(self, material_no: str):
        """按物料号查询其全部项目映射（不分页，供量纲折算/预测分摊跨应用调用）。"""
        material_no = self._clean(material_no)
        if not material_no:
            raise FdeError("物料号不能为空")

        rows = self.db.execute(
            "SELECT project_no, material_no, usage FROM md_project_part"
            " WHERE material_no = ? ORDER BY project_no",
            (material_no,),
        ).fetchall()
        return [self._to_dict(row) for row in rows]

    def import_batch(self, rows):
        """批量导入/更新（upsert）：逐行校验，失败行返回错误明细，不阻断其余行。"""
        if not isinstance(rows, (list, tuple)):
            raise FdeError("导入数据须为列表")

        errors = []
        success = 0
        total = len(rows)

        for i, raw in enumerate(rows, start=1):
            if not isinstance(raw, dict):
                errors.append({"row": i, "field": "", "message": "行数据格式非法"})
                continue
            data, err = self._validate_fields(raw)
            if err:
                errors.append({"row": i, **err})
                continue
            try:
                self._check_project(data["project_no"])
            except FdeError:
                errors.append({"row": i, "field": "project_no", "message": "项目不存在"})
                continue
            try:
                self._check_material(data["material_no"])
            except FdeError:
                errors.append({"row": i, "field": "material_no", "message": "物料不存在"})
                continue
            self._upsert(data)
            success += 1

        return {
            "total": total,
            "success": success,
            "fail": len(errors),
            "errors": errors,
        }

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _validate_fields(self, raw):
        """校验并清洗必填字段与量纲范围（不含跨应用引用校验）。返回 (data, error)。"""
        data = {}

        project_no = self._clean(raw.get("project_no"))
        if not project_no:
            return None, {"field": "project_no", "message": "项目号不能为空"}
        data["project_no"] = project_no

        material_no = self._clean(raw.get("material_no"))
        if not material_no:
            return None, {"field": "material_no", "message": "物料号不能为空"}
        data["material_no"] = material_no

        usage, err = self._usage_int(raw.get("usage"))
        if err:
            return None, {"field": "usage", "message": err}
        data["usage"] = usage

        return data, None

    def _check_project(self, project_no):
        try:
            self.fde.call("md_project", "get", project_no=project_no)
        except FdeError:
            raise FdeError("项目不存在")

    def _check_material(self, material_no):
        try:
            self.fde.call("md_material", "get", material_no=material_no)
        except FdeError:
            raise FdeError("物料不存在")

    def _upsert(self, data):
        existing = self._row(data["project_no"], data["material_no"])
        if existing is None:
            self.db.execute(
                "INSERT INTO md_project_part (project_no, material_no, usage) VALUES (?, ?, ?)",
                (data["project_no"], data["material_no"], data["usage"]),
            )
        else:
            self.db.execute(
                "UPDATE md_project_part SET usage = ? WHERE project_no = ? AND material_no = ?",
                (data["usage"], data["project_no"], data["material_no"]),
            )

    def _row(self, project_no, material_no):
        return self.db.execute(
            "SELECT project_no, material_no, usage FROM md_project_part"
            " WHERE project_no = ? AND material_no = ?",
            (project_no, material_no),
        ).fetchone()

    def _to_dict(self, row):
        return {
            "project_no": row["project_no"],
            "material_no": row["material_no"],
            "usage": row["usage"],
        }

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _num(self, value, field):
        """解析数值，返回 (数值, 错误信息)。"""
        if value is None:
            return None, f"{field}不能为空"
        if isinstance(value, bool):
            return None, f"{field}格式非法"
        if isinstance(value, (int, float)):
            return value, None
        text = str(value).strip()
        if not text:
            return None, f"{field}不能为空"
        try:
            return float(text), None
        except (TypeError, ValueError):
            return None, f"{field}格式非法"

    def _usage_int(self, value, field="单车用量"):
        """单车用量必须为正整数，返回 (int, 错误)。"""
        num, err = self._num(value, field)
        if err:
            return None, err
        if float(num) != int(float(num)):
            return None, f"{field}须为整数"
        if int(num) <= 0:
            return None, f"{field}须大于0"
        return int(num), None

    def _to_int(self, value, default):
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise FdeError("分页参数非法")
