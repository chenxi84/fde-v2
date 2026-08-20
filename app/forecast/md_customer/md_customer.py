from fde import FdeError


class MdCustomer:
    """客户主数据聚合根。管理客户/OEM工厂基础信息与结算模式。"""

    VALID_SETTLE_MODES = ("寄售", "非寄售")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_customer (
                oem_code TEXT NOT NULL,
                plant_code TEXT NOT NULL,
                oem_name TEXT NOT NULL,
                plant_name TEXT NOT NULL,
                settle_mode TEXT NOT NULL CHECK (settle_mode IN ('寄售', '非寄售')),
                PRIMARY KEY (oem_code, plant_code)
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_customer_settle_mode ON md_customer (settle_mode)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_customer_oem_name ON md_customer (oem_name)")

    def create(self, oem_code: str, oem_name: str, plant_code: str, plant_name: str, settle_mode: str):
        oem_code = self._clean(oem_code)
        if not oem_code:
            raise FdeError("客户编码必填，不能为空")
        oem_name = self._clean(oem_name)
        if not oem_name:
            raise FdeError("客户名称必填，不能为空")
        plant_code = self._clean(plant_code)
        if not plant_code:
            raise FdeError("工厂编码必填，不能为空")
        plant_name = self._clean(plant_name)
        if not plant_name:
            raise FdeError("工厂名称必填，不能为空")
        settle_mode = self._clean(settle_mode)
        if settle_mode not in self.VALID_SETTLE_MODES:
            raise FdeError("结算模式只能为 寄售 或 非寄售")

        if self._exists(oem_code, plant_code):
            raise FdeError(f"客户 {oem_code}/{plant_code} 已存在")

        self.db.execute(
            "INSERT INTO md_customer (oem_code, plant_code, oem_name, plant_name, settle_mode) VALUES (?, ?, ?, ?, ?)",
            (oem_code, plant_code, oem_name, plant_name, settle_mode),
        )
        return {"oem_code": oem_code, "plant_code": plant_code, "oem_name": oem_name, "plant_name": plant_name, "settle_mode": settle_mode}

    def get(self, oem_code: str, plant_code: str):
        oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code)
        if not oem_code or not plant_code:
            raise FdeError("客户编码和工厂编码必填")
        row = self._row(oem_code, plant_code)
        if row is None:
            raise FdeError(f"客户 {oem_code}/{plant_code} 不存在")
        return dict(row)

    def list(self, oem_code: str = None, plant_code: str = None, settle_mode: str = None, page: int = None, page_size: int = None):
        oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code)
        settle_mode = self._clean(settle_mode)
        if settle_mode and settle_mode not in self.VALID_SETTLE_MODES:
            raise FdeError("结算模式筛选不合法")

        sql = "SELECT oem_code, plant_code, oem_name, plant_name, settle_mode FROM md_customer"
        clauses, params = [], []
        if oem_code:
            clauses.append("oem_code LIKE '%' || ? || '%'")
            params.append(oem_code)
        if plant_code:
            clauses.append("plant_code LIKE '%' || ? || '%'")
            params.append(plant_code)
        if settle_mode:
            clauses.append("settle_mode = ?")
            params.append(settle_mode)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY oem_code, plant_code"
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

    def update(self, oem_code: str, plant_code: str, oem_name: str = None, plant_name: str = None, settle_mode: str = None):
        oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code)
        if not oem_code or not plant_code:
            raise FdeError("客户编码和工厂编码必填")
        row = self._row(oem_code, plant_code)
        if row is None:
            raise FdeError(f"客户 {oem_code}/{plant_code} 不存在")

        updates, params = [], []
        if oem_name is not None:
            v = self._clean(oem_name)
            if not v:
                raise FdeError("客户名称不能为空")
            updates.append("oem_name = ?")
            params.append(v)
        if plant_name is not None:
            v = self._clean(plant_name)
            if not v:
                raise FdeError("工厂名称不能为空")
            updates.append("plant_name = ?")
            params.append(v)
        if settle_mode is not None:
            v = self._clean(settle_mode)
            if v not in self.VALID_SETTLE_MODES:
                raise FdeError("结算模式只能为 寄售 或 非寄售")
            updates.append("settle_mode = ?")
            params.append(v)
        if updates:
            params.extend([oem_code, plant_code])
            self.db.execute(f"UPDATE md_customer SET {', '.join(updates)} WHERE oem_code = ? AND plant_code = ?", tuple(params))
        return dict(self._row(oem_code, plant_code))

    def import_batch(self, rows: list):
        if not rows:
            raise FdeError("导入数据不能为空")
        created, updated, errors = 0, 0, []
        for i, r in enumerate(rows):
            try:
                oem_code = self._clean(r.get("oem_code", ""))
                plant_code = self._clean(r.get("plant_code", ""))
                oem_name = self._clean(r.get("oem_name", ""))
                plant_name = self._clean(r.get("plant_name", ""))
                settle_mode = self._clean(r.get("settle_mode", ""))
                if not oem_code or not plant_code:
                    errors.append(f"行{i+1}: 客户编码和工厂编码必填")
                    continue
                if self._exists(oem_code, plant_code):
                    self.update(oem_code, plant_code, oem_name=oem_name, plant_name=plant_name, settle_mode=settle_mode)
                    updated += 1
                else:
                    self.create(oem_code, oem_name, plant_code, plant_name, settle_mode)
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

    def _exists(self, oem_code, plant_code):
        return self.db.execute(
            "SELECT 1 FROM md_customer WHERE oem_code = ? AND plant_code = ?", (oem_code, plant_code)
        ).fetchone() is not None

    def _row(self, oem_code, plant_code):
        return self.db.execute(
            "SELECT oem_code, plant_code, oem_name, plant_name, settle_mode FROM md_customer WHERE oem_code = ? AND plant_code = ?",
            (oem_code, plant_code),
        ).fetchone()
