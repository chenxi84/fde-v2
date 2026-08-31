from __future__ import annotations

from fde import FdeError


class Attainment:
    """达成率与置信度聚合根。客户×物料粒度的 MAPE/bias 派生指标，由 ERP 统计后经
    _load_attainment 适配器冗余回写。数据来源类型：自动参考创建——前端禁止创建入口，
    不提供 create 服务。"""

    def upsert(self, customer_no: str, material_no: str, mape: float, bias: float):
        """ERP 统计回写 MAPE/bias：同客户+物料存在则覆盖更新，不存在则插入（幂等）。"""
        customer_no = self._clean(customer_no)
        material_no = self._clean(material_no)
        if not customer_no or not material_no:
            raise FdeError("客户编码/物料号不能为空")

        mape = self._to_num(mape, "MAPE")
        if mape < 0:
            raise FdeError("MAPE 不能为负")

        bias = self._to_num(bias, "bias")

        existing = self.db.execute(
            "SELECT 1 FROM attainment WHERE customer_no = ? AND material_no = ?",
            (customer_no, material_no),
        ).fetchone()
        if existing:
            self.db.execute(
                "UPDATE attainment SET mape = ?, bias = ? WHERE customer_no = ? AND material_no = ?",
                (mape, bias, customer_no, material_no),
            )
        else:
            self.db.execute(
                "INSERT INTO attainment (customer_no, material_no, mape, bias) VALUES (?, ?, ?, ?)",
                (customer_no, material_no, mape, bias),
            )

        return {
            "customer_no": customer_no,
            "material_no": material_no,
            "mape": mape,
            "bias": bias,
        }

    def get(self, customer_no: str, material_no: str):
        """按客户+物料查询该组合的 MAPE/bias；未命中返回 None，不抛异常。"""
        customer_no = self._clean(customer_no)
        material_no = self._clean(material_no)
        if not customer_no or not material_no:
            raise FdeError("客户编码/物料号不能为空")

        row = self.db.execute(
            "SELECT customer_no, material_no, mape, bias FROM attainment WHERE customer_no = ? AND material_no = ?",
            (customer_no, material_no),
        ).fetchone()
        if row is None:
            return None
        return self._to_dict(row)

    def list(self, customer_no: str = None, material_no: str = None, page: int = None, size: int = None):
        """按客户/物料（AND 关系，可选）筛选达成率列表，分页返回 {items, total}。"""
        customer_no = self._clean(customer_no)
        material_no = self._clean(material_no)

        sql = "SELECT customer_no, material_no, mape, bias FROM attainment"
        clauses, params = [], []
        if customer_no:
            clauses.append("customer_no = ?")
            params.append(customer_no)
        if material_no:
            clauses.append("material_no = ?")
            params.append(material_no)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY customer_no, material_no"

        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [self._to_dict(r) for r in rows]
        total = len(items)

        if page is None and size is None:
            return {"items": items, "total": total}

        page_no = self._to_int(page, 1)
        page_sz = self._to_int(size, 20)
        if page_no < 1:
            page_no = 1
        if page_sz < 1:
            page_sz = 20

        start = (page_no - 1) * page_sz
        return {"items": items[start:start + page_sz], "total": total}

    def compute(self, months=6):
        """口径A 单表计算 MAPE/bias 并回写：直接读 sales_history 行内
        forecast_qty（N+1 原始预测，F）与 qty（实际干净需求，A），无需 join 销售预测。
        滚动 months 个月（默认6），窗口内有效样本<3 或 Σ实际=0 则跳过。返回 {computed, skipped}。
        计算前先调 sales_history.sync_forecast 回填 forecast_qty，保证单表数据最新。"""
        months_n = self._months_int(months)
        try:
            self.fde.call("sales_history", "sync_forecast")
        except FdeError:
            pass
        try:
            hist = self.fde.call("sales_history", "list")
        except FdeError:
            hist = {"items": []}
        items = hist.get("items") if isinstance(hist, dict) else (hist or [])

        groups = {}
        for r in items or []:
            key = (r.get("customer_no"), r.get("material_no"))
            groups.setdefault(key, []).append(
                (r.get("period"), r.get("forecast_qty"), r.get("qty")))

        computed = skipped = 0
        for (customer_no, material_no), rows in sorted(groups.items()):
            # 仅取 F 与 A 均非空的期间，按期间升序
            pairs = sorted((p, F, A) for p, F, A in rows if F is not None and A is not None)
            if pairs and months_n:
                cutoff = self._shift_month(pairs[-1][0], -(months_n - 1))
                pairs = [t for t in pairs if t[0] >= cutoff]
            if len(pairs) < 3:
                skipped += 1
                continue
            sumF = sum(F for _, F, _ in pairs)
            sumA = sum(A for _, _, A in pairs)
            if sumA == 0:
                skipped += 1
                continue
            bias = (sumF - sumA) / sumA
            mape_vals = [abs(A - F) / A for _, F, A in pairs if A != 0]
            if not mape_vals:
                skipped += 1
                continue
            mape = sum(mape_vals) / len(mape_vals)
            self.upsert(customer_no, material_no, round(mape, 4), round(bias, 4))
            computed += 1
        return {"computed": computed, "skipped": skipped}

    def _months_int(self, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return 6
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise FdeError("months 非法")
        if n < 1:
            raise FdeError("months 非法")
        return n

    def _shift_month(self, period, delta):
        y, m = int(period[:4]), int(period[5:7])
        idx = y * 12 + (m - 1) + delta
        return f"{idx // 12:04d}-{idx % 12 + 1:02d}"

    def _load_attainment(self):
        """ERP 达成率统计适配器（外部系统，不建聚合）。
        真实接入：从 ERP 拉取客户×物料粒度的 MAPE/bias 后逐条调用 upsert 冗余回写；
        只换本方法实现，不动公共方法。V1 本地 stub：返回空 dict，不执行任何回写。"""
        return {}

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _to_num(self, value, label):
        if value is None or (isinstance(value, str) and not value.strip()):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            raise FdeError(f"{label} 必须为数值")

    def _to_int(self, value, default):
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise FdeError("分页参数非法")

    def _to_dict(self, row):
        return {
            "customer_no": row["customer_no"],
            "material_no": row["material_no"],
            "mape": row["mape"],
            "bias": row["bias"],
        }
