from fde import FdeError
from datetime import datetime


class MasterPlan:
    """主计划聚合根。线下产能平衡结果导回系统，按计划版本号版本化（每次变更 +1），
    是库存推移表「预计入库量」的输入来源。"""

    VALID_ROLLING_MONTHS = ("N+1", "N+2", "N+3")

    def import_plan(self, version_no: str, rows):
        """导入线下产能平衡结果：逐行校验，合法行落新版本（plan_version +1），返回导入摘要。"""
        version_no = self._clean(version_no)
        if not version_no:
            raise FdeError("月度版本不能为空")
        if not isinstance(rows, (list, tuple)) or len(rows) == 0:
            raise FdeError("导入行不能为空")

        # 导出净需求供线下产能平衡参考（结果不强制，失败不阻断导入）
        try:
            self.fde.call("demand", "export_net", version_no=version_no)
        except FdeError:
            pass

        valid_rows = []
        errors = []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append({"row": idx + 1, "field": "row", "message": "导入行格式必须为对象"})
                continue
            item, err = self._prepare_row(row)
            if err:
                errors.append({"row": idx + 1, "field": err[0], "message": err[1]})
            else:
                valid_rows.append(item)

        if not valid_rows:
            return {
                "version_no": version_no,
                "plan_version": None,
                "success": 0,
                "fail": len(errors),
                "errors": errors,
            }

        # 计划版本号按「物料 × 滚动月度」递增：当前最大 plan_version +1
        version_cache = {}
        for item in valid_rows:
            key = (item["material_no"], item["rolling_month"])
            if key in version_cache:
                continue
            existing = self.db.execute(
                "SELECT MAX(plan_version) AS mv FROM master_plan WHERE material_no = ? AND rolling_month = ?",
                key,
            ).fetchone()
            cur = existing["mv"] if (existing and existing["mv"] is not None) else 0
            version_cache[key] = cur + 1

        for item in valid_rows:
            self.db.execute(
                """
                    INSERT INTO master_plan (
                        material_no, version_no, rolling_month, plan_version, plan_qty, latest_inbound_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item["material_no"],
                    version_no,
                    item["rolling_month"],
                    version_cache[(item["material_no"], item["rolling_month"])],
                    item["plan_qty"],
                    item["latest_inbound_date"],
                ),
            )

        return {
            "version_no": version_no,
            "plan_version": max(version_cache.values()),
            "success": len(valid_rows),
            "fail": len(errors),
            "errors": errors,
        }

    def get(self, plan_version: int, material_no: str, rolling_month: str):
        """按主键（plan_version + material_no + rolling_month）查询单行主计划。"""
        material_no = self._clean(material_no)
        rolling_month = self._clean(rolling_month)
        if not material_no:
            raise FdeError("物料号不能为空")
        if not rolling_month:
            raise FdeError("滚动月度不能为空")
        plan_version = self._clean_plan_version(plan_version)

        row = self.db.execute(
            """
                SELECT material_no, version_no, rolling_month, plan_version, plan_qty, latest_inbound_date
                FROM master_plan
                WHERE plan_version = ? AND material_no = ? AND rolling_month = ?
            """,
            (plan_version, material_no, rolling_month),
        ).fetchone()
        if row is None:
            raise FdeError("主计划记录不存在")
        return dict(row)

    def list(self, version_no: str = None, material_no: str = None, page: int = None, size: int = None):
        """分页查询主计划，支持按月度版本、物料号筛选，默认按 plan_version 降序。"""
        version_no = self._clean(version_no)
        material_no = self._clean(material_no)

        clauses = []
        params = []
        if version_no:
            clauses.append("version_no = ?")
            params.append(version_no)
        if material_no:
            clauses.append("material_no = ?")
            params.append(material_no)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        select_sql = (
            "SELECT material_no, version_no, rolling_month, plan_version, plan_qty, latest_inbound_date"
            " FROM master_plan" + where_sql + " ORDER BY plan_version DESC, rolling_month"
        )

        rows = self.db.execute(select_sql, tuple(params)).fetchall()
        items = [dict(r) for r in rows]
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

    def get_latest(self, version_no: str, material_no: str):
        """取某物料在指定月度版本下、每个滚动月度最大 plan_version 的行（供库存推移表取预计入库量）。"""
        version_no = self._clean(version_no)
        material_no = self._clean(material_no)
        if not version_no:
            raise FdeError("月度版本不能为空")
        if not material_no:
            raise FdeError("物料号不能为空")

        rows = self.db.execute(
            """
                SELECT material_no, version_no, rolling_month, plan_version, plan_qty, latest_inbound_date
                FROM master_plan
                WHERE version_no = ? AND material_no = ?
                  AND plan_version = (
                      SELECT MAX(m2.plan_version)
                      FROM master_plan m2
                      WHERE m2.version_no = master_plan.version_no
                        AND m2.material_no = master_plan.material_no
                        AND m2.rolling_month = master_plan.rolling_month
                  )
                ORDER BY rolling_month
            """,
            (version_no, material_no),
        ).fetchall()
        return [dict(r) for r in rows]

    def _prepare_row(self, row):
        material_no = self._clean(row.get("material_no"))
        rolling_month = self._clean(row.get("rolling_month"))
        latest_inbound_date = self._clean(row.get("latest_inbound_date"))

        if not material_no:
            return None, ("material_no", "物料号不能为空")
        if not rolling_month:
            return None, ("rolling_month", "滚动月度不能为空")
        if rolling_month not in self.VALID_ROLLING_MONTHS:
            return None, ("rolling_month", "滚动月度仅支持 N+1/N+2/N+3")

        qty, qty_err = self._parse_qty(row.get("plan_qty"))
        if qty_err:
            return None, ("plan_qty", qty_err)

        if not latest_inbound_date:
            return None, ("latest_inbound_date", "最迟入库日期不能为空")
        if not self._is_valid_date(latest_inbound_date):
            return None, ("latest_inbound_date", "最迟入库日期格式应为 YYYY-MM-DD")

        return {
            "material_no": material_no,
            "rolling_month": rolling_month,
            "plan_qty": qty,
            "latest_inbound_date": latest_inbound_date,
        }, None

    def _parse_qty(self, value):
        if value is None:
            return None, "需求量不能为空"
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                return None, "需求量不能为空"
        try:
            qty = float(value)
        except (TypeError, ValueError):
            return None, "需求量必须为数字"
        if qty < 0:
            return None, "需求量不能为负"
        return qty, None

    def _is_valid_date(self, value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def _clean_plan_version(self, value):
        if value is None:
            raise FdeError("计划版本号不能为空")
        if isinstance(value, str) and not value.strip():
            raise FdeError("计划版本号不能为空")
        try:
            return int(value)
        except (TypeError, ValueError):
            raise FdeError("计划版本号不合法")

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
