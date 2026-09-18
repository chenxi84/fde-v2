from __future__ import annotations

from fde import FdeError
from typing import Optional
from datetime import datetime, timedelta


class InventoryProjection:
    """库存推移表聚合根（预警引擎）。

    逐日推演未来 3 个月的库存水位（balance），对照库存策略三层水位（A/C/B）
    产出缺货 / 击穿最低 / 击穿安全 / 超储预警，并在击穿水位时触发需求池补库。
    数据来源类型为「自动参考创建」，前端只读，不提供创建 / 编辑 / 删除入口。
    """

    ALERT_TYPES = ("无", "缺货", "击穿最低", "击穿安全", "呆滞", "超储")
    BREACH_ALERT_TYPES = ("缺货", "击穿最低", "击穿安全")
    PROJECTION_DAYS = 90

    def refresh(self, material_no: str, biz_date: str, opening_stock: Optional[float] = None):
        """对单个物料逐日推演未来 3 个月库存水位并落盘（含预警标记）。"""
        material_no = self._clean(material_no)
        if not material_no:
            raise FdeError("物料号不能为空")

        start_date = self._parse_date(biz_date)
        if start_date is None:
            raise FdeError("推演起始日期格式非法，应为 YYYY-MM-DD")

        version_no = self._version_no_from_date(start_date)

        if opening_stock is None:
            opening_stock = self._load_inventory(material_no)
        opening_stock = self._to_number(opening_stock, 0)

        outbound_by_date = self._collect_outbound(material_no)
        water = self._load_water_level(version_no, material_no)
        if water is None:
            # fail-closed：没有水位策略就**不推演**，而不是产出一张「全标无预警」的表。
            # 静默降级踩过一次：biz_date 传成当天 → 推出的版本（当月）没有水位策略
            # （策略按版本开库日算）→ 623 行全标「无」，而余额已经负到 -1357，
            # 调用方看不到任何异常，还以为「没有缺料风险」。
            raise FdeError(
                f"未找到版本 {version_no} 的库存水位策略（物料 {material_no}）：无法判定预警，"
                f"推演已中止。请先执行 inventory_strategy.calc_batch(version_no=\"{version_no}\")；"
                f"若该版本不对，请核对 biz_date —— 按 {start_date.strftime('%Y-%m-%d')} "
                f"推出的是 {version_no}，而水位策略一般是按版本开库日（当月 1 日）算的"
            )

        dates = self._generate_dates(start_date, self.PROJECTION_DAYS)
        start_str = dates[0].strftime("%Y-%m-%d")
        end_exclusive = (dates[-1] + timedelta(days=1)).strftime("%Y-%m-%d")

        # 预计入库量在**窗口首日已知之后**才收集 —— 因为它要把**过期补库单钳到首日**（BR-04 口径变更，
        # 见 `_collect_inbound` 的说明）。放在 fail-closed 水位校验之后，保证"拒绝推演时一行不写"。
        inbound_by_date, overdue_inbound = self._collect_inbound(version_no, material_no, start_str)

        # 重算 start 及之后的全部未来行（清除旧推演残留，避免多窗口拼接出现"无入出库但余额跳变"的缝），
        # 保留已结束日期（biz_date < start）的历史快照（BR-11：隐藏不删除）。
        self.db.execute(
            "DELETE FROM inventory_projection WHERE material_no = ? AND biz_date >= ?",
            (material_no, start_str),
        )

        balance = opening_stock
        rows = []
        for d in dates:
            date_str = d.strftime("%Y-%m-%d")
            inbound = inbound_by_date.get(date_str, 0)
            outbound = outbound_by_date.get(date_str, 0)
            balance = balance + inbound - outbound
            alert_type = self._classify_alert(balance, water)
            self.db.execute(
                """
                    INSERT INTO inventory_projection (material_no, biz_date, inbound_qty, outbound_qty, balance, alert_type)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                (material_no, date_str, inbound, outbound, balance, alert_type),
            )
            rows.append({
                "material_no": material_no,
                "biz_date": date_str,
                "inbound_qty": inbound,
                "outbound_qty": outbound,
                "balance": balance,
                "alert_type": alert_type,
            })

        return {
            "material_no": material_no,
            "biz_date": start_str,
            "version_no": version_no,
            "opening_stock": opening_stock,
            "generated": len(rows),
            "rows": rows,
            # 过期补库单**明确报出**（BR-04 口径：钳到窗口首日计入，但不静默 —— 见 `_collect_inbound`）
            "overdue_inbound": overdue_inbound,
        }

    def refresh_batch(self, biz_date: Optional[str] = None, material_nos=None):
        """整批刷新全量物料推移表，并在刷新后联动预警扫描（击穿自动创建需求池补库单）。
        biz_date 缺省为当天；material_nos 缺省为全量「正常」状态物料。"""
        biz_date = self._clean(biz_date)
        if not biz_date:
            biz_date = datetime.now().strftime("%Y-%m-%d")
        start_date = self._parse_date(biz_date)
        if start_date is None:
            raise FdeError("推演起始日期格式非法，应为 YYYY-MM-DD")

        if material_nos is None:
            material_nos = self._load_active_materials()
        if not material_nos:
            raise FdeError("无可推演物料，请先确认物料主数据")

        total = len(material_nos)
        success = 0
        success_materials = []
        errors = []
        alert_errors = []
        overdue_inbound = []
        replenishments = []

        for m in material_nos:
            m = self._clean(m)
            try:
                res = self.refresh(m, biz_date)
            except FdeError as e:
                errors.append({"material_no": m, "message": str(e)})
                continue
            success += 1
            success_materials.append(m)
            # 过期补库单逐物料汇总报出（BR-04 口径：钳到窗口首日计入、但不静默，见 `_collect_inbound`）
            for item in (res.get("overdue_inbound") or []):
                overdue_inbound.append({"material_no": m, **item})
            # 逐物料独立：单物料预警失败不阻断整批。
            # ⚠ **但不得静默吞掉**（2026-09-17 补）：此前这里只写 `except FdeError: pass` ——
            # 于是「有击穿、却建不出补库单」这件事**一个字都不留**。实测（2026-10-01 演示数据）
            # `BYD-HAN-FB25/FB26` 正是这样：余额 0 击穿最低、算出补库量 ≤ 0、`create` 抛
            # 「补库数量必须大于0」，而调用方看到的是 `fail=0`、空错误、空补库单。
            # 与 `errors`（**推演**失败的物料）分开报，因为两者的处置不同：
            # 推演失败 → 该物料无推移数据；扫描/建单失败 → 有数据但**预警没落地**。
            try:
                result = self.scan_alert(m)
                replenishments.extend(result.get("replenishments") or [])
            except FdeError as e:
                alert_errors.append({"material_no": m, "message": str(e)})

        return {
            "total": total,
            "success": success,
            "fail": total - success,
            "success_materials": success_materials,
            "errors": errors,
            "alert_errors": alert_errors,
            "overdue_inbound": overdue_inbound,
            "replenishments": replenishments,
        }

    def get(self, material_no: str, biz_date: str):
        """按物料号 + 日期查询单日推移明细。"""
        material_no = self._clean(material_no)
        if not material_no:
            raise FdeError("物料号不能为空")
        biz_date = self._clean(biz_date)
        if not biz_date:
            raise FdeError("日期不能为空")

        row = self.db.execute(
            """
                SELECT material_no, biz_date, inbound_qty, outbound_qty, balance, alert_type
                FROM inventory_projection
                WHERE material_no = ? AND biz_date = ?
            """,
            (material_no, biz_date),
        ).fetchone()

        if row is None:
            raise FdeError("推移记录不存在")
        return self._to_dict(row)

    def list(
        self,
        material_no: Optional[str] = None,
        biz_date: Optional[str] = None,
        alert_type: Optional[str] = None,
        page: int = None,
        size: int = None,
    ):
        """按物料号 / 日期 / 预警类型筛选推移表列表，支持分页。
        默认日期升序（从早到晚）且从当天开始显示（BR-11：biz_date<今日的历史快照隐藏不删除）；
        选定具体日期（含历史日期）时精确回看该日。"""
        material_no = self._clean(material_no) or None
        biz_date = self._clean(biz_date) or None
        alert_type = self._clean(alert_type) or None

        if alert_type is not None and alert_type not in self.ALERT_TYPES:
            raise FdeError("预警类型筛选不合法")

        clauses = []
        params = []
        if material_no is not None:
            clauses.append("material_no = ?")
            params.append(material_no)
        if biz_date is not None:
            clauses.append("biz_date = ?")
            params.append(biz_date)
        else:
            # 未选日期：隐藏历史快照（biz_date < 今日），从当天开始显示
            clauses.append("biz_date >= ?")
            params.append(datetime.now().strftime("%Y-%m-%d"))
        if alert_type is not None:
            clauses.append("alert_type = ?")
            params.append(alert_type)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        select_sql = """
            SELECT material_no, biz_date, inbound_qty, outbound_qty, balance, alert_type
            FROM inventory_projection
        """ + where_sql + " ORDER BY biz_date ASC, material_no ASC"   # 从早到晚：首页即当天起的水位走势

        rows = self.db.execute(select_sql, tuple(params)).fetchall()
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

    def scan_alert(self, material_no: str, version_no: Optional[str] = None):
        """对照水位线扫描某物料推移表，回填 alert_type，击穿水位触发需求池补库。"""
        material_no = self._clean(material_no)
        if not material_no:
            raise FdeError("物料号不能为空")

        if version_no is None:
            version_no = self._infer_version_no(material_no)
        water = self._load_water_level(version_no, material_no)
        if water is None:
            raise FdeError("库存策略记录不存在，无法扫描预警")

        rows = self.db.execute(
            """
                SELECT material_no, biz_date, inbound_qty, outbound_qty, balance, alert_type
                FROM inventory_projection
                WHERE material_no = ?
                ORDER BY biz_date ASC
            """,
            (material_no,),
        ).fetchall()

        if not rows:
            raise FdeError("该物料暂无库存推移记录，请先执行刷新")

        breach_count = 0
        breach_row = None
        for row in rows:
            balance = self._to_number(row["balance"], 0)
            alert_type = self._classify_alert(balance, water)
            self.db.execute(
                "UPDATE inventory_projection SET alert_type = ? WHERE material_no = ? AND biz_date = ?",
                (alert_type, material_no, row["biz_date"]),
            )
            if alert_type in self.BREACH_ALERT_TYPES:
                breach_count += 1
                if breach_row is None:
                    breach_row = {
                        "biz_date": row["biz_date"],
                        "balance": balance,
                        "alert_type": alert_type,
                    }

        replenishments = []
        if breach_row is not None:
            replenish_type = self._replenish_type(breach_row["alert_type"])
            replenish_qty = self._replenish_qty(breach_row["alert_type"], breach_row["balance"], water)
            if replenish_qty > 0:
                # ⚠ 水位入参**必须传**（2026-09-17 按 B-08 补接线）：`demand_pool._resolve_replenish_qty`
                # 的 BR-06 分档（富余→补到组批水位 B / 紧张→补到触发线）一直是对的，但此前这里
                # **只传了 `replenish_qty`**，于是它最后一行「未提供水位线参数时退回触发方传入的补货量」
                # **无条件命中** ⇒ 生产上永远只补到触发线（实测 16 张单补到 B 的 **0** 张），
                # 补库量系统性偏小 ⇒ 补货更频繁 ⇒ 切线更多，而**这正是 BR-06 要避免的**，
                # 且全程静默（单量看着合理、界面无提示）。水位与击穿余额本就在手，只是没往下传。
                #
                # 产能松紧**不传**：按 BR-07 走 demand_pool 自己的默认（默认富余）。
                created = self.fde.call(
                    "demand_pool", "create",
                    material_no=material_no,
                    replenish_type=replenish_type,
                    replenish_qty=replenish_qty,
                    required_inbound=breach_row["biz_date"],
                    stock_on_hand=breach_row["balance"],
                    min_level_a=water["min_level"],
                    safety_level_c=water["safety_level"],
                    batch_level_b=water["batch_level"],
                )
                replenishments.append(created)

        return {
            "material_no": material_no,
            "version_no": version_no,
            "scanned": len(rows),
            "breach_count": breach_count,
            "replenishments": replenishments,
        }

    # ---- ERP 适配器（stub，真实接入时只换实现）----

    def _load_inventory(self, material_no):
        """取 ERP 自有仓成品库存总额（起始库存锚点）。stub 返回 0，真实接入换实现。"""
        return 0

    # 注：曾有 `_load_in_transit`（取 ERP 已下工单）—— 已于 2026-09-15 删除。
    # 它声明了语义却**全仓没有调用点**，是旧口径的化石：本应用的「在途」按 BR-04 指的是
    # **需求池未完成补库单**（`_collect_inbound` 走 `demand_pool.list`），而 ERP 在途工单
    # 是 demand 的 BR-07 扣减口径 —— **同一个词在两个应用里指两个不同的东西**。
    # 术语冲突已记入《应用详设》与 `宣传/待办.md` 第 5 项（本体 a) 的同名不同义校验）。

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _collect_inbound(self, version_no, material_no, window_start=None):
        """预计入库量 = 主计划月度需求（集中最迟入库日）+ 需求池「待下达/已下达/生产中」单据
        （按承诺入库日，无承诺则用要求入库日；纳入待下达避免重复下单）。

        返回 `(inbound_by_date, overdue)`：`overdue` 是**入库日早于推演窗口首日**的补库单明细。

        ⚠ **过期补库单钳到窗口首日**（2026-09-17 按已定口径实施）：推演只统计窗口内 `[首日, 首日+90天]`
        的日期，而一张「要求入库日已过、但仍未下达」的补库单，其入库日落在窗口**之前** ⇒
        `inbound_by_date.get(date_str, 0)` 永远取不到它 ⇒ **对余额零贡献**（旧行为：收集了却
        **静默丢掉**）。后果是连锁的：该物料在推演里永远等不到这笔货 → 持续击穿 → `scan_alert`
        **再建一张单**（`demand_pool` 无去重）→ 单越滚越多。
        口径（已定）：**按「尽快到货」算，钳到窗口首日** —— 这与 BR-04「待下达也要算进来（避免重复下单）」
        的初衷一致；同时在返回值里**明确报出**该单已过期，而不是静默丢。

        为什么**主计划**的最迟入库日不跟着钳：主计划的月度需求若属**已过去的月份**，
        那批货按业务上应已到货（已体现在起始库存里）—— 再钳到首日会**重复计入**。
        补库单不同：它在「待下达/已下达/生产中」三态里，**货还没到**，只是要求的日子过了。
        """
        inbound_by_date = {}
        overdue = []
        plan_rows = self.fde.call(
            "master_plan", "get_latest", version_no=version_no, material_no=material_no
        ) or []
        for row in plan_rows:
            if not isinstance(row, dict):
                continue
            inbound_date = row.get("latest_inbound_date")
            qty = self._to_number(row.get("plan_qty"), 0)
            if inbound_date:
                key = str(inbound_date)
                inbound_by_date[key] = inbound_by_date.get(key, 0) + qty

        for status in ("待下达", "已下达", "生产中"):
            try:
                pool = self.fde.call("demand_pool", "list",
                                     material_no=material_no, status=status) or {}
            except FdeError:
                continue
            for row in (pool.get("items") if isinstance(pool, dict) else pool) or []:
                if not isinstance(row, dict):
                    continue
                inbound_date = row.get("promised_inbound") or row.get("required_inbound")
                qty = self._to_number(row.get("replenish_qty"), 0)
                if not inbound_date:
                    continue
                key = str(inbound_date)
                if window_start and key < window_start:
                    overdue.append({
                        "replenish_no": row.get("replenish_no"),
                        "status": row.get("status"),
                        "inbound_date": key,
                        "replenish_qty": qty,
                        "clamped_to": window_start,
                        "message": f"补库单 {row.get('replenish_no')}（{row.get('status')}）的入库日 {key} "
                                   f"已早于推演窗口首日 {window_start}，按「尽快到货」钳到窗口首日计入",
                    })
                    key = window_start
                inbound_by_date[key] = inbound_by_date.get(key, 0) + qty
        return inbound_by_date, overdue

    def _collect_outbound(self, material_no):
        """预计出库量 = 出库计划「待出库」单据按计划出库日期合计
        （已关闭计划不计入；关闭后延期恢复待出库会重新进入推演）。"""
        outbound_by_date = {}
        try:
            plans = self.fde.call("outbound_plan", "list",
                                  material_no=material_no, status="待出库") or {}
        except FdeError:
            return outbound_by_date
        for row in (plans.get("items") if isinstance(plans, dict) else plans) or []:
            if not isinstance(row, dict):
                continue
            outbound_date = row.get("out_date")
            qty = self._to_number(row.get("qty"), 0)
            if outbound_date:
                key = str(outbound_date)
                outbound_by_date[key] = outbound_by_date.get(key, 0) + qty
        return outbound_by_date

    def _load_water_level(self, version_no, material_no):
        """取三层水位 A/C/B；无策略记录时返回 None（视为不可预警）。"""
        try:
            water = self.fde.call(
                "inventory_strategy", "get_water_level", version_no=version_no, material_no=material_no
            )
        except FdeError:
            return None
        if not isinstance(water, dict):
            return None
        return {
            "min_level": self._to_number(water.get("min_level"), 0),
            "safety_level": self._to_number(water.get("safety_level"), 0),
            "batch_level": self._to_number(water.get("batch_level"), 0),
        }

    def _classify_alert(self, balance, water):
        """对照水位带判定预警级别（BR-08）。呆滞阈值 BRD 未定义，暂不产出。

        阈值取**水位带**：下限 = A+C（补货触发线），上限 = **A+C+B**（组批封顶线）。

        ⚠ **超储的阈值是「上限」A+C+B，不是裸 `B`**（2026-09-17 订正，B-10）：
        实现此前写的是 `balance > b`，与正本 `inventory_strategy` 的 **BR-10**
        （「上限（组批封顶线）= A + C + B；高于上限即超储」）**互相矛盾**，
        而前端画的水位带用的正是 `A+C+B`（`get_water_level` 的 `upper`）——
        **预警与同一屏上的带子说的不是一回事**。
        对库存对冲件差别很小（RB26：`>898` vs `>968`），所以一直没暴露；
        对**速度对冲件**（BR-12 规定 C=B=0）则退化成 `>0` ⇒ **手上有货就报超储**：
        实测演示环境 279 行「超储」里有 **159 行**是 `BYD-HAN-FB25/FB26` 的误报。
        """
        if not water:
            return "无"
        a = water["min_level"]
        c = water["safety_level"]
        b = water["batch_level"]
        if balance < 0:
            return "缺货"
        if balance < a:
            return "击穿最低"
        if balance < a + c:
            return "击穿安全"
        if balance > a + c + b:
            return "超储"
        return "无"

    def _replenish_type(self, alert_type):
        return {
            "缺货": "缺货补库",
            "击穿最低": "最低库存补库",
            "击穿安全": "安全库存补库",
        }.get(alert_type, "缺货补库")

    def _replenish_qty(self, alert_type, balance, water):
        """补库量 = 补回触发水位线的缺口（**产能紧张基线**）。

        产能富余时补到组批水位 B —— 那一段由 `demand_pool._resolve_replenish_qty` 按 BR-06 分档，
        触发方（`scan_alert`）负责把水位与击穿余额**传下去**（2026-09-17 补的接线，见 create 调用处）。
        本方法算出的值只作为「水位入参缺失」时的兜底。
        """
        a = water["min_level"]
        c = water["safety_level"]
        if alert_type == "缺货":
            target = 0
        elif alert_type == "击穿最低":
            target = a
        elif alert_type == "击穿安全":
            target = a + c
        else:
            return 0
        return max(0, round(target - balance, 6))

    def _load_active_materials(self):
        """从物料主数据取「正常」状态物料作为推演范围（主数据引用铁律）。"""
        try:
            result = self.fde.call("md_material", "list", status="正常")
        except FdeError:
            return []
        if isinstance(result, dict):
            items = result.get("items") or []
        elif isinstance(result, list):
            items = result
        else:
            items = []
        return [str(item["material_no"]) for item in items if isinstance(item, dict) and item.get("material_no")]

    def _infer_version_no(self, material_no):
        row = self.db.execute(
            "SELECT MIN(biz_date) AS min_date FROM inventory_projection WHERE material_no = ?",
            (material_no,),
        ).fetchone()
        if row is None or not row["min_date"]:
            raise FdeError("该物料暂无库存推移记录，请先执行刷新")
        dt = self._parse_date(row["min_date"])
        if dt is None:
            raise FdeError("推移记录日期格式非法")
        return self._version_no_from_date(dt)

    def _parse_date(self, value):
        s = self._clean(value)
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    def _version_no_from_date(self, dt):
        return dt.strftime("%Y%m")

    def _generate_dates(self, start, days):
        return [start + timedelta(days=i) for i in range(days)]

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _to_number(self, value, default=0):
        if value is None or value == "":
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _to_int(self, value, default):
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise FdeError("分页参数不合法") from None

    def _to_dict(self, row):
        return {
            "material_no": row["material_no"],
            "biz_date": row["biz_date"],
            "inbound_qty": row["inbound_qty"],
            "outbound_qty": row["outbound_qty"],
            "balance": row["balance"],
            "alert_type": row["alert_type"],
        }
