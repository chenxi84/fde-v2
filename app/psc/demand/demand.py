from fde import FdeError
from typing import Optional


class Demand:
    """毛需求与净需求聚合根。

    把销售预测（sales_forecast.get_summary）与库存策略（inventory_strategy.get_water_level）
    合并为毛需求并发布冻结，再叠加未发订单、扣减当前库存与在途工单，运算出净需求。
    状态机随 md_monthly_version.lock_status 流转（草稿→发布（锁定）→冻结），本聚合无独立状态列。
    """

    ROLLING_MONTHS = ("N+1", "N+2", "N+3")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS demand (
                version_no      TEXT    NOT NULL,
                material_no     TEXT    NOT NULL,
                rolling_month   TEXT    NOT NULL,
                forecast_qty    REAL    NOT NULL DEFAULT 0,
                inventory_qty   REAL    NOT NULL DEFAULT 0,
                gross_qty       REAL    NOT NULL DEFAULT 0,
                open_order_qty  REAL    NOT NULL DEFAULT 0,
                onhand_qty      REAL    NOT NULL DEFAULT 0,
                in_transit_qty  REAL    NOT NULL DEFAULT 0,
                net_qty         REAL    NOT NULL DEFAULT 0,
                PRIMARY KEY (version_no, material_no, rolling_month)
            )
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_demand_material_no ON demand (material_no)"
        )

    # ---- 对外服务（公共方法） ----

    def build_gross(self, version_no: str):
        """合成毛需求：替换件/断点合并加工 + 叠加库存策略水位（期末 N+3）。幂等重算更新。"""
        version_no = self._clean_version_no(version_no)
        version = self._get_version(version_no)
        if version.get("lock_status") != "草稿":
            raise FdeError("版本已发布，不可合成")

        # 1. 销售预测汇总（物料级合计，通用件合并已在 get_summary 完成）
        summary = self._get_summary_rows(version_no)
        forecast = {}
        for row in summary:
            if not isinstance(row, dict):
                continue
            mat = str(row.get("material_no") or "").strip()
            rm = row.get("rolling_month")
            if not mat or rm not in self.ROLLING_MONTHS:
                continue
            qty = self._num(row.get("final_qty_sum"))
            forecast.setdefault(mat, {})[rm] = forecast.setdefault(mat, {}).get(rm, 0) + qty

        # 2. 替换件合并：old -> new，把 old 的预测合并到 new（全额转移）
        replace_map = {}
        for rel in self._get_replace_rows():
            old = str(rel.get("old_material_no") or "").strip()
            new = str(rel.get("new_material_no") or "").strip()
            if old and new and old != new:
                replace_map[old] = new
        for old, new in replace_map.items():
            if old in forecast:
                for rm, qty in forecast[old].items():
                    forecast.setdefault(new, {})[rm] = forecast.setdefault(new, {}).get(rm, 0) + qty
                forecast.pop(old, None)

        # 3. 断点处理：按 switch_time 归属（切换后需求归新件，切换前保留旧件）
        for bp in self._get_breakpoint_rows():
            old = str(bp.get("old_material_no") or "").strip()
            new = str(bp.get("new_material_no") or "").strip()
            switch_ym = self._parse_ym(bp.get("switch_time"))
            if not old or not new or old == new or not switch_ym or old not in forecast:
                continue
            for rm in list(forecast[old].keys()):
                rm_ym = self._rolling_to_ym(version_no, rm)
                if rm_ym and rm_ym >= switch_ym:
                    qty = forecast[old].pop(rm, 0)
                    forecast.setdefault(new, {})[rm] = forecast.setdefault(new, {}).get(rm, 0) + qty
            if not forecast[old]:
                forecast.pop(old, None)

        # 4. 叠加库存策略：每个滚动月度毛需求 = 销售预测 + 库存策略水位（N+1/N+2/N+3 同口径，
        #    净需求按期独立估算，未发/库存/在途按期静态扣减，不存在跨期累加），幂等写入/更新毛需求行
        for mat in sorted(forecast.keys()):
            water_level = self._get_water_level(version_no, mat)
            for rm in self.ROLLING_MONTHS:
                fq = self._num(forecast[mat].get(rm))
                iq = water_level
                gq = fq + iq
                self._upsert_gross(version_no, mat, rm, fq, iq, gq)

        return {
            "version_no": version_no,
            "material_count": len(forecast),
            "message": f"毛需求合成成功，共 {len(forecast)} 个物料",
        }

    def publish(self, version_no: str):
        """发布冻结毛需求：校验已合成，并联动 md_monthly_version.publish 锁定版本。"""
        version_no = self._clean_version_no(version_no)

        row = self.db.execute(
            "SELECT COUNT(*) AS c FROM demand WHERE version_no = ?", (version_no,)
        ).fetchone()
        if row is None or row["c"] == 0:
            raise FdeError("毛需求未合成，请先执行合成")

        try:
            self.fde.call("md_monthly_version", "publish", version_no=version_no)
        except FdeError as e:
            msg = str(e)
            if "草稿" in msg:
                raise FdeError("版本已发布，不可重复发布") from None
            raise FdeError(f"发布月度版本失败：{msg}") from None
        except Exception:
            raise FdeError("发布月度版本失败") from None

        return {"version_no": version_no, "message": "毛需求发布成功"}

    def calc_net(self, version_no: str):
        """运算净需求：net = gross + 未发 − 库存 − 在途，各层非负；联动 freeze 冻结版本。"""
        version_no = self._clean_version_no(version_no)
        version = self._get_version(version_no)
        if version.get("lock_status") == "草稿":
            raise FdeError("毛需求未发布冻结，不可运算净需求")
        if version.get("lock_status") == "冻结":
            raise FdeError("版本已冻结，不可重复运算净需求")

        open_orders = self._load_open_order(version_no)
        inventory = self._load_inventory(version_no)
        in_transit = self._load_in_transit(version_no)

        rows = self.db.execute(
            "SELECT material_no, rolling_month, gross_qty FROM demand WHERE version_no = ?",
            (version_no,),
        ).fetchall()
        for r in rows:
            mat = r["material_no"]
            rm = r["rolling_month"]
            gross = self._num(r["gross_qty"])
            if rm == "N+1":
                # 近期净额：当前未发/库存/在途已知，抵扣得净需求
                oo = self._num(open_orders.get(mat, 0))
                oh = self._num(inventory.get(mat, 0))
                it = self._num(in_transit.get(mat, 0))
                net = gross + oo - oh - it
                if net < 0:
                    net = 0
            else:
                # 远期毛额：N+2/N+3 库存/在途未知且当前库存已被近期预留，不扣减，净=毛
                oo = oh = it = 0
                net = gross
            self.db.execute(
                """
                    UPDATE demand
                    SET open_order_qty = ?, onhand_qty = ?, in_transit_qty = ?, net_qty = ?
                    WHERE version_no = ? AND material_no = ? AND rolling_month = ?
                """,
                (oo, oh, it, net, version_no, mat, rm),
            )

        try:
            self.fde.call("md_monthly_version", "freeze", version_no=version_no)
        except FdeError as e:
            raise FdeError(f"冻结月度版本失败：{e}") from None
        except Exception:
            raise FdeError("冻结月度版本失败") from None

        return {"version_no": version_no, "row_count": len(rows), "message": "净需求运算成功"}

    def get(self, version_no: str, material_no: str, rolling_month: str):
        """按 version_no + material_no + rolling_month 取单条毛需求/净需求详情（分层拆解）。"""
        version_no = self._clean_version_no(version_no)
        material_no = "" if material_no is None else str(material_no).strip()
        rolling_month = "" if rolling_month is None else str(rolling_month).strip()
        if not material_no:
            raise FdeError("物料号不能为空")
        if rolling_month not in self.ROLLING_MONTHS:
            raise FdeError("滚动月度只能为 N+1/N+2/N+3")

        row = self.db.execute(
            """
                SELECT version_no, material_no, rolling_month, forecast_qty, inventory_qty,
                       gross_qty, open_order_qty, onhand_qty, in_transit_qty, net_qty
                FROM demand
                WHERE version_no = ? AND material_no = ? AND rolling_month = ?
            """,
            (version_no, material_no, rolling_month),
        ).fetchone()
        if row is None:
            raise FdeError("记录不存在")
        return dict(row)

    def list(
        self,
        version_no: Optional[str] = None,
        material_no: Optional[str] = None,
        rolling_month: Optional[str] = None,
        page: Optional[int] = None,
        size: Optional[int] = None,
    ):
        """按版本/物料/滚动月度筛选毛需求与净需求分页列表。"""
        version_no = self._optional_str(version_no)
        material_no = self._optional_str(material_no)
        rolling_month = self._optional_str(rolling_month)
        if rolling_month is not None and rolling_month not in self.ROLLING_MONTHS:
            raise FdeError("滚动月度只能为 N+1/N+2/N+3")

        clauses = []
        params = []
        if version_no:
            clauses.append("version_no = ?")
            params.append(version_no)
        if material_no:
            clauses.append("material_no = ?")
            params.append(material_no)
        if rolling_month:
            clauses.append("rolling_month = ?")
            params.append(rolling_month)
        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        select_sql = """
            SELECT version_no, material_no, rolling_month, forecast_qty, inventory_qty,
                   gross_qty, open_order_qty, onhand_qty, in_transit_qty, net_qty
            FROM demand
        """ + where_sql + " ORDER BY version_no, material_no, rolling_month"

        rows = self.db.execute(select_sql, tuple(params)).fetchall()
        total = len(rows)

        if page is None and size is None:
            return {"items": [dict(r) for r in rows], "total": total}

        try:
            page_int = int(page) if page is not None else 1
            size_int = int(size) if size is not None else 20
        except (TypeError, ValueError):
            raise FdeError("分页参数不合法") from None
        if page_int < 1 or size_int < 1:
            raise FdeError("分页参数不合法") from None

        start = (page_int - 1) * size_int
        items = [dict(r) for r in rows[start:start + size_int]]
        return {"items": items, "total": total}

    def export_net(self, version_no: str):
        """导出某版本净需求清单（物料号/滚动月度/net_qty），供线下产能平衡。"""
        version_no = self._clean_version_no(version_no)
        version = self._get_version(version_no)
        if version.get("lock_status") != "冻结":
            raise FdeError("净需求未运算")

        rows = self.db.execute(
            """
                SELECT version_no, material_no, rolling_month, net_qty
                FROM demand
                WHERE version_no = ?
                ORDER BY material_no, rolling_month
            """,
            (version_no,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- 内部辅助（_ 前缀，不对外暴露） ----

    def _clean_version_no(self, version_no):
        v = "" if version_no is None else str(version_no).strip()
        if not v:
            raise FdeError("月度版本号不能为空")
        return v

    def _optional_str(self, value):
        if value is None:
            return None
        v = str(value).strip()
        return v if v else None

    def _num(self, value):
        if value is None or value == "":
            return 0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0

    def _get_version(self, version_no):
        try:
            version = self.fde.call("md_monthly_version", "get", version_no=version_no)
        except FdeError:
            raise FdeError("版本不存在") from None
        except Exception:
            raise FdeError("校验月度版本失败") from None
        if not version:
            raise FdeError("版本不存在")
        return version

    def _get_summary_rows(self, version_no):
        try:
            result = self.fde.call("sales_forecast", "get_summary", version_no=version_no)
        except FdeError as e:
            raise FdeError(f"销售预测汇总取数失败：{e}") from None
        except Exception:
            raise FdeError("销售预测汇总取数失败") from None
        if result is None:
            return []
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("items") or result.get("data") or result.get("rows") or result.get("list") or []
        return []

    def _get_water_level(self, version_no, material_no):
        # 无库存策略记录时按水位 0 处理（毛需求仅含预测），不阻断整版本合成
        try:
            wl = self.fde.call(
                "inventory_strategy", "get_water_level",
                version_no=version_no, material_no=material_no,
            )
        except FdeError:
            return 0
        except Exception:
            return 0
        if not isinstance(wl, dict):
            return 0
        return (
            self._num(wl.get("min_level"))
            + self._num(wl.get("safety_level"))
            + self._num(wl.get("batch_level"))
        )

    def _get_replace_rows(self):
        # 取生效替换关系（old -> new）；取不到时视为无替换关系，跳过合并
        try:
            result = self.fde.call("md_part_replace", "list", status="生效")
        except FdeError:
            return []
        except Exception:
            return []
        if isinstance(result, dict):
            result = result.get("items") or result.get("data") or result.get("rows") or result.get("list") or []
        if not isinstance(result, list):
            return []
        return result

    def _get_breakpoint_rows(self):
        # 取断点关系（old -> new，switch_time）；取不到时视为无断点，跳过处理
        try:
            result = self.fde.call("md_breakpoint", "list")
        except FdeError:
            return []
        except Exception:
            return []
        if isinstance(result, dict):
            result = result.get("items") or result.get("data") or result.get("rows") or result.get("list") or []
        if not isinstance(result, list):
            return []
        return result

    def _upsert_gross(self, version_no, material_no, rolling_month, forecast_qty, inventory_qty, gross_qty):
        row = self.db.execute(
            "SELECT 1 FROM demand WHERE version_no = ? AND material_no = ? AND rolling_month = ?",
            (version_no, material_no, rolling_month),
        ).fetchone()
        if row:
            self.db.execute(
                """
                    UPDATE demand
                    SET forecast_qty = ?, inventory_qty = ?, gross_qty = ?
                    WHERE version_no = ? AND material_no = ? AND rolling_month = ?
                """,
                (forecast_qty, inventory_qty, gross_qty, version_no, material_no, rolling_month),
            )
        else:
            self.db.execute(
                """
                    INSERT INTO demand (
                        version_no, material_no, rolling_month,
                        forecast_qty, inventory_qty, gross_qty,
                        open_order_qty, onhand_qty, in_transit_qty, net_qty
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
                """,
                (version_no, material_no, rolling_month, forecast_qty, inventory_qty, gross_qty),
            )

    def _parse_ym(self, switch_time):
        s = "" if switch_time is None else str(switch_time).strip()
        digits = "".join(ch for ch in s if ch.isdigit())
        return digits[:6] if len(digits) >= 6 else None

    def _rolling_to_ym(self, version_no, rolling_month):
        offset = {"N+1": 1, "N+2": 2, "N+3": 3}.get(rolling_month)
        if offset is None:
            return None
        v = str(version_no)
        if len(v) < 6:
            return None
        try:
            year = int(v[:4])
            month = int(v[4:6])
        except (TypeError, ValueError):
            return None
        total = year * 12 + (month - 1) + offset
        y = total // 12
        m = total % 12 + 1
        return f"{y:04d}{m:02d}"

    # ---- 外部系统适配器（stub，真实接入只换实现，不动公共方法） ----

    def _load_open_order(self, version_no):
        """ERP 未发订单（已接收未发运）。stub：真实接入时换实现，返回 {material_no: qty}。"""
        return {}

    def _load_inventory(self, version_no):
        """ERP 当前库存（自有仓 + 寄售仓）。stub：真实接入时换实现，返回 {material_no: qty}。"""
        return {}

    def _load_in_transit(self, version_no):
        """ERP 在途工单（在制/在途）。stub：真实接入时换实现，返回 {material_no: qty}。"""
        return {}
