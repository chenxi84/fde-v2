from fde import FdeError
import json


class MdFcstVersion:
    """月度版本主数据聚合根。计划周期节奏载体，触发自动生成行、期间折算基准。"""

    VALID_STATUSES = ("活跃", "锁定")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS md_fcst_version (
                fcst_version TEXT NOT NULL PRIMARY KEY,
                base_period TEXT NOT NULL,
                periods TEXT NOT NULL DEFAULT '[]',
                opening_date TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '活跃' CHECK (status IN ('活跃', '锁定')),
                linked_batch TEXT DEFAULT ''
            )
        """)

    def create(self, fcst_version: str, base_period: str, periods: list, opening_date: str = None):
        fcst_version = self._clean(fcst_version)
        if not fcst_version:
            raise FdeError("版本号必填，不能为空")
        if self._exists(fcst_version):
            raise FdeError(f"版本 {fcst_version} 已存在")
        base_period = self._clean(base_period)
        if not base_period:
            raise FdeError("锚定期间必填")
        if not periods or not isinstance(periods, list) or len(periods) == 0:
            raise FdeError("对应期间（periods）必填且至少一项")
        active = self._get_active()
        if active and active["status"] == "活跃":
            raise FdeError(f"当前已有活跃版本 {active['fcst_version']}，请先完成或锁定旧版本后再创建新版本")

        self.db.execute(
            "INSERT INTO md_fcst_version (fcst_version, base_period, periods, opening_date, status) VALUES (?, ?, ?, ?, '活跃')",
            (fcst_version, base_period, json.dumps(periods, ensure_ascii=False), self._clean(opening_date)),
        )
        return self.get(fcst_version)

    def get(self, fcst_version: str):
        fcst_version = self._clean(fcst_version)
        if not fcst_version:
            raise FdeError("版本号必填")
        row = self._row(fcst_version)
        if row is None:
            raise FdeError(f"版本 {fcst_version} 不存在")
        return self._to_dict(row)

    def list(self, page: int = None, page_size: int = None):
        sql = "SELECT fcst_version, base_period, periods, opening_date, status, linked_batch FROM md_fcst_version ORDER BY fcst_version DESC"
        rows = self.db.execute(sql).fetchall()
        items = [self._to_dict(r) for r in rows]
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

    def get_active(self):
        """取当前活跃版本"""
        active = self._get_active()
        if active is None:
            raise FdeError("无活跃版本，请先创建月度版本")
        return self._to_dict(active)

    def set_linked(self, fcst_version: str, rel_no: str = None):
        """R版发布联动锁定"""
        fcst_version = self._clean(fcst_version)
        if not fcst_version:
            raise FdeError("版本号必填")
        row = self._row(fcst_version)
        if row is None:
            raise FdeError(f"版本 {fcst_version} 不存在")
        if row["status"] == "锁定":
            raise FdeError(f"版本 {fcst_version} 已锁定")
        linked = self._clean(rel_no) if rel_no else row["linked_batch"]
        self.db.execute(
            "UPDATE md_fcst_version SET status = '锁定', linked_batch = ? WHERE fcst_version = ?",
            (linked, fcst_version),
        )
        return self.get(fcst_version)

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

    def _exists(self, fcst_version):
        return self.db.execute("SELECT 1 FROM md_fcst_version WHERE fcst_version = ?", (fcst_version,)).fetchone() is not None

    def _get_active(self):
        return self.db.execute(
            "SELECT fcst_version, base_period, periods, opening_date, status, linked_batch FROM md_fcst_version WHERE status = '活跃' ORDER BY fcst_version DESC LIMIT 1"
        ).fetchone()

    def _row(self, fcst_version):
        return self.db.execute(
            "SELECT fcst_version, base_period, periods, opening_date, status, linked_batch FROM md_fcst_version WHERE fcst_version = ?",
            (fcst_version,),
        ).fetchone()

    def _to_dict(self, row):
        d = dict(row)
        try:
            d["periods"] = json.loads(d["periods"]) if isinstance(d["periods"], str) else d["periods"]
        except (json.JSONDecodeError, TypeError):
            d["periods"] = []
        return d
