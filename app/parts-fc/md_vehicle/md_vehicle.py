from fde import FdeError


class MdVehicle:
    """车型主数据聚合根。"""

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_vehicle (
                vehicle_code TEXT NOT NULL PRIMARY KEY,
                vehicle_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                segment TEXT NOT NULL,
                powertrain TEXT NOT NULL,
                price_range TEXT NOT NULL,
                oem_code TEXT NOT NULL
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_vehicle_name ON md_vehicle (vehicle_name)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_vehicle_platform ON md_vehicle (platform)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_vehicle_segment ON md_vehicle (segment)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_md_vehicle_oem ON md_vehicle (oem_code)")

    def create(self, vehicle_code, vehicle_name, platform, segment, powertrain, price_range, oem_code):
        vehicle_code = self._clean(vehicle_code)
        if not vehicle_code:
            raise FdeError("vehicle_code 必填，不能为空")

        if self._exists(vehicle_code):
            raise FdeError("车型编码已存在")

        vehicle_name = self._clean(vehicle_name)
        if not vehicle_name:
            raise FdeError("vehicle_name 必填，不能为空")

        platform = self._clean(platform)
        if not platform:
            raise FdeError("platform 必填，不能为空")

        segment = self._clean(segment)
        if not segment:
            raise FdeError("segment 必填，不能为空")

        powertrain = self._clean(powertrain)
        if not powertrain:
            raise FdeError("powertrain 必填，不能为空")

        price_range = self._clean(price_range)
        if not price_range:
            raise FdeError("price_range 必填，不能为空")

        oem_code = self._clean(oem_code)
        if not oem_code:
            raise FdeError("oem_code 必填，不能为空")

        self.db.execute(
            "INSERT INTO md_vehicle (vehicle_code, vehicle_name, platform, segment, powertrain, price_range, oem_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (vehicle_code, vehicle_name, platform, segment, powertrain, price_range, oem_code),
        )

        return self.get(vehicle_code)

    def get(self, vehicle_code):
        vehicle_code = self._clean(vehicle_code)
        if not vehicle_code:
            raise FdeError("vehicle_code 必填，不能为空")

        row = self._row(vehicle_code)
        if row is None:
            raise FdeError("车型不存在")

        return self._to_dict(row)

    def list(self, keyword=None, platform=None, segment=None, oem_code=None, page=None, page_size=None):
        keyword = self._clean(keyword)
        platform = self._clean(platform)
        segment = self._clean(segment)
        oem_code = self._clean(oem_code)

        sql = "SELECT vehicle_code, vehicle_name, platform, segment, powertrain, price_range, oem_code FROM md_vehicle"
        clauses = []
        params = []

        if keyword:
            clauses.append(
                "("
                "vehicle_code LIKE '%' || ? || '%' "
                "OR vehicle_name LIKE '%' || ? || '%'"
                ")"
            )
            params.extend([keyword, keyword])

        if platform:
            clauses.append("platform = ?")
            params.append(platform)

        if segment:
            clauses.append("segment = ?")
            params.append(segment)

        if oem_code:
            clauses.append("oem_code = ?")
            params.append(oem_code)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY vehicle_code"
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

    def update(self, vehicle_code, vehicle_name=None, platform=None, segment=None, powertrain=None, price_range=None, oem_code=None):
        vehicle_code = self._clean(vehicle_code)
        if not vehicle_code:
            raise FdeError("vehicle_code 必填，不能为空")

        row = self._row(vehicle_code)
        if row is None:
            raise FdeError("车型不存在")

        sets = []
        params = []

        if vehicle_name is not None:
            v = self._clean(vehicle_name)
            if not v:
                raise FdeError("vehicle_name 不能为空")
            sets.append("vehicle_name = ?")
            params.append(v)

        if platform is not None:
            v = self._clean(platform)
            if not v:
                raise FdeError("platform 不能为空")
            sets.append("platform = ?")
            params.append(v)

        if segment is not None:
            v = self._clean(segment)
            if not v:
                raise FdeError("segment 不能为空")
            sets.append("segment = ?")
            params.append(v)

        if powertrain is not None:
            v = self._clean(powertrain)
            if not v:
                raise FdeError("powertrain 不能为空")
            sets.append("powertrain = ?")
            params.append(v)

        if price_range is not None:
            v = self._clean(price_range)
            if not v:
                raise FdeError("price_range 不能为空")
            sets.append("price_range = ?")
            params.append(v)

        if oem_code is not None:
            v = self._clean(oem_code)
            if not v:
                raise FdeError("oem_code 不能为空")
            sets.append("oem_code = ?")
            params.append(v)

        if not sets:
            return self.get(vehicle_code)

        params.append(vehicle_code)
        self.db.execute(
            "UPDATE md_vehicle SET " + ", ".join(sets) + " WHERE vehicle_code = ?",
            tuple(params),
        )

        return self.get(vehicle_code)

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

    def _exists(self, vehicle_code):
        return (
            self.db.execute(
                "SELECT 1 FROM md_vehicle WHERE vehicle_code = ?",
                (vehicle_code,),
            ).fetchone()
            is not None
        )

    def _row(self, vehicle_code):
        return self.db.execute(
            "SELECT vehicle_code, vehicle_name, platform, segment, powertrain, price_range, oem_code FROM md_vehicle WHERE vehicle_code = ?",
            (vehicle_code,),
        ).fetchone()

    def _to_dict(self, row):
        return {
            "vehicle_code": row["vehicle_code"],
            "vehicle_name": row["vehicle_name"],
            "platform": row["platform"],
            "segment": row["segment"],
            "powertrain": row["powertrain"],
            "price_range": row["price_range"],
            "oem_code": row["oem_code"],
        }
