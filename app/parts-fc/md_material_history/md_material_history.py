from fde import FdeError


class MdMaterialHistory:
    """物料历史数据——零件×期间×OEM×工厂的实际调拨量。
    数据来源：D04 发布后自动回流 + 手工导入补录。
    """

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_material_history (
                part_no     TEXT NOT NULL,
                project_no  TEXT NOT NULL DEFAULT '',
                period      TEXT NOT NULL,
                actual_qty  REAL NOT NULL,
                oem_code    TEXT NOT NULL,
                plant_code  TEXT NOT NULL,
                source      TEXT NOT NULL DEFAULT '自动',
                PRIMARY KEY (part_no, project_no, period, oem_code, plant_code)
            )
        """)
        # 兼容旧表
        try:
            self.db.execute("ALTER TABLE md_material_history ADD COLUMN project_no TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_mh_part ON md_material_history (part_no)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_mh_period ON md_material_history (period)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_mh_oem ON md_material_history (oem_code)")

    def create(self, part_no, period, actual_qty, oem_code, plant_code, project_no="", source="手工"):
        part_no = self._clean(part_no)
        period = self._clean(period)
        oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code)
        project_no = self._clean(project_no)
        if not part_no or not period:
            raise FdeError("part_no 和 period 必填")

        import re
        if not re.match(r'^\d{4}-\d{2}$', period):
            raise FdeError("period 格式须为 YYYY-MM")

        try:
            actual_qty = float(actual_qty)
        except (TypeError, ValueError):
            raise FdeError("actual_qty 必须为数字")

        source = self._clean(source) or "手工"

        self.db.execute(
            "INSERT OR REPLACE INTO md_material_history (part_no, project_no, period, actual_qty, oem_code, plant_code, source) VALUES (?,?,?,?,?,?,?)",
            (part_no, project_no, period, actual_qty, oem_code, plant_code, source)
        )
        return self.get(part_no, period, oem_code, plant_code, project_no)

    def get(self, part_no, period, oem_code, plant_code, project_no=""):
        row = self._row(part_no, period, oem_code, plant_code, project_no)
        if not row:
            raise FdeError("记录不存在")
        return dict(row)

    def bulk_import(self, lines: list):
        """批量导入 lines=[{part_no, period, actual_qty, oem_code, plant_code, source}]"""
        count = 0
        for item in lines:
            try:
                self.create(
                    part_no=item.get("part_no", ""),
                    project_no=item.get("project_no", ""),
                    period=item.get("period", ""),
                    actual_qty=item.get("actual_qty", 0),
                    oem_code=item.get("oem_code", ""),
                    plant_code=item.get("plant_code", ""),
                    source=item.get("source", "手工"),
                )
                count += 1
            except FdeError:
                pass  # skip invalid lines
        return {"imported": count}

    def get_recent(self, part_no, oem_code, plant_code, project_no="", months=6):
        """取最近 N 个月的实际量，返回 [{period, actual_qty}, ...] 按期间升序。"""
        part_no = self._clean(part_no)
        oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code)
        project_no = self._clean(project_no)
        rows = self.db.execute(
            """SELECT period, actual_qty FROM md_material_history
               WHERE part_no=? AND oem_code=? AND plant_code=? AND (project_no=? OR project_no='')
               ORDER BY period DESC LIMIT ?""",
            (part_no, oem_code, plant_code, project_no, months)
        ).fetchall()
        return [{"period": r["period"], "actual_qty": r["actual_qty"]} for r in reversed(rows)]

    def _row(self, part_no, period, oem_code, plant_code, project_no=""):
        return self.db.execute(
            "SELECT * FROM md_material_history WHERE part_no=? AND period=? AND oem_code=? AND plant_code=? AND (project_no=? OR project_no='')",
            (part_no, period, oem_code, plant_code, project_no)
        ).fetchone()

    def list(self, keyword=None, oem_code=None, period=None, page=None, page_size=None):
        keyword = self._clean(keyword)
        oem_code = self._clean(oem_code)
        period = self._clean(period)

        sql = "SELECT * FROM md_material_history WHERE 1=1"
        params = []

        if keyword:
            sql += " AND (part_no LIKE '%' || ? || '%' OR oem_code LIKE '%' || ? || '%')"
            params.extend([keyword, keyword])
        if oem_code:
            sql += " AND oem_code=?"
            params.append(oem_code)
        if period:
            sql += " AND period=?"
            params.append(period)

        sql += " ORDER BY period DESC, part_no"
        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [dict(r) for r in rows]
        total = len(items)

        if page is not None and page_size is not None:
            page_no = self._to_int(page, 1)
            size_n = self._to_int(page_size, 50)
            if page_no < 1: page_no = 1
            if size_n < 1: size_n = 50
            start = (page_no - 1) * size_n
            items = items[start:start + size_n]

        return {"total": total, "items": items}

    def _clean(self, value):
        if value is None: return ""
        return str(value).strip()

    def _to_int(self, value, default):
        if value is None: return default
        if isinstance(value, str) and not value.strip(): return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise FdeError("分页参数非法")

