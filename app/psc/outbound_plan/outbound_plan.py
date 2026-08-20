from fde import FdeError
from typing import Optional
from datetime import datetime


class OutboundPlan:
    """出库计划聚合根（手工参考创建）。

    业务人员手工登记对客户的出库计划（客户、物料、数量、计划出库日期、
    对应实际出库单号）。计划出库日期过期后系统自动关闭（惰性关闭：读取时
    结算，无需常驻定时器）；已关闭的计划仍可手工编辑延期——延期到今日及
    以后自动恢复「待出库」，库存推移表的预计出库量只取「待出库」计划。
    """

    VALID_STATUSES = ("待出库", "已关闭")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS outbound_plan (
                plan_no        TEXT PRIMARY KEY NOT NULL,
                customer_no    TEXT NOT NULL,
                material_no    TEXT NOT NULL,
                qty            REAL NOT NULL,
                out_date       TEXT NOT NULL,
                actual_out_no  TEXT,
                status         TEXT NOT NULL DEFAULT '待出库'
            )
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbound_plan_material_no ON outbound_plan (material_no)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbound_plan_customer_no ON outbound_plan (customer_no)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbound_plan_status ON outbound_plan (status)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbound_plan_out_date ON outbound_plan (out_date)"
        )

    # ---- 对外服务（公共方法）----

    def create(self, customer_no: str, material_no: str, qty, out_date: str,
               actual_out_no: Optional[str] = None):
        """手工新建出库计划：校验主数据引用，按日期判定初始状态。"""
        clean_customer = self._clean_required(customer_no, "客户编码")
        clean_material = self._clean_required(material_no, "物料号")
        clean_date = self._clean_date(out_date)
        clean_actual = self._clean_optional(actual_out_no)
        qty_num = self._to_positive_qty(qty)

        self._assert_material_exists(clean_material)
        self._assert_customer_exists(clean_customer)

        plan_no = self._generate_plan_no()
        status = self._status_for_date(clean_date)
        self.db.execute(
            """
                INSERT INTO outbound_plan (plan_no, customer_no, material_no, qty, out_date, actual_out_no, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (plan_no, clean_customer, clean_material, qty_num, clean_date, clean_actual, status),
        )
        return self.get(plan_no)

    def update(self, plan_no: str, customer_no: Optional[str] = None, material_no: Optional[str] = None,
               qty=None, out_date: Optional[str] = None, actual_out_no: Optional[str] = None):
        """编辑出库计划（已关闭亦可编辑延期）：传入字段覆盖，状态按最终日期重算。"""
        clean_no = self._clean_required(plan_no, "出库计划号")
        record = self._get_record(clean_no)

        new_customer = record["customer_no"]
        if customer_no is not None and str(customer_no).strip() != "":
            new_customer = str(customer_no).strip()
            self._assert_customer_exists(new_customer)

        new_material = record["material_no"]
        if material_no is not None and str(material_no).strip() != "":
            new_material = str(material_no).strip()
            self._assert_material_exists(new_material)

        new_qty = record["qty"]
        if qty is not None and str(qty).strip() != "":
            new_qty = self._to_positive_qty(qty)

        new_date = record["out_date"]
        if out_date is not None and str(out_date).strip() != "":
            new_date = self._clean_date(out_date)

        new_actual = record["actual_out_no"]
        if actual_out_no is not None:
            new_actual = self._clean_optional(actual_out_no)

        new_status = self._status_for_date(new_date)
        self.db.execute(
            """
                UPDATE outbound_plan
                SET customer_no = ?, material_no = ?, qty = ?, out_date = ?, actual_out_no = ?, status = ?
                WHERE plan_no = ?
            """,
            (new_customer, new_material, new_qty, new_date, new_actual, new_status, clean_no),
        )
        return self.get(clean_no)

    def delete(self, plan_no: str):
        """删除出库计划：仅「待出库」可删；已关闭为历史留痕，不可删除。"""
        clean_no = self._clean_required(plan_no, "出库计划号")
        record = self._get_record(clean_no)
        if record["status"] != "待出库":
            raise FdeError("已关闭的出库计划不可删除，如需继续执行请编辑延期")
        self.db.execute("DELETE FROM outbound_plan WHERE plan_no = ?", (clean_no,))
        return {"plan_no": clean_no, "deleted": True}

    def close_expired(self):
        """关闭到期计划：待出库且计划出库日期早于今日的计划自动关闭（幂等）。"""
        today = self._today()
        cur = self.db.execute(
            "UPDATE outbound_plan SET status = '已关闭' WHERE status = '待出库' AND out_date < ?",
            (today,),
        )
        return {"closed": cur.rowcount if cur.rowcount is not None else 0}

    def get(self, plan_no: str):
        """按出库计划号查看单条计划详情。"""
        self.close_expired()
        return self._get_record(self._clean_required(plan_no, "出库计划号"))

    def list(self, material_no: Optional[str] = None, customer_no: Optional[str] = None,
             status: Optional[str] = None, page: Optional[int] = None, size: Optional[int] = None):
        """按物料 / 客户 / 状态筛选出库计划分页列表（读取前先惰性关闭到期计划）。"""
        self.close_expired()

        material_no = self._clean_optional(material_no)
        customer_no = self._clean_optional(customer_no)
        status = self._clean_optional(status)

        if status is not None and status not in self.VALID_STATUSES:
            raise FdeError("状态筛选不合法")

        clauses = []
        params = []
        if material_no is not None:
            clauses.append("material_no = ?")
            params.append(material_no)
        if customer_no is not None:
            clauses.append("customer_no = ?")
            params.append(customer_no)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        select_sql = """
            SELECT plan_no, customer_no, material_no, qty, out_date, actual_out_no, status
            FROM outbound_plan
        """ + where_sql + " ORDER BY out_date DESC, plan_no DESC"

        rows = self.db.execute(select_sql, tuple(params)).fetchall()
        items = [dict(r) for r in rows]
        total = len(items)

        if page is None and size is None:
            return {"items": items, "total": total}

        try:
            page_int = int(page) if page is not None else 1
            size_int = int(size) if size is not None else 20
        except (TypeError, ValueError):
            raise FdeError("分页参数不合法") from None
        if page_int < 1:
            page_int = 1
        if size_int < 1:
            size_int = 20

        start = (page_int - 1) * size_int
        return {"items": items[start:start + size_int], "total": total}

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _clean_required(self, value, label):
        clean = "" if value is None else str(value).strip()
        if not clean:
            raise FdeError(f"{label}不能为空")
        return clean

    def _clean_optional(self, value):
        if value is None:
            return None
        clean = str(value).strip()
        return clean if clean else None

    def _clean_date(self, value):
        clean = "" if value is None else str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(clean, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        raise FdeError("计划出库日期格式非法，应为 YYYY-MM-DD")

    def _to_positive_qty(self, value):
        try:
            qty = float(value)
        except (TypeError, ValueError):
            raise FdeError("出库数量必须为数字") from None
        if qty <= 0:
            raise FdeError("出库数量必须大于0")
        return qty

    def _today(self):
        return datetime.now().strftime("%Y-%m-%d")

    def _status_for_date(self, out_date):
        """到期即关闭：计划出库日期早于今日 → 已关闭，否则待出库。"""
        return "已关闭" if out_date < self._today() else "待出库"

    def _assert_material_exists(self, material_no):
        try:
            result = self.fde.call("md_material", "get", material_no=material_no)
        except FdeError:
            raise FdeError("物料记录不存在") from None
        except Exception:
            raise FdeError("物料校验失败") from None
        if not result:
            raise FdeError("物料记录不存在")

    def _assert_customer_exists(self, customer_no):
        try:
            result = self.fde.call("md_customer", "get", customer_no=customer_no)
        except FdeError:
            raise FdeError("客户记录不存在") from None
        except Exception:
            raise FdeError("客户校验失败") from None
        if not result:
            raise FdeError("客户记录不存在")

    def _get_record(self, plan_no):
        row = self.db.execute(
            """
                SELECT plan_no, customer_no, material_no, qty, out_date, actual_out_no, status
                FROM outbound_plan
                WHERE plan_no = ?
            """,
            (plan_no,),
        ).fetchone()
        if row is None:
            raise FdeError("出库计划不存在")
        return dict(row)

    def _generate_plan_no(self):
        prefix = "OB" + datetime.now().strftime("%Y%m%d")
        row = self.db.execute(
            "SELECT plan_no FROM outbound_plan WHERE plan_no LIKE ? ORDER BY plan_no DESC LIMIT 1",
            (prefix + "%",),
        ).fetchone()
        seq = 1
        if row is not None:
            try:
                seq = int(row["plan_no"][len(prefix):]) + 1
            except ValueError:
                seq = 1
        for _ in range(100):
            candidate = prefix + str(seq).zfill(4)
            if self.db.execute(
                "SELECT 1 FROM outbound_plan WHERE plan_no = ?", (candidate,)
            ).fetchone() is None:
                return candidate
            seq += 1
        raise FdeError("出库计划号生成失败，请重试")

    def _to_dict(self, row):
        return dict(row)
