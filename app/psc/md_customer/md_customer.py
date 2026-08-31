from __future__ import annotations

from fde import FdeError


class MdCustomer:
    """客户主数据聚合根。公共方法即对外服务，如 psc__md_customer__create。"""

    # 结算模式字典（BR-05，2026-08 业务确认）：空值允许（未设置），非空必须命中字典
    SETTLE_MODES = ("现售", "寄售")

    # 统一社会信用代码（GB 32100-2015）：31 位字符集（不含 I/O/Z/S/V）+ 17 位权重
    _USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
    _USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)

    def create(self, customer_no: str, customer_name: str, settle_mode: str = None,
               line_stock_days: int = None, transfer_lead_days: int = None,
               credit_code: str = None):
        """新建客户主数据，customer_no 全局唯一。"""
        customer_no = self._clean(customer_no)
        if not customer_no:
            raise FdeError("客户编码不能为空")
        if len(customer_no) > 50:
            raise FdeError("客户编码不能超过50字符")

        if self._exists(customer_no):
            raise FdeError("该客户编码已存在")

        customer_name = self._clean(customer_name)
        if not customer_name:
            raise FdeError("客户名称不能为空")
        if len(customer_name) > 100:
            raise FdeError("客户名称不能超过100字符")

        settle_mode = self._settle_mode(settle_mode)
        credit_code = self._credit_code(credit_code)
        line_stock_days = self._to_int(line_stock_days, 0, "线边库存天数")
        transfer_lead_days = self._to_int(transfer_lead_days, None, "调拨提前期")

        self.db.execute(
            "INSERT INTO md_customer "
            "(customer_no, customer_name, credit_code, settle_mode, line_stock_days, transfer_lead_days) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (customer_no, customer_name, credit_code, settle_mode, line_stock_days, transfer_lead_days),
        )
        return {
            "customer_no": customer_no,
            "customer_name": customer_name,
            "credit_code": credit_code,
            "settle_mode": settle_mode,
            "line_stock_days": line_stock_days,
            "transfer_lead_days": transfer_lead_days,
        }

    def get(self, customer_no: str):
        """按客户编码查看单条客户主数据详情。"""
        customer_no = self._clean(customer_no)
        if not customer_no:
            raise FdeError("客户编码不能为空")

        row = self._row(customer_no)
        if row is None:
            raise FdeError("客户记录不存在")

        return self._to_dict(row)

    def list(self, customer_no: str = None, customer_name: str = None,
             credit_code: str = None, page: int = None, size: int = None):
        """按客户编码/名称/统一社会信用代码模糊筛选的分页列表，按 customer_no 升序。"""
        customer_no = self._clean(customer_no)
        customer_name = self._clean(customer_name)
        credit_code = self._clean(credit_code).upper()

        sql = ("SELECT customer_no, customer_name, credit_code, settle_mode, line_stock_days, "
               "transfer_lead_days FROM md_customer")
        clauses = []
        params = []

        if customer_no:
            clauses.append("customer_no LIKE '%' || ? || '%'")
            params.append(customer_no)
        if customer_name:
            clauses.append("customer_name LIKE '%' || ? || '%'")
            params.append(customer_name)
        if credit_code:
            clauses.append("credit_code LIKE '%' || ? || '%'")
            params.append(credit_code)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY customer_no"

        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [self._to_dict(r) for r in rows]
        total = len(items)

        if page is None and size is None:
            return {"items": items, "total": total}

        page_no = self._page_int(page, 1)
        page_size = self._page_int(size, 20)
        start = (page_no - 1) * page_size
        return {"items": items[start:start + page_size], "total": total}

    def update(self, customer_no: str, customer_name: str = None, settle_mode: str = None,
               line_stock_days: int = None, transfer_lead_days: int = None,
               credit_code: str = None):
        """更新客户主数据（customer_no 主键不可改）。"""
        customer_no = self._clean(customer_no)
        if not customer_no:
            raise FdeError("客户编码不能为空")

        row = self._row(customer_no)
        if row is None:
            raise FdeError("客户记录不存在")

        fields = []
        params = []

        if customer_name is not None:
            customer_name = self._clean(customer_name)
            if not customer_name:
                raise FdeError("客户名称不能为空")
            if len(customer_name) > 100:
                raise FdeError("客户名称不能超过100字符")
            fields.append("customer_name = ?")
            params.append(customer_name)

        if settle_mode is not None:
            settle_mode = self._settle_mode(settle_mode)
            fields.append("settle_mode = ?")
            params.append(settle_mode)

        if credit_code is not None:
            credit_code = self._credit_code(credit_code)
            fields.append("credit_code = ?")
            params.append(credit_code)

        if line_stock_days is not None:
            line_stock_days = self._to_int(line_stock_days, 0, "线边库存天数")
            fields.append("line_stock_days = ?")
            params.append(line_stock_days)

        if transfer_lead_days is not None:
            transfer_lead_days = self._to_int(transfer_lead_days, None, "调拨提前期")
            fields.append("transfer_lead_days = ?")
            params.append(transfer_lead_days)

        if fields:
            params.append(customer_no)
            self.db.execute(
                f"UPDATE md_customer SET {', '.join(fields)} WHERE customer_no = ?",
                tuple(params),
            )

        return self._to_dict(self._row(customer_no))

    def import_batch(self, rows: list):
        """批量导入/更新（upsert）：已存在 customer_no 更新，不存在则新增。"""
        if not isinstance(rows, list):
            raise FdeError("导入数据必须为列表")

        total = len(rows)
        success = 0
        errors = []

        for i, row in enumerate(rows):
            row_no = i + 1
            try:
                if not isinstance(row, dict):
                    errors.append({"row": row_no, "field": "", "message": "行数据格式非法"})
                    continue

                customer_no = self._clean(row.get("customer_no"))
                if not customer_no:
                    errors.append({"row": row_no, "field": "customer_no", "message": "客户编码不能为空"})
                    continue
                if len(customer_no) > 50:
                    errors.append({"row": row_no, "field": "customer_no", "message": "客户编码不能超过50字符"})
                    continue

                customer_name = self._clean(row.get("customer_name"))
                if not customer_name:
                    errors.append({"row": row_no, "field": "customer_name", "message": "客户名称不能为空"})
                    continue
                if len(customer_name) > 100:
                    errors.append({"row": row_no, "field": "customer_name", "message": "客户名称不能超过100字符"})
                    continue

                try:
                    settle_mode = self._settle_mode(row.get("settle_mode"))
                except FdeError as e:
                    errors.append({"row": row_no, "field": "settle_mode", "message": str(e)})
                    continue

                try:
                    credit_code = self._credit_code(row.get("credit_code"))
                except FdeError as e:
                    errors.append({"row": row_no, "field": "credit_code", "message": str(e)})
                    continue

                try:
                    line_stock_days = self._to_int(row.get("line_stock_days"), 0, "线边库存天数")
                except FdeError as e:
                    errors.append({"row": row_no, "field": "line_stock_days", "message": str(e)})
                    continue

                try:
                    transfer_lead_days = self._to_int(row.get("transfer_lead_days"), None, "调拨提前期")
                except FdeError as e:
                    errors.append({"row": row_no, "field": "transfer_lead_days", "message": str(e)})
                    continue

                if self._exists(customer_no):
                    self.db.execute(
                        "UPDATE md_customer SET customer_name = ?, credit_code = ?, settle_mode = ?, "
                        "line_stock_days = ?, transfer_lead_days = ? WHERE customer_no = ?",
                        (customer_name, credit_code, settle_mode, line_stock_days, transfer_lead_days, customer_no),
                    )
                else:
                    self.db.execute(
                        "INSERT INTO md_customer "
                        "(customer_no, customer_name, credit_code, settle_mode, line_stock_days, transfer_lead_days) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (customer_no, customer_name, credit_code, settle_mode, line_stock_days, transfer_lead_days),
                    )
                success += 1
            except FdeError as e:
                errors.append({"row": row_no, "field": "", "message": str(e)})

        return {"total": total, "success": success, "fail": len(errors), "errors": errors}

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _settle_mode(self, value):
        """结算模式字典校验：空值 → None（未设置）；非空必须为字典值（现售/寄售）。"""
        v = self._clean(value)
        if not v:
            return None
        if v not in self.SETTLE_MODES:
            raise FdeError("结算模式必须为字典值：现售 / 寄售")
        return v

    def _credit_code(self, value):
        """统一社会信用代码校验（GB 32100-2015）：空值 → None；非空须为 18 位合法字符集且校验位正确。"""
        v = self._clean(value).upper()
        if not v:
            return None
        if len(v) != 18:
            raise FdeError("统一社会信用代码必须为18位")
        if any(c not in self._USCC_CHARS for c in v):
            raise FdeError("统一社会信用代码含非法字符（仅数字与大写字母，不含 I/O/Z/S/V）")
        total = sum(self._USCC_CHARS.index(c) * w for c, w in zip(v[:17], self._USCC_WEIGHTS))
        if v[17] != self._USCC_CHARS[(31 - total % 31) % 31]:
            raise FdeError("统一社会信用代码校验位不正确")
        return v

    def _to_int(self, value, default, label):
        """转非负整数；None/空串取 default；非法或负数抛 FdeError。"""
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return default
        if isinstance(value, float):
            if not value.is_integer():
                raise FdeError(f"{label}必须为非负整数")
            n = int(value)
        else:
            try:
                n = int(value)
            except (TypeError, ValueError):
                raise FdeError(f"{label}必须为非负整数")
        if n < 0:
            raise FdeError(f"{label}必须为非负整数")
        return n

    def _page_int(self, value, default):
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        try:
            n = int(value)
        except (TypeError, ValueError):
            return default
        return n if n > 0 else default

    def _row(self, customer_no):
        return self.db.execute(
            "SELECT customer_no, customer_name, credit_code, settle_mode, line_stock_days, transfer_lead_days "
            "FROM md_customer WHERE customer_no = ?",
            (customer_no,),
        ).fetchone()

    def _exists(self, customer_no):
        return (
            self.db.execute(
                "SELECT 1 FROM md_customer WHERE customer_no = ?",
                (customer_no,),
            ).fetchone()
            is not None
        )

    def _to_dict(self, row):
        return {
            "customer_no": row["customer_no"],
            "customer_name": row["customer_name"],
            "credit_code": row["credit_code"],
            "settle_mode": row["settle_mode"],
            "line_stock_days": row["line_stock_days"],
            "transfer_lead_days": row["transfer_lead_days"],
        }
