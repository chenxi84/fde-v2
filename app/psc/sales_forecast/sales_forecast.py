from fde import FdeError
from typing import Optional
import json
import re


class SalesForecast:
    """销售预测聚合根。

    按「正常状态物料 × 历史采购客户」生成预测清单，逐行完成客户预测调整、基线计算
    （四种方法）、事件调整、异常标记与最终预测决策，最后按物料×滚动月度汇总，
    为毛需求发布提供物料级预测输入。本聚合无独立状态列，写操作随
    md_monthly_version.lock_status（草稿才可写）流转。
    """

    # ---- 可配置常量（BR-13 / BR-16）----
    MAPE_THRESHOLD = 0.20        # MAPE 阈值：≤ 视为「小」（客户可信），> 视为「大」
    DEVIATION_THRESHOLD = 0.05   # 偏离率阈值：> 视为异常（需人工介入）
    ROLLING_MONTHS = ("N+1", "N+2", "N+3")
    DRAFT_STATUS = "草稿"

    # ---- 生命周期（必选）：加载时由平台调用，幂等建表 ----
    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS sales_forecast_line (
                version_no      TEXT    NOT NULL,
                material_no     TEXT    NOT NULL,
                customer_no     TEXT    NOT NULL,
                rolling_month   TEXT    NOT NULL,
                orig_qty        REAL,
                mape            REAL,
                bias            REAL,
                adj_qty         REAL,
                base_method     TEXT,
                base_params     TEXT,
                base_qty        REAL,
                event_analysis  TEXT,
                event_adj       REAL    NOT NULL DEFAULT 0,
                base_event_qty  REAL,
                bp_material_no  TEXT,
                switch_time     TEXT,
                abnormal_flag   INTEGER NOT NULL DEFAULT 0,
                final_qty       REAL,
                PRIMARY KEY (version_no, material_no, customer_no, rolling_month)
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS sales_forecast_summary (
                version_no      TEXT    NOT NULL,
                material_no     TEXT    NOT NULL,
                rolling_month   TEXT    NOT NULL,
                final_qty_sum   REAL    NOT NULL DEFAULT 0,
                PRIMARY KEY (version_no, material_no, rolling_month)
            )
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sf_line_version ON sales_forecast_line (version_no)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sf_line_material ON sales_forecast_line (material_no)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sf_line_customer ON sales_forecast_line (customer_no)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sf_line_abnormal ON sales_forecast_line (version_no, abnormal_flag)"
        )

    # ---- 对外服务（公共方法）----

    def open_version(self, version_no: str):
        """开启月度版本：按正常状态物料 × 该物料的历史采购客户生成清单并拆 N+1/N+2/N+3 进处理表。
        某物料无任何历史采购记录时，客户字段为空、仅初始化一行（避免 300 客户 × 3 月铺满）。"""
        version_no = self._require(version_no, "版本号")
        version = self._get_version(version_no)
        if version.get("lock_status") != self.DRAFT_STATUS:
            raise FdeError("版本已锁定，不可开启预测")

        existing = self.db.execute(
            "SELECT 1 FROM sales_forecast_line WHERE version_no = ? LIMIT 1", (version_no,)
        ).fetchone()
        if existing is not None:
            raise FdeError("该版本已开启预测，不可重复开启")

        try:
            materials = self.fde.call("md_material", "list", status="正常")
        except FdeError:
            raise FdeError("获取物料主数据失败，请稍后重试") from None
        material_list = self._as_list(materials)

        list_rows = 0
        line_rows = 0
        for material in material_list:
            material_no = self._material_no(material)
            if not material_no:
                continue
            # 客户维度按物料收窄：取该物料的历史采购客户；无历史 → 空客户占位仅一行
            customers = self._purchasing_customers(material_no)
            if not customers:
                customers = [""]
            for customer_no in customers:
                customer_no = self._clean(customer_no)
                list_rows += 1
                for rolling_month in self.ROLLING_MONTHS:
                    self.db.execute(
                        """
                            INSERT INTO sales_forecast_line
                                (version_no, material_no, customer_no, rolling_month, event_adj, abnormal_flag)
                            VALUES (?, ?, ?, ?, 0, 0)
                        """,
                        (version_no, material_no, customer_no, rolling_month),
                    )
                    line_rows += 1

        return {"version_no": version_no, "list_rows": list_rows, "line_rows": line_rows}

    def create(self, version_no: str, material_no: str, customer_no: Optional[str] = None):
        """手工新建物料×客户组合（客户可空），覆盖 open_version 未生成的组合。
        按组合拆 N+1/N+2/N+3 三行进处理表；组合已存在则拒绝重复创建。"""
        version_no = self._require(version_no, "版本号")
        self._get_version(version_no)
        self._require_draft(version_no)
        material_no = self._require(material_no, "物料号")

        # 主数据引用铁律：物料必须存在；客户非空时必须存在
        try:
            material = self.fde.call("md_material", "get", material_no=material_no)
        except FdeError:
            material = None
        if not material:
            raise FdeError("物料记录不存在")

        customer_no = self._clean(customer_no)
        if customer_no:
            try:
                cust = self.fde.call("md_customer", "get", customer_no=customer_no)
            except FdeError:
                cust = None
            if not cust:
                raise FdeError("客户记录不存在")

        existing = self.db.execute(
            "SELECT 1 FROM sales_forecast_line WHERE version_no = ? AND material_no = ? AND customer_no = ? LIMIT 1",
            (version_no, material_no, customer_no),
        ).fetchone()
        if existing is not None:
            raise FdeError("该物料×客户组合已存在，不可重复创建")

        for rolling_month in self.ROLLING_MONTHS:
            self.db.execute(
                """
                    INSERT INTO sales_forecast_line
                        (version_no, material_no, customer_no, rolling_month, event_adj, abnormal_flag)
                    VALUES (?, ?, ?, ?, 0, 0)
                """,
                (version_no, material_no, customer_no, rolling_month),
            )
        return {"version_no": version_no, "material_no": material_no, "customer_no": customer_no, "line_rows": 3}

    def fill_customer(
        self,
        version_no: str,
        material_no: str,
        customer_no: str,
        rolling_month: str,
        orig_qty: Optional[float] = None,
        adj_qty: Optional[float] = None,
    ):
        """填写客户原始预测数量，系统按 bias 自动算调整后需求（人工可调）。"""
        version_no = self._require(version_no, "版本号")
        material_no = self._require(material_no, "物料号")
        customer_no = self._require(customer_no, "客户编号")
        rolling_month = self._require(rolling_month, "滚动月度")
        self._require_draft(version_no)
        self._require_rolling_month(rolling_month)

        line = self._get_line(version_no, material_no, customer_no, rolling_month)

        try:
            material = self.fde.call("md_material", "get", material_no=material_no)
        except FdeError:
            raise FdeError("物料不存在") from None
        if not material:
            raise FdeError("物料不存在")

        try:
            customer = self.fde.call("md_customer", "get", customer_no=customer_no)
        except FdeError:
            raise FdeError("客户不存在") from None
        if not customer:
            raise FdeError("客户不存在")

        mape = None
        bias = None
        try:
            att = self.fde.call("attainment", "get", customer_no=customer_no, material_no=material_no)
        except FdeError:
            att = None
        if att:
            mape = att.get("mape")
            bias = att.get("bias")

        clean_orig = self._to_float(orig_qty, "原始需求数量")
        clean_adj = self._to_float(adj_qty, "调整后需求")
        if clean_adj is None and clean_orig is not None:
            # 调整后需求 = 原始 × (1 − bias)；无达成率（bias 缺失）按 bias=0 计，即 adj=orig
            clean_adj = round(clean_orig * (1 - (bias or 0)), 4)

        self.db.execute(
            """
                UPDATE sales_forecast_line
                SET orig_qty = ?, mape = ?, bias = ?, adj_qty = ?
                WHERE version_no = ? AND material_no = ? AND customer_no = ? AND rolling_month = ?
            """,
            (clean_orig, mape, bias, clean_adj, version_no, material_no, customer_no, rolling_month),
        )

        # N+1 原始预测自动关联到历史台账（期间=版本月+1）；实际行未到则跳过（写入实际时再拉取兜底）
        if rolling_month == "N+1" and clean_orig is not None:
            period = self._version_to_next_period(version_no)
            if period:
                try:
                    self.fde.call("sales_history", "attach_forecast",
                                  material_no=material_no, customer_no=customer_no,
                                  period=period, qty=clean_orig)
                except FdeError:
                    pass

        return self._get_line(version_no, material_no, customer_no, rolling_month)

    def calc_baseline(self, version_no: str, material_no: str, customer_no: str, rolling_month: str):
        """断点追溯前置 + 按物料基线方法/参数作用于历史干净需求，得到基线数量。"""
        version_no = self._require(version_no, "版本号")
        material_no = self._require(material_no, "物料号")
        customer_no = self._require(customer_no, "客户编号")
        rolling_month = self._require(rolling_month, "滚动月度")
        self._require_draft(version_no)
        self._require_rolling_month(rolling_month)

        line = self._get_line(version_no, material_no, customer_no, rolling_month)

        try:
            material = self.fde.call("md_material", "get", material_no=material_no)
        except FdeError:
            raise FdeError("物料不存在") from None
        if not material:
            raise FdeError("物料不存在")

        base_method = material.get("base_method")
        if not base_method:
            raise FdeError("物料未配置基线方法")
        base_params_raw = material.get("base_params")
        base_params = self._parse_json(base_params_raw)

        bp_material_no = None
        switch_time = None
        chain = None
        try:
            chain = self.fde.call("md_breakpoint", "trace", new_material_no=material_no)
            switch_time = self.fde.call("md_breakpoint", "get_switch_time",
                                        new_material_no=material_no, customer_no=customer_no)
        except FdeError:
            chain = None
            switch_time = None
        if isinstance(chain, list) and len(chain) > 1:
            bp_material_no = chain[0]

        history = self._load_sales_history(material_no=material_no, bp_chain=chain)
        horizon = {"N+1": 1, "N+2": 2, "N+3": 3}.get(rolling_month, 1)
        base_qty = self._calc_base_qty(base_method, base_params, history, horizon=horizon)

        event_adj = line.get("event_adj") or 0
        base_event_qty = (base_qty + event_adj) if base_qty is not None else None

        self.db.execute(
            """
                UPDATE sales_forecast_line
                SET base_method = ?, base_params = ?, base_qty = ?, base_event_qty = ?,
                    bp_material_no = ?, switch_time = ?
                WHERE version_no = ? AND material_no = ? AND customer_no = ? AND rolling_month = ?
            """,
            (
                base_method,
                base_params_raw,
                base_qty,
                base_event_qty,
                bp_material_no,
                switch_time,
                version_no,
                material_no,
                customer_no,
                rolling_month,
            ),
        )
        return self._get_line(version_no, material_no, customer_no, rolling_month)

    def calc_baseline_batch(self, version_no: str, material_no: str = None, customer_no: str = None):
        """批量算基线：遍历版本内全部处理行（可按物料/客户收窄）逐行 calc_baseline，
        单行失败（物料无基线方法/无历史等）跳过不阻断。返回 {version_no, computed, failed}。"""
        version_no = self._require(version_no, "版本号")
        self._require_draft(version_no)

        sql = ("SELECT DISTINCT material_no, customer_no, rolling_month FROM sales_forecast_line "
               "WHERE version_no = ?")
        params = [version_no]
        if material_no:
            sql += " AND material_no = ?"
            params.append(self._clean(material_no))
        if customer_no:
            sql += " AND customer_no = ?"
            params.append(self._clean(customer_no))
        rows = self.db.execute(sql, tuple(params)).fetchall()

        computed = failed = 0
        for r in rows:
            try:
                self.calc_baseline(version_no, r["material_no"], r["customer_no"], r["rolling_month"])
                computed += 1
            except FdeError:
                failed += 1
        return {"version_no": version_no, "computed": computed, "failed": failed}

    def import_orig_qty(self, version_no: str, rows):
        """批量导入客户原始预测：逐行调 fill_customer 写 orig_qty（自动算 adj、N+1 关联历史台账），
        单行失败（物料/客户不存在、月度非法、非草稿等）跳过不阻断。返回 {total,success,fail,errors}。"""
        version_no = self._require(version_no, "版本号")
        self._require_draft(version_no)
        if not isinstance(rows, (list, tuple)):
            raise FdeError("导入数据必须为列表")

        total, success, errors = len(rows), 0, []
        for i, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                errors.append({"row": i, "field": "", "message": "行数据格式非法"})
                continue
            m = self._clean(row.get("material_no"))
            c = self._clean(row.get("customer_no"))
            rm = self._clean(row.get("rolling_month"))
            if not m or not c or not rm:
                errors.append({"row": i, "field": "", "message": "缺少 material_no/customer_no/rolling_month"})
                continue
            try:
                self.fill_customer(version_no, m, c, rm, orig_qty=row.get("orig_qty"))
                success += 1
            except FdeError as e:
                errors.append({"row": i, "field": "", "message": str(e)})
        return {"total": total, "success": success, "fail": len(errors), "errors": errors}

    def adjust_event(
        self,
        version_no: str,
        material_no: str,
        customer_no: str,
        rolling_month: str,
        event_analysis: Optional[str] = None,
        event_adj: Optional[float] = 0,
    ):
        """填写事件分析/事件调整量，重算基线和事件合计量（只作用归属期，不外推）。"""
        version_no = self._require(version_no, "版本号")
        material_no = self._require(material_no, "物料号")
        customer_no = self._require(customer_no, "客户编号")
        rolling_month = self._require(rolling_month, "滚动月度")
        self._require_draft(version_no)
        self._require_rolling_month(rolling_month)

        line = self._get_line(version_no, material_no, customer_no, rolling_month)

        clean_event_adj = self._to_float(event_adj, "事件调整量")
        if clean_event_adj is None:
            clean_event_adj = 0.0
        clean_analysis = None
        if event_analysis is not None and str(event_analysis).strip() != "":
            clean_analysis = str(event_analysis).strip()

        base_qty = line.get("base_qty")
        base_event_qty = (base_qty + clean_event_adj) if base_qty is not None else None

        self.db.execute(
            """
                UPDATE sales_forecast_line
                SET event_analysis = ?, event_adj = ?, base_event_qty = ?
                WHERE version_no = ? AND material_no = ? AND customer_no = ? AND rolling_month = ?
            """,
            (clean_analysis, clean_event_adj, base_event_qty, version_no, material_no, customer_no, rolling_month),
        )
        return self._get_line(version_no, material_no, customer_no, rolling_month)

    def decide(self, version_no: str, material_no: str, customer_no: str, rolling_month: str):
        """按 MAPE 与偏离率自动标记异常并给出最终预测建议（异常行不自动填写）。"""
        version_no = self._require(version_no, "版本号")
        material_no = self._require(material_no, "物料号")
        customer_no = self._require(customer_no, "客户编号")
        rolling_month = self._require(rolling_month, "滚动月度")
        self._require_draft(version_no)
        self._require_rolling_month(rolling_month)

        line = self._get_line(version_no, material_no, customer_no, rolling_month)

        mape = None
        try:
            att = self.fde.call("attainment", "get", customer_no=customer_no, material_no=material_no)
        except FdeError:
            att = None
        if att:
            mape = att.get("mape")

        adj_qty = line.get("adj_qty")
        base_qty = line.get("base_qty")
        # 物料级口径：该品种全部客户调整后需求合计，与基线（物料级）同口径对比
        adj_sum = self._adj_sum(version_no, material_no, rolling_month)

        abnormal_flag = False
        final_qty = None

        if base_qty is None or adj_sum is None:
            # 基线或合计缺失 → 无法物料级对比，不标记异常，取客户调整后值
            final_qty = adj_qty
        else:
            deviation = self._deviation(base_qty, adj_sum)
            if deviation > self.DEVIATION_THRESHOLD:
                # 物料级偏离 > 阈值 → 该物料该月全部客户行标记异常，final 待人工
                abnormal_flag = True
                final_qty = None
            else:
                # 不异常 → 单客户最终取各自调整后值
                final_qty = adj_qty

        self.db.execute(
            """
                UPDATE sales_forecast_line
                SET mape = ?, abnormal_flag = ?, final_qty = ?
                WHERE version_no = ? AND material_no = ? AND customer_no = ? AND rolling_month = ?
            """,
            (mape, 1 if abnormal_flag else 0, final_qty, version_no, material_no, customer_no, rolling_month),
        )
        return self._get_line(version_no, material_no, customer_no, rolling_month)

    def set_final(self, version_no: str, material_no: str, customer_no: str, rolling_month: str, final_qty: float):
        """异常行人工填写最终预测量（非异常行拒绝人工覆盖）。"""
        version_no = self._require(version_no, "版本号")
        material_no = self._require(material_no, "物料号")
        customer_no = self._require(customer_no, "客户编号")
        rolling_month = self._require(rolling_month, "滚动月度")
        self._require_draft(version_no)
        self._require_rolling_month(rolling_month)

        line = self._get_line(version_no, material_no, customer_no, rolling_month)
        if not line.get("abnormal_flag"):
            raise FdeError("该行非异常行，无需人工填写")

        clean_final = self._to_float(final_qty, "最终预测量")
        if clean_final is None:
            raise FdeError("最终预测量不能为空")

        self.db.execute(
            """
                UPDATE sales_forecast_line
                SET final_qty = ?
                WHERE version_no = ? AND material_no = ? AND customer_no = ? AND rolling_month = ?
            """,
            (clean_final, version_no, material_no, customer_no, rolling_month),
        )
        return self._get_line(version_no, material_no, customer_no, rolling_month)

    def decide_batch(self, version_no: str, material_no: str = None, customer_no: str = None):
        """批量决策：遍历版本内全部处理行（可按物料/客户收窄）逐行 decide，单行失败跳过。
        返回 {version_no, computed, failed, abnormal}，abnormal 为标记异常的行数。"""
        version_no = self._require(version_no, "版本号")
        self._require_draft(version_no)

        sql = ("SELECT DISTINCT material_no, customer_no, rolling_month FROM sales_forecast_line "
               "WHERE version_no = ?")
        params = [version_no]
        if material_no:
            sql += " AND material_no = ?"
            params.append(self._clean(material_no))
        if customer_no:
            sql += " AND customer_no = ?"
            params.append(self._clean(customer_no))
        rows = self.db.execute(sql, tuple(params)).fetchall()

        computed = failed = abnormal = 0
        for r in rows:
            try:
                line = self.decide(version_no, r["material_no"], r["customer_no"], r["rolling_month"])
                computed += 1
                if line and line.get("abnormal_flag"):
                    abnormal += 1
            except FdeError:
                failed += 1
        return {"version_no": version_no, "computed": computed, "failed": failed, "abnormal": abnormal}

    def summarize(self, version_no: str):
        """按物料 × 滚动月度合计所有客户最终预测量，刷新汇总表。"""
        version_no = self._require(version_no, "版本号")
        self._require_draft(version_no)

        rows = self.db.execute(
            """
                SELECT material_no, rolling_month, SUM(COALESCE(final_qty, 0)) AS final_qty_sum
                FROM sales_forecast_line
                WHERE version_no = ?
                GROUP BY material_no, rolling_month
                ORDER BY material_no, rolling_month
            """,
            (version_no,),
        ).fetchall()

        self.db.execute("DELETE FROM sales_forecast_summary WHERE version_no = ?", (version_no,))
        for row in rows:
            self.db.execute(
                """
                    INSERT INTO sales_forecast_summary (version_no, material_no, rolling_month, final_qty_sum)
                    VALUES (?, ?, ?, ?)
                """,
                (version_no, row["material_no"], row["rolling_month"], row["final_qty_sum"]),
            )

        return {"version_no": version_no, "summary_rows": len(rows)}

    def get(self, version_no: str, material_no: str, customer_no: str, rolling_month: str):
        """按主键取处理表单行全部字段。"""
        version_no = self._require(version_no, "版本号")
        material_no = self._require(material_no, "物料号")
        customer_no = self._require(customer_no, "客户编号")
        rolling_month = self._require(rolling_month, "滚动月度")
        return self._get_line(version_no, material_no, customer_no, rolling_month)

    def list(
        self,
        version_no: Optional[str] = None,
        material_no: Optional[str] = None,
        customer_no: Optional[str] = None,
        rolling_month: Optional[str] = None,
        abnormal_flag: Optional[bool] = None,
        page: Optional[int] = None,
        size: Optional[int] = None,
    ):
        """按版本/物料/客户/滚动月度/异常标记筛选分页查询处理表。"""
        clauses = []
        params = []

        if version_no is not None:
            clean = self._clean(version_no)
            if clean:
                clauses.append("version_no = ?")
                params.append(clean)
        if material_no is not None:
            clean = self._clean(material_no)
            if clean:
                clauses.append("material_no = ?")
                params.append(clean)
        if customer_no is not None:
            clean = self._clean(customer_no)
            if clean:
                clauses.append("customer_no = ?")
                params.append(clean)
        if rolling_month is not None:
            clean = self._clean(rolling_month)
            if clean:
                if clean not in self.ROLLING_MONTHS:
                    raise FdeError("滚动月度只能为 N+1 / N+2 / N+3")
                clauses.append("rolling_month = ?")
                params.append(clean)
        if abnormal_flag is not None:
            flag = self._to_bool(abnormal_flag)
            if flag is None:
                raise FdeError("异常标记筛选不合法")
            clauses.append("abnormal_flag = ?")
            params.append(flag)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        select_sql = "SELECT * FROM sales_forecast_line" + where_sql + " ORDER BY version_no, material_no, customer_no, rolling_month"

        page_int, size_int = self._page_size(page, size)
        rows = self.db.execute(select_sql, tuple(params)).fetchall()
        total = len(rows)

        if page_int is not None:
            start = (page_int - 1) * size_int
            rows = rows[start:start + size_int]

        return {"items": [dict(row) for row in rows], "total": total}

    def get_summary(self, version_no: str, material_no: Optional[str] = None):
        """取指定版本（可指定物料）的汇总行，供毛需求合成。"""
        version_no = self._require(version_no, "版本号")
        if material_no is not None:
            material_no = self._clean(material_no)
            if not material_no:
                raise FdeError("物料号不能为空")
            rows = self.db.execute(
                """
                    SELECT version_no, material_no, rolling_month, final_qty_sum
                    FROM sales_forecast_summary
                    WHERE version_no = ? AND material_no = ?
                    ORDER BY material_no, rolling_month
                """,
                (version_no, material_no),
            ).fetchall()
        else:
            rows = self.db.execute(
                """
                    SELECT version_no, material_no, rolling_month, final_qty_sum
                    FROM sales_forecast_summary
                    WHERE version_no = ?
                    ORDER BY material_no, rolling_month
                """,
                (version_no,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _require(self, value, label):
        clean = "" if value is None else str(value).strip()
        if not clean:
            raise FdeError(f"{label}不能为空")
        return clean

    def _clean(self, value):
        return "" if value is None else str(value).strip()

    def _to_float(self, value, label):
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise FdeError(f"{label}不合法") from None

    def _to_bool(self, value):
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return 1 if value else 0
        s = str(value).strip().lower()
        if s in ("1", "true", "是", "y", "yes", "t"):
            return 1
        if s in ("0", "false", "否", "n", "no", "f"):
            return 0
        return None

    def _page_size(self, page, size):
        if page is None and size is None:
            return None, None
        try:
            page_int = int(page) if page is not None else 1
            size_int = int(size) if size is not None else 100
        except (TypeError, ValueError):
            raise FdeError("分页参数不合法") from None
        if page_int < 1 or size_int < 1:
            raise FdeError("分页参数不合法")
        return page_int, size_int

    def _parse_json(self, raw):
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _as_list(self, result):
        if result is None:
            return []
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("items", "list", "records", "data"):
                if isinstance(result.get(key), list):
                    return result[key]
        return []

    def _material_no(self, material):
        if isinstance(material, dict):
            return material.get("material_no")
        return None

    def _require_rolling_month(self, rolling_month):
        if rolling_month not in self.ROLLING_MONTHS:
            raise FdeError("滚动月度只能为 N+1 / N+2 / N+3")

    def _get_version(self, version_no):
        try:
            version = self.fde.call("md_monthly_version", "get", version_no=version_no)
        except FdeError:
            raise FdeError("月度版本不存在") from None
        if not version:
            raise FdeError("月度版本不存在")
        return version

    def _require_draft(self, version_no, locked_msg="版本已锁定，预测不可修改"):
        version = self._get_version(version_no)
        if version.get("lock_status") != self.DRAFT_STATUS:
            raise FdeError(locked_msg)
        return version

    def _get_line(self, version_no, material_no, customer_no, rolling_month):
        row = self.db.execute(
            """
                SELECT * FROM sales_forecast_line
                WHERE version_no = ? AND material_no = ? AND customer_no = ? AND rolling_month = ?
            """,
            (version_no, material_no, customer_no, rolling_month),
        ).fetchone()
        if row is None:
            raise FdeError("处理表行不存在")
        return dict(row)

    def _load_sales_history(self, material_no=None, bp_chain=None, **kwargs):
        """历史台账适配器（替代 V1 stub）：委托 sales_history 应用，不动公共方法。
        物料/断点链均空 → purchasing_customers（全量客户维度）；
        否则 → history_sequence（期升序数量；断点链=多物料按期求和）。失败/为空返回 []。"""
        try:
            has_chain = isinstance(bp_chain, list) and bp_chain
            if not material_no and not has_chain:
                customers = self.fde.call("sales_history", "purchasing_customers")
                return customers if isinstance(customers, list) else []
            materials = bp_chain if has_chain else material_no
            seq = self.fde.call("sales_history", "history_sequence", material_nos=materials)
            return seq if isinstance(seq, list) else []
        except FdeError:
            return []

    def _purchasing_customers(self, material_no):
        """该物料的历史采购客户（去重升序）；无历史 / 异常 → 空列表。"""
        try:
            customers = self.fde.call("sales_history", "purchasing_customers", material_no=material_no)
            if not isinstance(customers, list):
                return []
            return [c for c in (self._clean(c) for c in customers) if c]
        except FdeError:
            return []

    def customer_forecast_history(self, material_no: str, customer_no: str, months: int = None):
        """历史客户预测投影（供达成率计算，口径A）：取 rolling=N+1 且 orig_qty 非空的行，
        期间 = 版本月+1（即"提前一个月"的客户预测），返回 [{period, orig_qty}] 按 period 升序。
        months 给定时仅保留末尾 N 个月。"""
        material_no = self._clean(material_no)
        customer_no = self._clean(customer_no)
        if not material_no or not customer_no:
            return []

        rows = self.db.execute(
            "SELECT version_no, orig_qty FROM sales_forecast_line "
            "WHERE material_no = ? AND customer_no = ? AND rolling_month = 'N+1' AND orig_qty IS NOT NULL "
            "ORDER BY version_no",
            (material_no, customer_no),
        ).fetchall()

        out = []
        for r in rows:
            period = self._version_to_next_period(r["version_no"])
            if period:
                out.append({"period": period, "orig_qty": r["orig_qty"]})

        n = self._to_int(months, 0) if months is not None else 0
        if n and out:
            out = out[-n:]
        return out

    def _version_to_next_period(self, version_no):
        """YYYYMM 版本 → 其 N+1 期间 YYYY-MM。非法返回 None。"""
        v = self._clean(version_no)
        if not re.fullmatch(r"\d{6}", v):
            return None
        y, m = int(v[:4]), int(v[4:6])
        if m < 1 or m > 12:
            return None
        m += 1
        if m > 12:
            y, m = y + 1, 1
        return f"{y:04d}-{m:02d}"

    def _calc_base_qty(self, base_method, params, history, horizon=1):
        """基线数量。horizon=滚动月度步长（N+1=1…）。
        移动平均/阶跃/借用参考为水平法（各月度相同）；指数平滑按 trend/seasonal 向前投影 horizon 步。"""
        history = history or []
        if base_method == "移动平均":
            window = self._int_param(params, "window", 6)
            recent = history[-window:]
            return round(sum(recent) / len(recent), 4) if recent else None
        if base_method == "指数平滑":
            return self._es_forecast(params, history, horizon)
        if base_method == "阶跃检测":
            lookback = self._int_param(params, "lookback", 6)
            recent = history[-lookback:]
            return round(sum(recent) / len(recent), 4) if recent else None
        if base_method == "借用参考":
            ref_material = params.get("ref_material") if params else None
            if not ref_material:
                raise FdeError("借用参考缺少参考物料号")
            scale = self._float_param(params, "scale", 1.0)
            ref_history = self._load_sales_history(material_no=ref_material)
            if not ref_history:
                return None
            return round(sum(ref_history) / len(ref_history) * scale, 4)
        raise FdeError("未知基线方法")

    def _es_forecast(self, params, history, horizon):
        """指数平滑 horizon 步预测：trend→Holt 线性外推；seasonal→Holt-Winters 加法；否则水平平推。"""
        if not history:
            return None
        params = params or {}
        alpha = self._float_param(params, "alpha", 0.3)
        beta = self._float_param(params, "beta", 0.1)
        gamma = self._float_param(params, "gamma", 0.1)
        trend = bool(params.get("trend"))
        seasonal = bool(params.get("seasonal"))
        period = self._int_param(params, "period", 12)
        n = len(history)

        if seasonal and period >= 2 and n >= 2 * period:
            return self._hw_forecast(history, alpha, beta, gamma, period, horizon)
        if trend:
            level = history[0]
            tr = (history[1] - history[0]) if n > 1 else 0.0
            for d in history[1:]:
                prev_level = level
                level = alpha * d + (1 - alpha) * (level + tr)
                tr = beta * (level - prev_level) + (1 - beta) * tr
            return round(level + horizon * tr, 4)
        level = sum(history) / n
        for d in history:
            level = alpha * d + (1 - alpha) * level
        return round(level, 4)

    def _hw_forecast(self, hist, alpha, beta, gamma, p, horizon):
        """Holt-Winters 加法季节模型，返回 horizon 步预测。"""
        n = len(hist)
        m1 = sum(hist[:p]) / p
        m2 = sum(hist[p:2 * p]) / p
        level = m1
        tr = (m2 - m1) / p
        season = [hist[i] - m1 for i in range(p)]
        for t in range(p, n):
            d = hist[t]
            prev_level = level
            level = alpha * (d - season[t - p]) + (1 - alpha) * (level + tr)
            tr = beta * (level - prev_level) + (1 - beta) * tr
            season[t - p] = gamma * (d - level) + (1 - gamma) * season[t - p]
        si = (n - 1 + horizon) % p
        return round(level + horizon * tr + season[si], 4)

    def _int_param(self, params, key, default):
        try:
            return int(params.get(key, default))
        except (TypeError, ValueError):
            return default

    def _float_param(self, params, key, default):
        try:
            return float(params.get(key, default))
        except (TypeError, ValueError):
            return default

    def _adj_sum(self, version_no, material_no, rolling_month):
        """该品种（版本+物料+滚动月度）全部客户调整后需求合计；无任一客户填报返回 None。"""
        row = self.db.execute(
            "SELECT SUM(adj_qty) AS s FROM sales_forecast_line "
            "WHERE version_no = ? AND material_no = ? AND rolling_month = ? AND adj_qty IS NOT NULL",
            (version_no, material_no, rolling_month),
        ).fetchone()
        return row["s"] if row and row["s"] is not None else None

    def _deviation(self, base_qty, adj_sum):
        if adj_sum == 0:
            return abs(base_qty - adj_sum)
        return abs(base_qty - adj_sum) / adj_sum
