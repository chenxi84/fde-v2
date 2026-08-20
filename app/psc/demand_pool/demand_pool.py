from fde import FdeError
from typing import Optional
from datetime import datetime


class DemandPool:
    """需求池（补库单）聚合根，管理三类补库单的击穿生成、下达与状态机闭环流转。"""

    VALID_REPLENISH_TYPES = ("缺货补库", "最低库存补库", "安全库存补库")
    VALID_STATUSES = ("待下达", "已下达", "生产中", "已完成", "已取消")

    # 三类补库优先级：缺货 > 最低库存 > 安全库存（BR-05，由触发方据此判定类型）
    REPLENISH_PRIORITY = ("缺货补库", "最低库存补库", "安全库存补库")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS demand_pool (
                replenish_no      TEXT PRIMARY KEY NOT NULL,
                material_no       TEXT NOT NULL,
                replenish_type    TEXT NOT NULL,
                replenish_qty     REAL NOT NULL,
                required_inbound  TEXT NOT NULL,
                promised_inbound  TEXT,
                status            TEXT NOT NULL DEFAULT '待下达'
            )
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_demand_pool_material_no ON demand_pool (material_no)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_demand_pool_replenish_type ON demand_pool (replenish_type)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_demand_pool_status ON demand_pool (status)"
        )

    # ---- 对外服务（公共方法）----

    def create(self, material_no: str, replenish_type: str, replenish_qty, required_inbound: str,
               stock_on_hand=None, min_level_a=None, safety_level_c=None, batch_level_b=None,
               capacity_tight=None):
        """库存推移表击穿触发自动生成补库单（数据来源类型：自动参考创建，非手工新建）。"""
        clean_material = self._clean_material_no(material_no)
        clean_type = self._clean_replenish_type(replenish_type)
        clean_required = self._clean_required_inbound(required_inbound)

        # BR-08 物料主数据引用铁律：material_no 必须存在于 md_material
        self._assert_material_exists(clean_material)

        # BR-07 产能松紧：入参 > ctx > 默认富余
        tight = capacity_tight if capacity_tight is not None else bool(self.ctx.get("capacity_tight", False))

        # BR-06 按产能松紧分档补货量：富余补到组批水位 B，紧张补到触发水位线
        resolved_qty = self._resolve_replenish_qty(
            clean_type, replenish_qty, stock_on_hand, min_level_a, safety_level_c, batch_level_b, tight
        )
        qty = self._to_positive_qty(resolved_qty)

        replenish_no = self._generate_replenish_no()
        self.db.execute(
            """
                INSERT INTO demand_pool (replenish_no, material_no, replenish_type, replenish_qty, required_inbound, promised_inbound, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (replenish_no, clean_material, clean_type, qty, clean_required, None, "待下达"),
        )
        return self.get(replenish_no)

    def release(self, replenish_no: str, promised_inbound: Optional[str] = None):
        """下达生产：待下达 -> 已下达，经 _dispatch_to_erp 适配器下发生产计划给 ERP。"""
        clean_no = self._clean_replenish_no(replenish_no)
        record = self._get_record(clean_no)

        if record["status"] != "待下达":
            raise FdeError("当前状态不可下达")

        clean_promised = self._clean_optional_date(promised_inbound, "承诺入库时间")

        # 先经适配器下发 ERP，成功后再推进状态
        self._dispatch_to_erp(record)

        self.db.execute(
            "UPDATE demand_pool SET status = ?, promised_inbound = ? WHERE replenish_no = ?",
            ("已下达", clean_promised, clean_no),
        )
        return self.get(clean_no)

    def on_workorder_started(self, replenish_no: str):
        """ERP 回传工单开工：已下达 -> 生产中。"""
        clean_no = self._clean_replenish_no(replenish_no)
        record = self._get_record(clean_no)

        if record["status"] != "已下达":
            raise FdeError("当前状态不可开工回传")

        self.db.execute(
            "UPDATE demand_pool SET status = ? WHERE replenish_no = ?",
            ("生产中", clean_no),
        )
        return self.get(clean_no)

    def on_inbound(self, replenish_no: str):
        """ERP 回传入库：生产中 -> 已完成（终态）。"""
        clean_no = self._clean_replenish_no(replenish_no)
        record = self._get_record(clean_no)

        if record["status"] != "生产中":
            raise FdeError("当前状态不可入库回传")

        self.db.execute(
            "UPDATE demand_pool SET status = ? WHERE replenish_no = ?",
            ("已完成", clean_no),
        )
        return self.get(clean_no)

    def cancel(self, replenish_no: str):
        """需求消失作废：待下达 / 已下达 -> 已取消（终态）。"""
        clean_no = self._clean_replenish_no(replenish_no)
        record = self._get_record(clean_no)

        if record["status"] not in ("待下达", "已下达"):
            raise FdeError("当前状态不可取消")

        self.db.execute(
            "UPDATE demand_pool SET status = ? WHERE replenish_no = ?",
            ("已取消", clean_no),
        )
        return self.get(clean_no)

    def get(self, replenish_no: str):
        """按补库单号查看单条补库单详情。"""
        return self._get_record(self._clean_replenish_no(replenish_no))

    def list(self, material_no: Optional[str] = None, replenish_type: Optional[str] = None,
             status: Optional[str] = None, page: Optional[int] = None, size: Optional[int] = None):
        """按物料号 / 补库类型 / 状态（精确）筛选分页列表，默认按要求入库时间升序。"""
        if material_no is not None:
            material_no = str(material_no).strip()
            if material_no == "":
                material_no = None
        if replenish_type is not None:
            replenish_type = str(replenish_type).strip()
            if replenish_type == "":
                replenish_type = None
        if status is not None:
            status = str(status).strip()
            if status == "":
                status = None

        if replenish_type is not None and replenish_type not in self.VALID_REPLENISH_TYPES:
            raise FdeError("补库类型仅支持缺货/最低库存/安全库存补库")
        if status is not None and status not in self.VALID_STATUSES:
            raise FdeError("状态筛选不合法")

        clauses = []
        params = []

        if material_no is not None:
            clauses.append("material_no = ?")
            params.append(material_no)
        if replenish_type is not None:
            clauses.append("replenish_type = ?")
            params.append(replenish_type)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        select_sql = """
            SELECT replenish_no, material_no, replenish_type, replenish_qty, required_inbound, promised_inbound, status
            FROM demand_pool
        """ + where_sql + " ORDER BY required_inbound ASC, replenish_no ASC"

        rows = self.db.execute(select_sql, tuple(params)).fetchall()
        total = len(rows)

        if page is None and size is None:
            return {"items": [dict(r) for r in rows], "total": total}

        try:
            page_int = int(page) if page is not None else 1
            size_int = int(size) if size is not None else 20
        except (TypeError, ValueError):
            raise FdeError("分页参数不合法") from None

        if page_int < 1:
            raise FdeError("页码必须大于等于1")
        if size_int < 1:
            raise FdeError("每页条数必须大于等于1")

        start = (page_int - 1) * size_int
        items = [dict(r) for r in rows[start:start + size_int]]
        return {"items": items, "total": total}

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _clean_replenish_no(self, replenish_no):
        clean = "" if replenish_no is None else str(replenish_no).strip()
        if not clean:
            raise FdeError("补库单号不能为空")
        return clean

    def _clean_material_no(self, material_no):
        clean = "" if material_no is None else str(material_no).strip()
        if not clean:
            raise FdeError("物料号不能为空")
        return clean

    def _clean_replenish_type(self, replenish_type):
        clean = "" if replenish_type is None else str(replenish_type).strip()
        if clean not in self.VALID_REPLENISH_TYPES:
            raise FdeError("补库类型仅支持缺货/最低库存/安全库存补库")
        return clean

    def _clean_required_inbound(self, required_inbound):
        clean = "" if required_inbound is None else str(required_inbound).strip()
        if not clean:
            raise FdeError("要求入库时间不能为空")
        return clean

    def _clean_optional_date(self, value, label):
        clean = None if value is None else str(value).strip()
        if clean == "":
            clean = None
        return clean

    def _to_positive_qty(self, value):
        try:
            qty = float(value)
        except (TypeError, ValueError):
            raise FdeError("补库数量必须为数字") from None
        if qty <= 0:
            raise FdeError("补库数量必须大于0")
        return qty

    def _resolve_replenish_qty(self, replenish_type, replenish_qty, stock_on_hand,
                               min_level_a, safety_level_c, batch_level_b, tight):
        """BR-06 补货量分档：富余补到组批水位 B；紧张补到触发水位线（缺货补回 0）。"""
        sh = self._to_optional_number(stock_on_hand)
        # 富余：一次按组批量切线上足（补到组批水位 B）
        if not tight and batch_level_b is not None and sh is not None:
            return float(batch_level_b) - sh
        # 紧张：只补到触发的那条水位线
        if tight and sh is not None:
            if replenish_type == "缺货补库":
                return 0.0 - sh
            if replenish_type == "最低库存补库" and min_level_a is not None:
                return float(min_level_a) - sh
            if replenish_type == "安全库存补库" and min_level_a is not None and safety_level_c is not None:
                return float(min_level_a) + float(safety_level_c) - sh
        # 未提供水位线参数时，退回触发方传入的补货量
        return replenish_qty

    def _to_optional_number(self, value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _assert_material_exists(self, material_no):
        try:
            result = self.fde.call("md_material", "get", material_no=material_no)
        except FdeError:
            raise FdeError("物料记录不存在") from None
        except Exception:
            raise FdeError("物料校验失败") from None
        if not result:
            raise FdeError("物料记录不存在")

    def _get_record(self, replenish_no):
        row = self.db.execute(
            """
                SELECT replenish_no, material_no, replenish_type, replenish_qty, required_inbound, promised_inbound, status
                FROM demand_pool
                WHERE replenish_no = ?
            """,
            (replenish_no,),
        ).fetchone()
        if row is None:
            raise FdeError("补库单不存在")
        return dict(row)

    def _generate_replenish_no(self):
        prefix = "RP" + datetime.now().strftime("%Y%m%d")
        row = self.db.execute(
            "SELECT replenish_no FROM demand_pool WHERE replenish_no LIKE ? ORDER BY replenish_no DESC LIMIT 1",
            (prefix + "%",),
        ).fetchone()
        seq = 1
        if row is not None:
            try:
                seq = int(row["replenish_no"][len(prefix):]) + 1
            except ValueError:
                seq = 1
        for _ in range(100):
            candidate = prefix + str(seq).zfill(4)
            if self.db.execute(
                "SELECT 1 FROM demand_pool WHERE replenish_no = ?", (candidate,)
            ).fetchone() is None:
                return candidate
            seq += 1
        raise FdeError("补库单号生成失败，请重试")

    def _dispatch_to_erp(self, record):
        """外部系统适配器（出向）：下发生产计划给 ERP。真实接入时只换本实现，不动公共方法。"""
        return {
            "dispatched": True,
            "replenish_no": record["replenish_no"],
            "material_no": record["material_no"],
            "replenish_qty": record["replenish_qty"],
            "required_inbound": record["required_inbound"],
        }
