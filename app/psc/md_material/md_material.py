import json
from datetime import datetime

from fde import FdeError


class MdMaterial:
    """物料主数据聚合根。

    物料号（material_no）是全链 11 个业务聚合的核心键，本应用作为物料号的
    权威来源，承载物料基础信息（编号/名称/状态）与两套参数（预测方法参数 +
    库存策略参数），并为策略拟合（strategy_fitting）提供 set_fit_params 回填服务。
    """

    _STATUS = ("正常", "EOP", "停用")
    _VALUE_CLASS = ("高", "低")
    _CHANGE_RISK = ("高", "低")
    _BASE_METHODS = ("移动平均", "指数平滑", "阶跃检测", "借用参考")

    def create(self, material_no: str, material_name: str, status: str = "正常",
               unit_value: float = None, value_class: str = None, change_cost: float = None,
               prod_days: float = None, logistics_days: float = None, change_risk: str = None,
               service_level: float = None, batch_window: float = None,
               base_method: str = None, base_params: str = None):
        """新建物料主数据记录，material_no 全局唯一。"""
        values, errors = self._normalize_record(
            material_no, material_name, status, unit_value, value_class, change_cost,
            prod_days, logistics_days, change_risk, service_level, batch_window,
            base_method, base_params,
        )
        if errors:
            raise FdeError(next(iter(errors.values())))
        if self._exists(values["material_no"]):
            raise FdeError("该物料号已存在")
        self._insert(values)
        return self._to_dict(self._row(values["material_no"]))

    def get(self, material_no: str):
        """查询单个物料的完整主数据与参数。"""
        material_no = self._clean(material_no)
        if not material_no:
            raise FdeError("物料号不能为空")
        row = self._row(material_no)
        if row is None:
            raise FdeError("物料记录不存在")
        return self._to_dict(row)

    def list(self, material_no: str = None, material_name: str = None,
             status: str = None, page: int = None, size: int = None):
        """按物料号/名称模糊、状态精确筛选的分页列表。返回全字段，供列表自选显示列。"""
        sql = ("SELECT material_no, material_name, status, unit_value, value_class, change_cost, "
               "prod_days, logistics_days, change_risk, service_level, batch_window, base_method, "
               "base_params, fit_version, fit_effective_at FROM md_material")
        clauses = []
        params = []

        material_no = self._clean(material_no)
        if material_no:
            clauses.append("material_no LIKE '%' || ? || '%'")
            params.append(material_no)

        material_name = self._clean(material_name)
        if material_name:
            clauses.append("material_name LIKE '%' || ? || '%'")
            params.append(material_name)

        status = self._clean(status)
        if status:
            if status not in self._STATUS:
                raise FdeError("状态仅支持正常/EOP/停用")
            clauses.append("status = ?")
            params.append(status)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY material_no"

        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [self._to_dict(r) for r in rows]
        total = len(items)

        if page is None and size is None:
            return {"items": items, "total": total}

        page_no = self._to_int(page, 1)
        size_no = self._to_int(size, 20)
        if page_no < 1:
            page_no = 1
        if size_no < 1:
            size_no = 20
        start = (page_no - 1) * size_no
        return {"items": items[start:start + size_no], "total": total}

    def update(self, material_no: str, material_name: str = None, status: str = None,
               unit_value: float = None, value_class: str = None, change_cost: float = None,
               prod_days: float = None, logistics_days: float = None, change_risk: str = None,
               service_level: float = None, batch_window: float = None,
               base_method: str = None, base_params: str = None):
        """更新物料名称与各参数；material_no（主键）与 status（只读）不可修改。"""
        material_no = self._clean(material_no)
        if not material_no:
            raise FdeError("物料号不能为空")
        row = self._row(material_no)
        if row is None:
            raise FdeError("物料记录不存在")

        # status 由外部维护，本系统只读，不接受 update 修改
        if status is not None:
            new_status = self._clean(status)
            if new_status and new_status != row["status"]:
                raise FdeError("状态由外部维护，本系统只读")

        name = row["material_name"]
        if material_name is not None:
            name = self._clean(material_name)
            if not name:
                raise FdeError("物料名称不能为空")

        if value_class is not None:
            value_class = self._check_value_class(value_class)
        else:
            value_class = row["value_class"]

        if change_risk is not None:
            change_risk = self._check_change_risk(change_risk)
        else:
            change_risk = row["change_risk"]

        if unit_value is not None:
            unit_value = self._check_nonneg(unit_value, "单位货值")
        else:
            unit_value = row["unit_value"]

        if change_cost is not None:
            change_cost = self._check_nonneg(change_cost, "切线成本")
        else:
            change_cost = row["change_cost"]

        if prod_days is not None:
            prod_days = self._check_nonneg(prod_days, "生产时间")
        else:
            prod_days = row["prod_days"]

        if logistics_days is not None:
            logistics_days = self._check_nonneg(logistics_days, "物流时间")
        else:
            logistics_days = row["logistics_days"]

        if service_level is not None:
            service_level = self._check_service_level(service_level)
        else:
            service_level = row["service_level"]

        if batch_window is not None:
            batch_window = self._check_batch_window(batch_window)
        else:
            batch_window = row["batch_window"]

        # 基线方法/参数成对处理：改方法但未给参数 → 用新方法默认值；只改参数 → 按现有方法校验
        new_method = row["base_method"]
        new_params = row["base_params"]
        if base_method is not None:
            new_method = self._clean(base_method)
            if new_method not in self._BASE_METHODS:
                raise FdeError("基线方法仅支持移动平均/指数平滑/阶跃检测/借用参考")
            new_params = self._normalize_base_params(new_method, base_params)
        elif base_params is not None:
            if not new_method:
                raise FdeError("基线参数与基线方法不匹配")
            new_params = self._normalize_base_params(new_method, base_params)

        self.db.execute(
            "UPDATE md_material SET material_name = ?, unit_value = ?, value_class = ?, "
            "change_cost = ?, prod_days = ?, logistics_days = ?, change_risk = ?, "
            "service_level = ?, batch_window = ?, base_method = ?, base_params = ? "
            "WHERE material_no = ?",
            (name, unit_value, value_class, change_cost, prod_days, logistics_days,
             change_risk, service_level, batch_window, new_method, new_params, material_no),
        )
        return self._to_dict(self._row(material_no))

    def import_batch(self, rows: list):
        """批量导入/更新（upsert）：逐行校验，成功行入库，失败行返回错误明细。"""
        if not isinstance(rows, (list, tuple)):
            raise FdeError("导入数据须为行列表")

        success = 0
        fail = 0
        errors = []
        for idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                fail += 1
                errors.append({"row": idx, "field": None, "message": "行数据须为对象"})
                continue
            values, row_errors = self._normalize_record(
                row.get("material_no"), row.get("material_name"), row.get("status"),
                row.get("unit_value"), row.get("value_class"), row.get("change_cost"),
                row.get("prod_days"), row.get("logistics_days"), row.get("change_risk"),
                row.get("service_level"), row.get("batch_window"), row.get("base_method"),
                row.get("base_params"),
            )
            if row_errors:
                fail += 1
                field, message = next(iter(row_errors.items()))
                errors.append({"row": idx, "field": field, "message": message})
                continue
            if self._exists(values["material_no"]):
                self._update_all(values)
            else:
                self._insert(values)
            success += 1

        return {"total": len(rows), "success": success, "fail": fail, "errors": errors}

    def set_fit_params(self, material_no: str, base_method: str, base_params: str,
                       batch_window: float, service_level: float, fit_version: str):
        """拟合参数回填（被 strategy_fitting 调用），更新方法/参数并记录版本快照。"""
        material_no = self._clean(material_no)
        if not material_no:
            raise FdeError("物料号不能为空")
        if self._row(material_no) is None:
            raise FdeError("物料记录不存在")

        base_method = self._clean(base_method)
        if base_method not in self._BASE_METHODS:
            raise FdeError("基线方法仅支持移动平均/指数平滑/阶跃检测/借用参考")
        params_norm = self._normalize_base_params(base_method, base_params)

        bw = self._check_batch_window(batch_window)
        if bw is None:
            raise FdeError("组批窗口须大于 0")
        sl = self._check_service_level(service_level)
        if sl is None:
            raise FdeError("满足率目标须在 0~1 之间")

        fit_version = self._clean(fit_version)
        if not fit_version:
            raise FdeError("拟合版本不能为空")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.db.execute(
            "UPDATE md_material SET base_method = ?, base_params = ?, batch_window = ?, "
            "service_level = ?, fit_version = ?, fit_effective_at = ? "
            "WHERE material_no = ?",
            (base_method, params_norm, bw, sl, fit_version, now, material_no),
        )

        # 记录参数版本快照（material_no + fit_version 唯一，重复版本覆盖更新），供回滚追溯
        existing = self.db.execute(
            "SELECT 1 FROM md_material_param_version WHERE material_no = ? AND fit_version = ?",
            (material_no, fit_version),
        ).fetchone()
        if existing:
            self.db.execute(
                "UPDATE md_material_param_version SET base_method = ?, base_params = ?, "
                "batch_window = ?, service_level = ?, effective_at = ? "
                "WHERE material_no = ? AND fit_version = ?",
                (base_method, params_norm, bw, sl, now, material_no, fit_version),
            )
        else:
            self.db.execute(
                "INSERT INTO md_material_param_version (material_no, fit_version, base_method, "
                "base_params, batch_window, service_level, effective_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (material_no, fit_version, base_method, params_norm, bw, sl, now),
            )

        return self._to_dict(self._row(material_no))

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _normalize_record(self, material_no, material_name, status="正常", unit_value=None,
                          value_class=None, change_cost=None, prod_days=None, logistics_days=None,
                          change_risk=None, service_level=None, batch_window=None,
                          base_method=None, base_params=None):
        """整行校验：返回 (values, errors)；errors 非空表示存在非法字段。"""
        errors = {}
        values = {}

        material_no = self._clean(material_no)
        if not material_no:
            errors["material_no"] = "物料号不能为空"
        values["material_no"] = material_no

        material_name = self._clean(material_name)
        if not material_name:
            errors["material_name"] = "物料名称不能为空"
        values["material_name"] = material_name

        try:
            values["status"] = self._check_status(status)
        except FdeError as e:
            errors["status"] = str(e)
            values["status"] = None

        try:
            values["value_class"] = self._check_value_class(value_class)
        except FdeError as e:
            errors["value_class"] = str(e)
            values["value_class"] = None

        try:
            values["change_risk"] = self._check_change_risk(change_risk)
        except FdeError as e:
            errors["change_risk"] = str(e)
            values["change_risk"] = None

        try:
            values["unit_value"] = self._check_nonneg(unit_value, "单位货值")
        except FdeError as e:
            errors["unit_value"] = str(e)
            values["unit_value"] = None

        try:
            values["change_cost"] = self._check_nonneg(change_cost, "切线成本")
        except FdeError as e:
            errors["change_cost"] = str(e)
            values["change_cost"] = None

        try:
            values["prod_days"] = self._check_nonneg(prod_days, "生产时间")
        except FdeError as e:
            errors["prod_days"] = str(e)
            values["prod_days"] = None

        try:
            values["logistics_days"] = self._check_nonneg(logistics_days, "物流时间")
        except FdeError as e:
            errors["logistics_days"] = str(e)
            values["logistics_days"] = None

        try:
            values["service_level"] = self._check_service_level(service_level)
        except FdeError as e:
            errors["service_level"] = str(e)
            values["service_level"] = None

        try:
            values["batch_window"] = self._check_batch_window(batch_window)
        except FdeError as e:
            errors["batch_window"] = str(e)
            values["batch_window"] = None

        method = self._clean(base_method)
        if method:
            if method not in self._BASE_METHODS:
                errors["base_method"] = "基线方法仅支持移动平均/指数平滑/阶跃检测/借用参考"
                values["base_method"] = None
                values["base_params"] = None
            else:
                values["base_method"] = method
                try:
                    values["base_params"] = self._normalize_base_params(method, base_params)
                except FdeError as e:
                    errors["base_params"] = str(e)
                    values["base_params"] = None
        else:
            if self._clean(base_params):
                errors["base_params"] = "基线参数与基线方法不匹配"
            values["base_method"] = None
            values["base_params"] = None

        return values, errors

    def _normalize_base_params(self, base_method, base_params):
        """校验 base_params 与 base_method 匹配，返回规范化后的 JSON 字符串。"""
        bp = self._clean(base_params)
        if not bp:
            params = {
                "移动平均": {"window": 6},
                "指数平滑": {"alpha": 0.3, "trend": False},
                "阶跃检测": {"threshold": 0.3, "confirm_periods": 2, "lookback": 6},
                "借用参考": {},
            }[base_method]
        else:
            try:
                params = json.loads(bp)
            except ValueError:
                raise FdeError("基线参数须为合法 JSON 字符串")
            if not isinstance(params, dict):
                raise FdeError("基线参数须为合法 JSON 字符串")

        if base_method == "移动平均":
            if "window" not in params:
                raise FdeError("基线参数与基线方法不匹配")
            window = params["window"]
            if isinstance(window, bool) or not isinstance(window, int) or window < 3 or window > 12:
                raise FdeError("移动平均 window 须为 3~12 的整数")

        elif base_method == "指数平滑":
            if "alpha" not in params:
                raise FdeError("基线参数与基线方法不匹配")
            alpha = params["alpha"]
            if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or alpha < 0 or alpha > 1:
                raise FdeError("指数平滑 alpha 须在 0~1 之间")
            for key in ("beta", "gamma"):
                if key in params:
                    val = params[key]
                    if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0 or val > 1:
                        raise FdeError(f"指数平滑 {key} 须在 0~1 之间")
            for key in ("trend", "seasonal"):
                if key in params and not isinstance(params[key], bool):
                    raise FdeError(f"指数平滑 {key} 须为布尔值")
            if "period" in params:
                period = params["period"]
                if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
                    raise FdeError("指数平滑 period 须为正整数")

        elif base_method == "阶跃检测":
            if "threshold" not in params:
                raise FdeError("基线参数与基线方法不匹配")
            threshold = params["threshold"]
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or threshold < 0 or threshold > 1:
                raise FdeError("阶跃检测 threshold 须在 0~1 之间")
            if "confirm_periods" in params:
                cp = params["confirm_periods"]
                if isinstance(cp, bool) or not isinstance(cp, int) or cp < 1 or cp > 3:
                    raise FdeError("阶跃检测 confirm_periods 须为 1~3 的整数")
            if "lookback" in params:
                lb = params["lookback"]
                if isinstance(lb, bool) or not isinstance(lb, int) or lb < 3 or lb > 12:
                    raise FdeError("阶跃检测 lookback 须为 3~12 的整数")

        elif base_method == "借用参考":
            ref = params.get("ref_material")
            if not ref or not str(ref).strip():
                raise FdeError("借用参考 ref_material 必填")
            if not self._exists(str(ref).strip()):
                raise FdeError("借用参考 ref_material 不存在")
            if "scale" in params:
                scale = params["scale"]
                if isinstance(scale, bool) or not isinstance(scale, (int, float)) or scale <= 0:
                    raise FdeError("借用参考 scale 须大于 0")
            if "mode" in params and params["mode"] not in ("trend", "season", "lifecycle"):
                raise FdeError("借用参考 mode 仅支持 trend/season/lifecycle")

        return json.dumps(params, ensure_ascii=False)

    def _insert(self, values):
        self.db.execute(
            "INSERT INTO md_material (material_no, material_name, status, unit_value, "
            "value_class, change_cost, prod_days, logistics_days, change_risk, service_level, "
            "batch_window, base_method, base_params) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (values["material_no"], values["material_name"], values["status"],
             values["unit_value"], values["value_class"], values["change_cost"],
             values["prod_days"], values["logistics_days"], values["change_risk"],
             values["service_level"], values["batch_window"], values["base_method"],
             values["base_params"]),
        )

    def _update_all(self, values):
        self.db.execute(
            "UPDATE md_material SET material_name = ?, status = ?, unit_value = ?, "
            "value_class = ?, change_cost = ?, prod_days = ?, logistics_days = ?, "
            "change_risk = ?, service_level = ?, batch_window = ?, base_method = ?, "
            "base_params = ? WHERE material_no = ?",
            (values["material_name"], values["status"], values["unit_value"],
             values["value_class"], values["change_cost"], values["prod_days"],
             values["logistics_days"], values["change_risk"], values["service_level"],
             values["batch_window"], values["base_method"], values["base_params"],
             values["material_no"]),
        )

    def _check_status(self, value):
        v = self._clean(value) or "正常"
        if v not in self._STATUS:
            raise FdeError("状态仅支持正常/EOP/停用")
        return v

    def _check_value_class(self, value):
        v = self._clean(value)
        if v and v not in self._VALUE_CLASS:
            raise FdeError("价值分类仅支持高/低")
        return v or None

    def _check_change_risk(self, value):
        v = self._clean(value)
        if v and v not in self._CHANGE_RISK:
            raise FdeError("变更风险等级仅支持高/低")
        return v or None

    def _check_nonneg(self, value, label):
        n = self._num(value, label)
        if n is not None and n < 0:
            raise FdeError(f"{label}不能为负")
        return n

    def _check_service_level(self, value):
        n = self._num(value, "满足率目标")
        if n is not None and not (0 <= n <= 1):
            raise FdeError("满足率目标须在 0~1 之间")
        return n

    def _check_batch_window(self, value):
        n = self._num(value, "组批窗口")
        if n is not None and n <= 0:
            raise FdeError("组批窗口须大于 0")
        return n

    def _num(self, value, label="数值"):
        if value is None:
            return None
        if isinstance(value, bool):
            raise FdeError(f"{label}须为数字")
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if s == "":
            return None
        try:
            return float(s)
        except ValueError:
            raise FdeError(f"{label}须为数字")

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _to_int(self, value, default):
        if value is None:
            return default
        if isinstance(value, bool):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise FdeError("分页参数非法")

    def _exists(self, material_no):
        return (
            self.db.execute(
                "SELECT 1 FROM md_material WHERE material_no = ?",
                (material_no,),
            ).fetchone()
            is not None
        )

    def _row(self, material_no):
        return self.db.execute(
            "SELECT material_no, material_name, status, unit_value, value_class, change_cost, "
            "prod_days, logistics_days, change_risk, service_level, batch_window, base_method, "
            "base_params, fit_version, fit_effective_at FROM md_material WHERE material_no = ?",
            (material_no,),
        ).fetchone()

    def _to_dict(self, row):
        if row is None:
            return None
        return {
            "material_no": row["material_no"],
            "material_name": row["material_name"],
            "status": row["status"],
            "unit_value": row["unit_value"],
            "value_class": row["value_class"],
            "change_cost": row["change_cost"],
            "prod_days": row["prod_days"],
            "logistics_days": row["logistics_days"],
            "change_risk": row["change_risk"],
            "service_level": row["service_level"],
            "batch_window": row["batch_window"],
            "base_method": row["base_method"],
            "base_params": row["base_params"],
            "fit_version": row["fit_version"],
            "fit_effective_at": row["fit_effective_at"],
        }

