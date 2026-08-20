from fde import FdeError


class MdMaterial:
    """物料主数据聚合根。管理零件号/名称/单位基础信息。"""

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_material (
                part_no TEXT NOT NULL PRIMARY KEY,
                part_name TEXT NOT NULL,
                uom TEXT NOT NULL DEFAULT '件',
                mat_type TEXT DEFAULT '成品'
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_material_part_name ON md_material (part_name)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_material_mat_type ON md_material (mat_type)")

    def create(self, part_no: str, part_name: str, uom: str = None, mat_type: str = None):
        part_no = self._clean(part_no)
        if not part_no:
            raise FdeError("零件号必填，不能为空")
        if self._exists(part_no):
            raise FdeError(f"物料 {part_no} 已存在")
        part_name = self._clean(part_name)
        if not part_name:
            raise FdeError("零件名称必填，不能为空")
        uom = self._clean(uom) if uom else "件"
        mat_type = self._clean(mat_type) if mat_type else "成品"

        self.db.execute(
            "INSERT INTO md_material (part_no, part_name, uom, mat_type) VALUES (?, ?, ?, ?)",
            (part_no, part_name, uom, mat_type),
        )
        return {"part_no": part_no, "part_name": part_name, "uom": uom, "mat_type": mat_type}

    def get(self, part_no: str):
        part_no = self._clean(part_no)
        if not part_no:
            raise FdeError("零件号必填，不能为空")
        row = self._row(part_no)
        if row is None:
            raise FdeError(f"物料 {part_no} 不存在")
        return dict(row)

    def list(self, part_no: str = None, part_name: str = None, mat_type: str = None, page: int = None, page_size: int = None):
        part_no = self._clean(part_no)
        part_name = self._clean(part_name)
        mat_type = self._clean(mat_type)
        sql = "SELECT part_no, part_name, uom, mat_type FROM md_material"
        clauses, params = [], []
        if part_no:
            clauses.append("part_no LIKE '%' || ? || '%'")
            params.append(part_no)
        if part_name:
            clauses.append("part_name LIKE '%' || ? || '%'")
            params.append(part_name)
        if mat_type:
            clauses.append("mat_type = ?")
            params.append(mat_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY part_no"
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

    def update(self, part_no: str, part_name: str = None, uom: str = None, mat_type: str = None):
        part_no = self._clean(part_no)
        if not part_no:
            raise FdeError("零件号必填")
        row = self._row(part_no)
        if row is None:
            raise FdeError(f"物料 {part_no} 不存在")
        updates, params = [], []
        if part_name is not None:
            v = self._clean(part_name)
            if not v:
                raise FdeError("零件名称不能为空")
            updates.append("part_name = ?")
            params.append(v)
        if uom is not None:
            updates.append("uom = ?")
            params.append(self._clean(uom))
        if mat_type is not None:
            updates.append("mat_type = ?")
            params.append(self._clean(mat_type))
        if updates:
            params.append(part_no)
            self.db.execute(f"UPDATE md_material SET {', '.join(updates)} WHERE part_no = ?", tuple(params))
        return dict(self._row(part_no))

    def import_batch(self, rows: list):
        if not rows:
            raise FdeError("导入数据不能为空")
        created, updated, errors = 0, 0, []
        for i, r in enumerate(rows):
            try:
                part_no = self._clean(r.get("part_no", ""))
                part_name = self._clean(r.get("part_name", ""))
                uom = r.get("uom")
                mat_type = r.get("mat_type")
                if not part_no:
                    errors.append(f"行{i+1}: 零件号必填")
                    continue
                if self._exists(part_no):
                    self.update(part_no, part_name=part_name, uom=uom, mat_type=mat_type)
                    updated += 1
                else:
                    self.create(part_no, part_name, uom=uom, mat_type=mat_type)
                    created += 1
            except FdeError as e:
                errors.append(f"行{i+1}: {e}")
        return {"created": created, "updated": updated, "errors": errors}

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
        return self.db.execute("SELECT 1 FROM md_material WHERE part_no = ?", (part_no,)).fetchone() is not None

    def _row(self, part_no):
        return self.db.execute(
            "SELECT part_no, part_name, uom, mat_type FROM md_material WHERE part_no = ?", (part_no,)
        ).fetchone()
