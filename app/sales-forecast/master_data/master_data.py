from fde import FdeError


class MasterData:
    """通用主数据本地冗余——客户/物料/车型/用户/日历五类实体的本地副本。
    权威源在外部（MDM/ERP/HR），本地只读主体字段 + 维护域扩展属性。
    """

    def _init_db(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS md_customer (
                oem_code    TEXT PRIMARY KEY,
                oem_name    TEXT NOT NULL,
                plants      TEXT NOT NULL DEFAULT '[]',
                settle_mode TEXT NOT NULL DEFAULT '寄售',
                behavior_tag TEXT
            );
            CREATE TABLE IF NOT EXISTS md_part (
                part_no   TEXT PRIMARY KEY,
                part_name TEXT NOT NULL,
                uom       TEXT NOT NULL DEFAULT '件',
                part_type TEXT NOT NULL DEFAULT '成品',
                status    TEXT NOT NULL DEFAULT '在用'
            );
            CREATE TABLE IF NOT EXISTS md_vehicle (
                veh_model   TEXT PRIMARY KEY,
                veh_name    TEXT NOT NULL,
                platform    TEXT,
                segment     TEXT,
                powertrain  TEXT,
                price_range TEXT,
                oem_code    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS md_user (
                userno           TEXT PRIMARY KEY,
                name             TEXT NOT NULL,
                department       TEXT NOT NULL,
                role             TEXT NOT NULL,
                responsible_scope TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS md_calendar (
                date       TEXT PRIMARY KEY,
                is_workday INTEGER NOT NULL DEFAULT 1,
                shutdowns  TEXT NOT NULL DEFAULT '[]'
            );
        """)

    # ---- 客户 ----
    def get_customer(self, oem_code: str):
        row = self.db.execute("SELECT * FROM md_customer WHERE oem_code = ?", (oem_code,)).fetchone()
        if not row:
            raise FdeError(f"客户 {oem_code} 不存在于本地冗余表")
        return dict(row)

    def list_customers(self, settle_mode: str = None, keyword: str = None):
        sql = "SELECT * FROM md_customer WHERE 1=1"
        params = []
        if settle_mode:
            sql += " AND settle_mode = ?"
            params.append(settle_mode)
        if keyword:
            sql += " AND (oem_code LIKE ? OR oem_name LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ---- 物料 ----
    def get_part(self, part_no: str):
        row = self.db.execute("SELECT * FROM md_part WHERE part_no = ?", (part_no,)).fetchone()
        if not row:
            raise FdeError(f"零件 {part_no} 不存在于本地冗余表")
        return dict(row)

    def list_parts(self, part_type: str = None, status: str = "在用", keyword: str = None):
        sql = "SELECT * FROM md_part WHERE 1=1"
        params = []
        if part_type:
            sql += " AND part_type = ?"
            params.append(part_type)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if keyword:
            sql += " AND (part_no LIKE ? OR part_name LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ---- 车型 ----
    def get_vehicle(self, veh_model: str):
        row = self.db.execute("SELECT * FROM md_vehicle WHERE veh_model = ?", (veh_model,)).fetchone()
        if not row:
            raise FdeError(f"车型 {veh_model} 不存在于本地冗余表")
        return dict(row)

    def list_vehicles(self, oem_code: str = None, platform: str = None):
        sql = "SELECT * FROM md_vehicle WHERE 1=1"
        params = []
        if oem_code:
            sql += " AND oem_code = ?"
            params.append(oem_code)
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ---- 用户 ----
    def get_user(self, userno: str):
        row = self.db.execute("SELECT * FROM md_user WHERE userno = ?", (userno,)).fetchone()
        if not row:
            raise FdeError(f"用户 {userno} 不存在于本地冗余表")
        return dict(row)

    def list_users(self, role: str = None, department: str = None):
        sql = "SELECT * FROM md_user WHERE 1=1"
        params = []
        if role:
            sql += " AND role = ?"
            params.append(role)
        if department:
            sql += " AND department = ?"
            params.append(department)
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ---- 日历 ----
    def get_calendar(self, date: str):
        row = self.db.execute("SELECT * FROM md_calendar WHERE date = ?", (date,)).fetchone()
        if not row:
            raise FdeError(f"日历 {date} 不存在")
        return dict(row)

    def list_calendars(self, date_from: str, date_to: str):
        rows = self.db.execute(
            "SELECT * FROM md_calendar WHERE date >= ? AND date <= ? ORDER BY date",
            (date_from, date_to)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- 同步（被外部接口调用，覆盖主体字段） ----
    def sync_customers(self, data: list):
        for c in data:
            self.db.execute(
                "INSERT OR REPLACE INTO md_customer(oem_code, oem_name, plants, settle_mode) VALUES (?,?,?,?)",
                (c["oem_code"], c["oem_name"], c.get("plants", "[]"), c.get("settle_mode", "寄售"))
            )

    def sync_parts(self, data: list):
        for p in data:
            self.db.execute(
                "INSERT OR REPLACE INTO md_part(part_no, part_name, uom, part_type, status) VALUES (?,?,?,?,?)",
                (p["part_no"], p["part_name"], p.get("uom", "件"), p.get("part_type", "成品"), p.get("status", "在用"))
            )

    def sync_vehicles(self, data: list):
        for v in data:
            self.db.execute(
                "INSERT OR REPLACE INTO md_vehicle(veh_model, veh_name, platform, segment, powertrain, price_range, oem_code) VALUES (?,?,?,?,?,?,?)",
                (v["veh_model"], v["veh_name"], v.get("platform"), v.get("segment"),
                 v.get("powertrain"), v.get("price_range"), v["oem_code"])
            )

    def sync_users(self, data: list):
        for u in data:
            self.db.execute(
                "INSERT OR REPLACE INTO md_user(userno, name, department, role, responsible_scope) VALUES (?,?,?,?,?)",
                (u["userno"], u["name"], u["department"], u["role"], u.get("responsible_scope", "{}"))
            )

    def sync_calendars(self, data: list):
        for cal in data:
            self.db.execute(
                "INSERT OR REPLACE INTO md_calendar(date, is_workday, shutdowns) VALUES (?,?,?)",
                (cal["date"], cal.get("is_workday", 1), cal.get("shutdowns", "[]"))
            )
