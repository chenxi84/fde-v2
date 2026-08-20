from fde import FdeError


class MdCustomer:
    """客户主数据聚合根。"""

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_customer (
                customer_code TEXT NOT NULL PRIMARY KEY,
                customer_name TEXT NOT NULL,
                short_name TEXT NOT NULL,
                settlement_mode TEXT NOT NULL,
                predict_behavior_label TEXT NOT NULL
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS customer_plant (
                customer_code TEXT NOT NULL,
                plant_code TEXT NOT NULL,
                plant_name TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (customer_code, plant_code),
                FOREIGN KEY (customer_code) REFERENCES md_customer(customer_code)
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_customer_name ON md_customer (customer_name)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_customer_settlement ON md_customer (settlement_mode)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_customer_label ON md_customer (predict_behavior_label)")

    def create(self, customer_code, customer_name, short_name, settlement_mode, predict_behavior_label):
        customer_code = self._clean(customer_code)
        if not customer_code:
            raise FdeError("customer_code 必填，不能为空")

        if self._exists(customer_code):
            raise FdeError("客户编码已存在")

        customer_name = self._clean(customer_name)
        if not customer_name:
            raise FdeError("customer_name 必填，不能为空")

        short_name = self._clean(short_name)
        if not short_name:
            raise FdeError("short_name 必填，不能为空")

        settlement_mode = self._clean(settlement_mode)
        if not settlement_mode:
            raise FdeError("settlement_mode 必填，不能为空")

        predict_behavior_label = self._clean(predict_behavior_label)
        if not predict_behavior_label:
            raise FdeError("predict_behavior_label 必填，不能为空")

        self.db.execute(
            "INSERT INTO md_customer (customer_code, customer_name, short_name, settlement_mode, predict_behavior_label) VALUES (?, ?, ?, ?, ?)",
            (customer_code, customer_name, short_name, settlement_mode, predict_behavior_label),
        )

        return self.get(customer_code)

    def get(self, customer_code):
        customer_code = self._clean(customer_code)
        if not customer_code:
            raise FdeError("customer_code 必填，不能为空")

        row = self._row(customer_code)
        if row is None:
            raise FdeError("客户不存在")

        return self._to_dict(row)

    
    def get_plants(self, customer_code: str):
        """获取该客户的工厂列表。"""
        rows = self.db.execute(
            "SELECT plant_code, plant_name FROM customer_plant WHERE customer_code=? ORDER BY plant_code",
            (customer_code,)
        ).fetchall()
        return [dict(r) for r in rows]

    def add_plant(self, customer_code: str, plant_code: str, plant_name: str = ""):
        """为客户添加工厂。"""
        if not self._exists(customer_code):
            raise FdeError(f"客户 {customer_code} 不存在")
        self.db.execute(
            "INSERT OR REPLACE INTO customer_plant (customer_code, plant_code, plant_name) VALUES (?,?,?)",
            (customer_code, plant_code, plant_name)
        )
        return self.get_plants(customer_code)

    def remove_plant(self, customer_code: str, plant_code: str):
        """删除客户的工厂。"""
        self.db.execute(
            "DELETE FROM customer_plant WHERE customer_code=? AND plant_code=?",
            (customer_code, plant_code)
        )
        return self.get_plants(customer_code)

    def list(self, keyword=None, settlement_mode=None, page=None, page_size=None):
        keyword = self._clean(keyword)
        settlement_mode = self._clean(settlement_mode)

        sql = "SELECT customer_code, customer_name, short_name, settlement_mode, predict_behavior_label FROM md_customer"
        clauses = []
        params = []

        if keyword:
            clauses.append(
                "("
                "customer_code LIKE '%' || ? || '%' "
                "OR customer_name LIKE '%' || ? || '%' "
                "OR short_name LIKE '%' || ? || '%'"
                ")"
            )
            params.extend([keyword, keyword, keyword])

        if settlement_mode:
            clauses.append("settlement_mode = ?")
            params.append(settlement_mode)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY customer_code"
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

    def update(self, customer_code, customer_name=None, short_name=None, settlement_mode=None, predict_behavior_label=None):
        customer_code = self._clean(customer_code)
        if not customer_code:
            raise FdeError("customer_code 必填，不能为空")

        row = self._row(customer_code)
        if row is None:
            raise FdeError("客户不存在")

        sets = []
        params = []

        if customer_name is not None:
            v = self._clean(customer_name)
            if not v:
                raise FdeError("customer_name 不能为空")
            sets.append("customer_name = ?")
            params.append(v)

        if short_name is not None:
            v = self._clean(short_name)
            if not v:
                raise FdeError("short_name 不能为空")
            sets.append("short_name = ?")
            params.append(v)

        if settlement_mode is not None:
            v = self._clean(settlement_mode)
            if not v:
                raise FdeError("settlement_mode 不能为空")
            sets.append("settlement_mode = ?")
            params.append(v)

        if predict_behavior_label is not None:
            v = self._clean(predict_behavior_label)
            if not v:
                raise FdeError("predict_behavior_label 不能为空")
            sets.append("predict_behavior_label = ?")
            params.append(v)

        if not sets:
            return self.get(customer_code)

        params.append(customer_code)
        self.db.execute(
            "UPDATE md_customer SET " + ", ".join(sets) + " WHERE customer_code = ?",
            tuple(params),
        )

        return self.get(customer_code)

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

    def _exists(self, customer_code):
        return (
            self.db.execute(
                "SELECT 1 FROM md_customer WHERE customer_code = ?",
                (customer_code,),
            ).fetchone()
            is not None
        )

    def _row(self, customer_code):
        return self.db.execute(
            "SELECT customer_code, customer_name, short_name, settlement_mode, predict_behavior_label FROM md_customer WHERE customer_code = ?",
            (customer_code,),
        ).fetchone()

    def _to_dict(self, row):
        return {
            "customer_code": row["customer_code"],
            "customer_name": row["customer_name"],
            "short_name": row["short_name"],
            "settlement_mode": row["settlement_mode"],
            "predict_behavior_label": row["predict_behavior_label"],
        }
