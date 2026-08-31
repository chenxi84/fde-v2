from fde import FdeError
import re
from datetime import datetime


class MdMonthlyVersion:
    """月度版本主数据聚合根。"""

    VALID_LOCK_STATUSES = ("草稿", "发布（锁定）", "冻结")
    # 锚定期间格式：与历史台账 sales_history.period 一致（YYYY-MM）
    _PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

    def create(self, version_no: str, anchor_period: str, opening_date: str):
        version_no = self._clean(version_no)
        if not version_no:
            raise FdeError("版本号不能为空")
        self._validate_version_no(version_no)

        anchor_period = self._clean(anchor_period)
        if not anchor_period:
            raise FdeError("锚定期间不能为空")
        if not self._PERIOD_RE.match(anchor_period):
            raise FdeError("锚定期间格式必须为 YYYY-MM（与历史台账期间一致）")

        opening_date = self._clean(opening_date)
        if not opening_date:
            raise FdeError("opening 日不能为空")
        self._validate_date(opening_date)

        if self._exists(version_no):
            raise FdeError("该版本号已存在")

        active = self._get_active_row()
        if active is not None:
            raise FdeError(
                f"已存在活跃版本 {active['version_no']}（{active['lock_status']}）。"
                f"同一时刻仅一个活跃版本，请先将其冻结后再新建。"
            )

        self.db.execute(
            "INSERT INTO md_monthly_version (version_no, anchor_period, opening_date, lock_status) "
            "VALUES (?, ?, ?, ?)",
            (version_no, anchor_period, opening_date, "草稿"),
        )
        return self.get(version_no)

    def get(self, version_no: str):
        version_no = self._clean(version_no)
        if not version_no:
            raise FdeError("版本号不能为空")

        row = self._row(version_no)
        if row is None:
            raise FdeError("版本记录不存在")
        return self._to_dict(row)

    def list(self, version_no: str = None, lock_status: str = None, page: int = None, size: int = None):
        version_no = self._clean(version_no)
        lock_status = self._clean(lock_status)

        if lock_status and lock_status not in self.VALID_LOCK_STATUSES:
            raise FdeError("锁定状态筛选不合法")

        clauses = []
        params = []

        if version_no:
            clauses.append("version_no = ?")
            params.append(version_no)

        if lock_status:
            clauses.append("lock_status = ?")
            params.append(lock_status)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        select_sql = (
            "SELECT version_no, anchor_period, opening_date, lock_status "
            "FROM md_monthly_version" + where_sql + " ORDER BY version_no DESC"
        )

        rows = self.db.execute(select_sql, tuple(params)).fetchall()
        items = [self._to_dict(row) for row in rows]
        total = len(items)

        if page is None and size is None:
            return {"items": items, "total": total}

        page_int = self._to_int(page, 1)
        size_int = self._to_int(size, 20)

        if page_int < 1:
            raise FdeError("页码必须大于等于1")
        if size_int < 1:
            raise FdeError("每页条数必须大于等于1")

        start = (page_int - 1) * size_int
        return {"items": items[start:start + size_int], "total": total}

    def publish(self, version_no: str):
        version_no = self._clean(version_no)
        if not version_no:
            raise FdeError("版本号不能为空")

        row = self._row(version_no)
        if row is None:
            raise FdeError("版本记录不存在")

        if row["lock_status"] != "草稿":
            raise FdeError("仅草稿状态可发布")

        self.db.execute(
            "UPDATE md_monthly_version SET lock_status = ? WHERE version_no = ?",
            ("发布（锁定）", version_no),
        )
        return self.get(version_no)

    def freeze(self, version_no: str):
        version_no = self._clean(version_no)
        if not version_no:
            raise FdeError("版本号不能为空")

        row = self._row(version_no)
        if row is None:
            raise FdeError("版本记录不存在")

        status = row["lock_status"]
        if status == "草稿":
            raise FdeError("仅发布（锁定）状态可冻结")
        if status == "冻结":
            raise FdeError("版本已冻结，不可逆")

        self.db.execute(
            "UPDATE md_monthly_version SET lock_status = ? WHERE version_no = ?",
            ("冻结", version_no),
        )
        return self.get(version_no)

    def get_active(self):
        row = self._get_active_row()
        if row is None:
            return None
        return self._to_dict(row)

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _get_active_row(self):
        return self.db.execute(
            "SELECT version_no, anchor_period, opening_date, lock_status "
            "FROM md_monthly_version WHERE lock_status != ? "
            "ORDER BY version_no DESC LIMIT 1",
            ("冻结",),
        ).fetchone()

    def _validate_version_no(self, version_no):
        if not re.fullmatch(r"\d{6}", version_no):
            raise FdeError("版本号格式必须为 YYYYMM")
        month = int(version_no[4:6])
        if month < 1 or month > 12:
            raise FdeError("版本号格式必须为 YYYYMM")

    def _validate_date(self, date_str):
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except (TypeError, ValueError):
            raise FdeError("opening 日必须为合法日期")

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
            raise FdeError("分页参数不合法")

    def _exists(self, version_no):
        return (
            self.db.execute(
                "SELECT 1 FROM md_monthly_version WHERE version_no = ?",
                (version_no,),
            ).fetchone()
            is not None
        )

    def _row(self, version_no):
        return self.db.execute(
            "SELECT version_no, anchor_period, opening_date, lock_status "
            "FROM md_monthly_version WHERE version_no = ?",
            (version_no,),
        ).fetchone()

    def _to_dict(self, row):
        return {
            "version_no": row["version_no"],
            "anchor_period": row["anchor_period"],
            "opening_date": row["opening_date"],
            "lock_status": row["lock_status"],
        }
