from __future__ import annotations

from fde import FdeError
import re


class InventoryStrategy:
    """库存策略聚合根，管理物料×月度版本的三层水位（最低A/安全C/组批B）与品种分层对冲工具判定。"""

    VALID_HEDGE_TOOLS = ("库存", "速度")
    SERVICE_FACTORS = {0.90: 1.28, 0.95: 1.65, 0.98: 2.05, 0.99: 2.33}

    def calc(self, version_no: str, material_no: str, customer_no: str = None):
        """计算单物料库存策略（三层水位+对冲工具），同物料同版本重复计算即覆盖更新。"""
        version_no = self._validate_version(version_no)
        material_no = self._clean_material_no(material_no)
        return self._calc_one(version_no, material_no, customer_no)

    def calc_batch(self, version_no: str):
        """整版本批量计算库存策略，逐物料计算，单个物料失败不中断其余物料。"""
        version_no = self._validate_version(version_no)
        result = self.fde.call("md_material", "list", status="正常")
        materials = result.get("items") if isinstance(result, dict) else result
        success = 0
        fail = 0
        errors = []
        for m in materials:
            material_no = m.get("material_no") if isinstance(m, dict) else m
            if not material_no:
                fail += 1
                errors.append({"material_no": "", "message": "物料号缺失"})
                continue
            try:
                self._calc_one(version_no, str(material_no).strip(), None)
                success += 1
            except FdeError as e:
                fail += 1
                errors.append({"material_no": str(material_no).strip(), "message": str(e)})
        return {"total": len(materials), "success": success, "fail": fail, "errors": errors}

    def get(self, version_no: str, material_no: str):
        """查看单物料库存策略详情（含水位带下限/上限派生值）。"""
        version_no = self._validate_version(version_no)
        material_no = self._clean_material_no(material_no)
        row = self._row(version_no, material_no)
        if row is None:
            raise FdeError("库存策略记录不存在")
        return self._to_record(row)

    def list(self, version_no: str = None, material_no: str = None, hedge_tool: str = None,
             page: int = None, size: int = None):
        """按版本/物料/对冲工具筛选查看库存策略列表，支持分页。"""
        if version_no is not None:
            version_no = str(version_no).strip() or None
        if material_no is not None:
            material_no = str(material_no).strip() or None
        if hedge_tool is not None:
            hedge_tool = str(hedge_tool).strip() or None
            if hedge_tool is not None and hedge_tool not in self.VALID_HEDGE_TOOLS:
                raise FdeError("对冲工具筛选不合法")

        clauses = []
        params = []
        if version_no:
            clauses.append("version_no = ?")
            params.append(version_no)
        if material_no:
            clauses.append("material_no LIKE '%' || ? || '%'")
            params.append(material_no)
        if hedge_tool:
            clauses.append("hedge_tool = ?")
            params.append(hedge_tool)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        select_sql = (
            "SELECT version_no, material_no, hedge_tool, min_level, service_factor, "
            "resp_volatility, safety_level, batch_window, batch_level, basis "
            "FROM inventory_strategy" + where_sql + " ORDER BY material_no"
        )
        rows = self.db.execute(select_sql, tuple(params)).fetchall()
        items = [self._to_record(r) for r in rows]
        total = len(items)

        if page is None and size is None:
            return {"items": items, "total": total}
        try:
            page_int = int(page) if page is not None else 1
            size_int = int(size) if size is not None else 20
        except (TypeError, ValueError):
            raise FdeError("分页参数非法") from None
        if page_int < 1 or size_int < 1:
            raise FdeError("分页参数非法") from None
        start = (page_int - 1) * size_int
        return {"items": items[start:start + size_int], "total": total}

    def get_water_level(self, version_no: str, material_no: str):
        """取三层水位（供下游应用对照水位线），返回 A/C/B 及水位带上下限。"""
        version_no = self._validate_version(version_no)
        material_no = self._clean_material_no(material_no)
        row = self._row(version_no, material_no)
        if row is None:
            raise FdeError("库存策略记录不存在")
        rec = self._to_record(row)
        return {
            "min_level": rec["min_level"],
            "safety_level": rec["safety_level"],
            "batch_level": rec["batch_level"],
            "lower": rec["lower"],
            "upper": rec["upper"],
        }

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _calc_one(self, version_no, material_no, customer_no):
        rec = self._compute(version_no, material_no, customer_no)
        self._upsert(rec)
        return self._to_record(self._row(version_no, material_no))

    def _compute(self, version_no, material_no, customer_no):
        material = self.fde.call("md_material", "get", material_no=material_no)
        if not material:
            raise FdeError(f"物料 {material_no} 不存在")

        prod_days = self._to_num(material.get("prod_days"), 0.0)
        logistics_days = self._to_num(material.get("logistics_days"), 0.0)
        batch_window = self._to_num(material.get("batch_window"), 0.0)
        value_class = str(material.get("value_class") or "低").strip()
        service_level = material.get("service_level")

        # BR-15 参数合法性校验
        if prod_days < 0:
            raise FdeError("生产时间不能为负")
        if logistics_days < 0:
            raise FdeError("物流时间不能为负")
        if batch_window < 0:
            raise FdeError("组批窗口不能为负")

        service_factor = self._service_factor(service_level)

        # BR-04 可用缓冲天数默认 0；有客户缓冲协议时按 line_stock_days 扣减
        line_stock_days = 0.0
        transfer_lead_days = 0.0
        if customer_no:
            customer_no = str(customer_no).strip()
            customer = self.fde.call("md_customer", "get", customer_no=customer_no)
            if not customer:
                raise FdeError(f"客户 {customer_no} 不存在")
            line_stock_days = self._to_num(customer.get("line_stock_days"), 0.0)
            transfer_lead_days = self._to_num(customer.get("transfer_lead_days"), 0.0)

        # 近 N 期（默认 12 个月）历史干净需求
        history = self._load_sales_history(material_no)
        if not history:
            # 兜底：无历史数据（新品/初始场景）→ 水位按 0 计算（日需求/波动为 0），basis 注明，不阻断主链
            basis = self._build_basis(material_no, prod_days, logistics_days, service_level,
                                      batch_window, 0, 0.0, "库存")
            return {
                "version_no": version_no,
                "material_no": material_no,
                "hedge_tool": "库存",
                "min_level": 0.0,
                "service_factor": self._num(service_factor),
                "resp_volatility": 0.0,
                "safety_level": 0.0,
                "batch_window": self._num(batch_window),
                "batch_level": 0.0,
                "basis": basis + "（无历史数据，水位按 0）",
            }

        # BR-02 日需求 = 近 N 期月均干净需求 ÷ 30
        monthly_avg = sum(history) / len(history)
        daily_demand = monthly_avg / 30.0

        # BR-06 响应窗口需求波动 σ_L（滚动 L 期累计标准差）
        resp_volatility = self._resp_window_volatility(history, prod_days, logistics_days)

        # BR-03 最低库存 A = 日需求 × max(0, 生产时间 + 物流时间 − 可用缓冲天数)
        min_level = daily_demand * max(0.0, prod_days + logistics_days - line_stock_days)

        # BR-08 安全库存 C = 服务系数 × 响应窗口波动
        safety_level = service_factor * resp_volatility

        # BR-09 组批库存 B = 日需求 × 组批窗口
        batch_level = daily_demand * batch_window

        # BR-11/BR-12 品种分层：高价值 + 生产周期短（生产+物流 ≤ 线边+调拨提前期）→ 速度对冲
        if value_class == "高" and (prod_days + logistics_days) <= (line_stock_days + transfer_lead_days):
            hedge_tool = "速度"
            safety_level = 0.0
            batch_level = 0.0
            batch_window = 0.0
        else:
            hedge_tool = "库存"

        basis = self._build_basis(material_no, prod_days, logistics_days, service_level,
                                  batch_window, len(history), monthly_avg, hedge_tool)

        return {
            "version_no": version_no,
            "material_no": material_no,
            "hedge_tool": hedge_tool,
            "min_level": self._num(min_level),
            "service_factor": self._num(service_factor),
            "resp_volatility": self._num(resp_volatility),
            "safety_level": self._num(safety_level),
            "batch_window": self._num(batch_window),
            "batch_level": self._num(batch_level),
            "basis": basis,
        }

    def _upsert(self, rec):
        version_no = rec["version_no"]
        material_no = rec["material_no"]
        if self._exists(version_no, material_no):
            self.db.execute("""
                UPDATE inventory_strategy
                SET hedge_tool = ?, min_level = ?, service_factor = ?, resp_volatility = ?,
                    safety_level = ?, batch_window = ?, batch_level = ?, basis = ?
                WHERE version_no = ? AND material_no = ?
            """, (
                rec["hedge_tool"], rec["min_level"], rec["service_factor"], rec["resp_volatility"],
                rec["safety_level"], rec["batch_window"], rec["batch_level"], rec["basis"],
                version_no, material_no,
            ))
        else:
            self.db.execute("""
                INSERT INTO inventory_strategy
                    (version_no, material_no, hedge_tool, min_level, service_factor,
                     resp_volatility, safety_level, batch_window, batch_level, basis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                version_no, material_no, rec["hedge_tool"], rec["min_level"], rec["service_factor"],
                rec["resp_volatility"], rec["safety_level"], rec["batch_window"], rec["batch_level"],
                rec["basis"],
            ))

    def _load_sales_history(self, material_no, months=12):
        # 历史台账适配器（替代 stub）：委托 sales_history.history_sequence 近 months 期；
        # 失败/台账为空 → []（水位按 0 兜底不变）。
        try:
            seq = self.fde.call("sales_history", "history_sequence",
                                material_nos=[material_no], limit=months)
            return seq if isinstance(seq, list) else []
        except FdeError:
            return []

    def _resp_window_volatility(self, history, prod_days, logistics_days):
        # BR-05/BR-06：响应窗口 L(月) = (生产时间+物流时间)/30；滚动 L 期累计需求标准差
        if not history:
            return 0.0
        L = (prod_days + logistics_days) / 30.0
        if L <= 0:
            return 0.0
        if L < 1.0:
            # 窗口不足一期：累计需求按 L 比例折算（等价于方法一 σ×L 参考）
            scaled = [d * L for d in history]
            return self._std(scaled)
        w = int(round(L))
        w = max(1, min(w, len(history)))
        rolling = [sum(history[i:i + w]) for i in range(len(history) - w + 1)]
        return self._std(rolling)

    def _std(self, values):
        # 样本标准差（ddof=1）
        n = len(values)
        if n < 2:
            return 0.0
        mean = sum(values) / n
        return (sum((v - mean) ** 2 for v in values) / (n - 1)) ** 0.5

    def _service_factor(self, service_level):
        # BR-07 满足率目标 → 标准正态分位数
        if service_level is None or service_level == "":
            raise FdeError("满足率目标不能为空")
        try:
            sl = float(service_level)
        except (TypeError, ValueError):
            raise FdeError("满足率目标格式非法") from None
        if 1.0 < sl <= 100.0:
            sl = sl / 100.0
        key = round(sl, 2)
        if key not in self.SERVICE_FACTORS:
            raise FdeError("满足率目标仅支持 90%/95%/98%/99%")
        return self.SERVICE_FACTORS[key]

    def _build_basis(self, material_no, prod_days, logistics_days, service_level,
                     batch_window, n, monthly_avg, hedge_tool):
        sl = float(service_level)
        if 1.0 < sl <= 100.0:
            sl = sl / 100.0
        sl_pct = "%.0f%%" % (sl * 100)
        return (f"物料{material_no}：生产{self._num(prod_days)}天+物流{self._num(logistics_days)}天，"
                f"满足率{sl_pct}，组批窗口{self._num(batch_window)}天，"
                f"近{n}期月均干净需求{self._num(monthly_avg)}件，对冲工具{hedge_tool}")

    def _validate_version(self, version_no):
        v = "" if version_no is None else str(version_no).strip()
        if not v:
            raise FdeError("月度版本不能为空")
        if not re.fullmatch(r"\d{6}", v) or int(v[4:6]) < 1 or int(v[4:6]) > 12:
            raise FdeError("版本号格式必须为 YYYYMM")
        return v

    def _clean_material_no(self, material_no):
        v = "" if material_no is None else str(material_no).strip()
        if not v:
            raise FdeError("物料号不能为空")
        return v

    def _row(self, version_no, material_no):
        return self.db.execute(
            "SELECT version_no, material_no, hedge_tool, min_level, service_factor, "
            "resp_volatility, safety_level, batch_window, batch_level, basis "
            "FROM inventory_strategy WHERE version_no = ? AND material_no = ?",
            (version_no, material_no),
        ).fetchone()

    def _exists(self, version_no, material_no):
        return self.db.execute(
            "SELECT 1 FROM inventory_strategy WHERE version_no = ? AND material_no = ?",
            (version_no, material_no),
        ).fetchone() is not None

    def _to_record(self, row):
        a = self._num(row["min_level"])
        c = self._num(row["safety_level"])
        b = self._num(row["batch_level"])
        return {
            "version_no": row["version_no"],
            "material_no": row["material_no"],
            "hedge_tool": row["hedge_tool"],
            "min_level": a,
            "service_factor": self._num(row["service_factor"]),
            "resp_volatility": self._num(row["resp_volatility"]),
            "safety_level": c,
            "batch_window": self._num(row["batch_window"]),
            "batch_level": b,
            "basis": row["basis"],
            "lower": self._num(a + c),
            "upper": self._num(a + c + b),
        }

    def _to_num(self, value, default=0.0):
        if value is None or value == "":
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            raise FdeError("数值参数非法") from None

    def _num(self, value):
        if value is None:
            return 0
        try:
            f = round(float(value), 2)
        except (TypeError, ValueError):
            return value
        return int(f) if f.is_integer() else f
