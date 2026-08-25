from fde import FdeError
from typing import Optional
import re
from datetime import datetime


class StrategyFitting:
    """策略拟合聚合根：按物料滚动回测拟合最优预测方法与库存参数，
    结果先落表（待复核），人工复核通过后回填物料主数据（已生效）。"""

    VALID_STATUSES = ("待复核", "已生效", "已否决")
    VALID_PRED_METHODS = ("移动平均", "指数平滑", "阶跃检测", "借用参考")

    # ---- 生命周期（必选）：加载时由平台调用，幂等建表 ----
    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS strategy_fitting (
                material_no     TEXT NOT NULL,
                fit_version     TEXT NOT NULL,
                pred_method     TEXT,
                pred_params     TEXT,
                smape           REAL,
                service_factor  REAL,
                safety_level    REAL,
                batch_window    REAL,
                fulfill_rate    REAL,
                inv_days        REAL,
                changeover_cnt  INTEGER,
                abnormal_flag   INTEGER NOT NULL DEFAULT 0,
                status          TEXT NOT NULL DEFAULT '待复核'
                    CHECK (status IN ('待复核', '已生效', '已否决')),
                PRIMARY KEY (fit_version, material_no)
            )
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_strategy_fitting_status ON strategy_fitting (status)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_strategy_fitting_material_no ON strategy_fitting (material_no)"
        )

    # ---- 对外服务（公共方法）----

    def run(self, material_no: str, fit_version: str):
        """对指定物料发起一次策略拟合（预测拟合 + 库存拟合），结果落表（待复核）。"""
        clean_material = self._clean_material_no(material_no)
        clean_version = self._clean_fit_version(fit_version)

        # BR-17 主数据引用铁律：run 前经 md_material.get 校验物料存在
        try:
            material = self.fde.call("md_material", "get", material_no=clean_material)
        except FdeError:
            raise FdeError("物料不存在") from None
        except Exception:
            raise FdeError("物料不存在") from None
        if not material:
            raise FdeError("物料不存在")

        # 历史干净需求（ERP 外部适配器；BR-19 剔除一次性脉冲）
        history = self._load_sales_history(clean_material)

        # 预测拟合（BR-02 与库存拟合解耦）
        pred_method, pred_params, smape = self._predict_fit(history)

        # 库存拟合（实际干净需求回放，BR-02/BR-11 约束优化）
        (service_factor, safety_level, batch_window,
         fulfill_rate, inv_days, changeover_cnt) = self._inventory_fit(history)

        # BR-13 拟合结果先落表 status=待复核，人工复核通过才回填
        values = (
            pred_method, pred_params, smape, service_factor, safety_level,
            batch_window, fulfill_rate, inv_days, changeover_cnt,
        )

        existing = self.db.execute(
            "SELECT 1 FROM strategy_fitting WHERE fit_version = ? AND material_no = ?",
            (clean_version, clean_material),
        ).fetchone()

        if existing is None:
            self.db.execute(
                """
                    INSERT INTO strategy_fitting (
                        material_no, fit_version, pred_method, pred_params, smape,
                        service_factor, safety_level, batch_window, fulfill_rate,
                        inv_days, changeover_cnt, abnormal_flag, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '待复核')
                """,
                (clean_material, clean_version) + values,
            )
        else:
            # BR-01 幂等：同一 fit_version+material_no 重复拟合覆盖（重置为待复核）
            self.db.execute(
                """
                    UPDATE strategy_fitting SET
                        pred_method = ?, pred_params = ?, smape = ?,
                        service_factor = ?, safety_level = ?, batch_window = ?,
                        fulfill_rate = ?, inv_days = ?, changeover_cnt = ?,
                        abnormal_flag = 0, status = '待复核'
                    WHERE fit_version = ? AND material_no = ?
                """,
                values + (clean_version, clean_material),
            )

        return self.get(clean_version, clean_material)

    def run_batch(self, fit_version: str = None):
        """整批拟合：按 fit_version 对全部正常状态物料逐物料拟合（简化同步实现）。

        fit_version 缺省/为空时自动取当前年月（YYYYMM），前端批量弹窗亦预填当月。"""
        if fit_version is None or str(fit_version).strip() == "":
            fit_version = datetime.now().strftime("%Y%m")
        clean_version = self._clean_fit_version(fit_version)

        try:
            result = self.fde.call("md_material", "list", status="正常")
        except FdeError:
            raise FdeError("物料列表获取失败") from None

        if isinstance(result, dict):
            materials = result.get("items", []) or []
        else:
            materials = result or []

        summary = {
            "fit_version": clean_version,
            "total": 0,
            "success": 0,
            "failed": 0,
            "errors": [],
        }
        for m in materials:
            material_no = m.get("material_no") if isinstance(m, dict) else None
            if not material_no:
                continue
            summary["total"] += 1
            try:
                self.run(material_no=material_no, fit_version=clean_version)
                summary["success"] += 1
            except FdeError as e:
                summary["failed"] += 1
                summary["errors"].append({"material_no": material_no, "error": str(e)})
        return summary

    def get(self, fit_version: str, material_no: str):
        """查看单条拟合结果完整字段。"""
        clean_version = self._clean_fit_version(fit_version)
        clean_material = self._clean_material_no(material_no)
        row = self._get_row(clean_version, clean_material)
        if row is None:
            raise FdeError("拟合结果不存在")
        return self._to_dict(row)

    def list(
        self,
        material_no: Optional[str] = None,
        fit_version: Optional[str] = None,
        status: Optional[str] = None,
        abnormal_flag: Optional[bool] = None,
        page: Optional[int] = None,
        size: Optional[int] = None,
    ):
        """按物料号（模糊）/拟合版本/状态/异常标记筛选分页列表。"""
        if material_no is not None:
            material_no = str(material_no).strip()
            if material_no == "":
                material_no = None
        if fit_version is not None:
            fit_version = str(fit_version).strip()
            if fit_version == "":
                fit_version = None
        if status is not None:
            status = str(status).strip()
            if status == "":
                status = None
        if abnormal_flag is not None:
            abnormal_flag = self._to_bool(abnormal_flag)

        if status is not None and status not in self.VALID_STATUSES:
            raise FdeError("状态筛选不合法")

        clauses = []
        params = []

        if material_no is not None:
            clauses.append("material_no LIKE ?")
            params.append("%" + material_no + "%")
        if fit_version is not None:
            clauses.append("fit_version = ?")
            params.append(fit_version)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if abnormal_flag is not None:
            clauses.append("abnormal_flag = ?")
            params.append(1 if abnormal_flag else 0)

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        select_sql = """
            SELECT material_no, fit_version, pred_method, pred_params, smape,
                   service_factor, safety_level, batch_window, fulfill_rate,
                   inv_days, changeover_cnt, abnormal_flag, status
            FROM strategy_fitting
        """ + where_sql + " ORDER BY fit_version DESC, material_no ASC"

        rows = self.db.execute(select_sql, tuple(params)).fetchall()
        items = [self._to_dict(r) for r in rows]
        total = len(items)

        if page is None and size is None:
            return {"items": items, "total": total}

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
        return {"items": items[start:start + size_int], "total": total}

    def approve(self, fit_version: str, material_no: str, confirm: Optional[bool] = False):
        """复核通过：待复核 → 已生效，并回填物料主数据（带版本）。"""
        clean_version = self._clean_fit_version(fit_version)
        clean_material = self._clean_material_no(material_no)
        row = self._get_row(clean_version, clean_material)
        if row is None:
            raise FdeError("拟合结果不存在")

        # BR-16 状态机：仅待复核可 approve
        if row["status"] != "待复核":
            raise FdeError("仅待复核状态可生效")

        # BR-14 参数跳变过大强制人工二次确认
        if row["abnormal_flag"] and not confirm:
            raise FdeError("参数跳变过大，需人工确认")

        # BR-13/BR-15 复核通过才回填物料主数据（带版本记录，支持回滚）
        self.fde.call(
            "md_material", "set_fit_params",
            material_no=clean_material,
            base_method=row["pred_method"],
            base_params=row["pred_params"],
            batch_window=row["batch_window"],
            service_level=row["fulfill_rate"],
            fit_version=clean_version,
        )

        self.db.execute(
            "UPDATE strategy_fitting SET status = '已生效' WHERE fit_version = ? AND material_no = ?",
            (clean_version, clean_material),
        )
        return self.get(clean_version, clean_material)

    def reject(self, fit_version: str, material_no: str):
        """否决：待复核 → 已否决，不回填物料主数据。"""
        clean_version = self._clean_fit_version(fit_version)
        clean_material = self._clean_material_no(material_no)
        row = self._get_row(clean_version, clean_material)
        if row is None:
            raise FdeError("拟合结果不存在")

        # BR-16 状态机：仅待复核可否决
        if row["status"] != "待复核":
            raise FdeError("仅待复核状态可否决")

        self.db.execute(
            "UPDATE strategy_fitting SET status = '已否决' WHERE fit_version = ? AND material_no = ?",
            (clean_version, clean_material),
        )
        return self.get(clean_version, clean_material)

    def rollback(self, fit_version: str, material_no: str):
        """回滚：已生效 → 已否决（本版作废），并回填上一版参数。"""
        clean_version = self._clean_fit_version(fit_version)
        clean_material = self._clean_material_no(material_no)
        row = self._get_row(clean_version, clean_material)
        if row is None:
            raise FdeError("拟合结果不存在")

        # BR-16 状态机：仅已生效可回滚
        if row["status"] != "已生效":
            raise FdeError("仅已生效状态可回滚")

        # 定位上一版已生效参数（历史回填记录）
        prev = self.db.execute(
            "SELECT material_no, fit_version, pred_method, pred_params, smape, "
            "service_factor, safety_level, batch_window, fulfill_rate, "
            "inv_days, changeover_cnt, abnormal_flag, status "
            "FROM strategy_fitting "
            "WHERE material_no = ? AND fit_version < ? AND status = '已生效' "
            "ORDER BY fit_version DESC LIMIT 1",
            (clean_material, clean_version),
        ).fetchone()

        if prev is None:
            raise FdeError("无上一版参数可回滚")

        # BR-15 回填上一版参数
        self.fde.call(
            "md_material", "set_fit_params",
            material_no=clean_material,
            base_method=prev["pred_method"],
            base_params=prev["pred_params"],
            batch_window=prev["batch_window"],
            service_level=prev["fulfill_rate"],
            fit_version=prev["fit_version"],
        )

        # 本记录作废（已否决）
        self.db.execute(
            "UPDATE strategy_fitting SET status = '已否决' WHERE fit_version = ? AND material_no = ?",
            (clean_version, clean_material),
        )
        return self.get(clean_version, clean_material)

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _load_sales_history(self, material_no, periods=24):
        """历史台账适配器（替代 V1 stub）：委托 sales_history.history_sequence 近 periods 期。
        失败/台账为空 → []（回测兜底不变），不改动公共方法。"""
        try:
            seq = self.fde.call("sales_history", "history_sequence",
                                material_nos=[material_no], limit=periods)
            return seq if isinstance(seq, list) else []
        except FdeError:
            return []

    def _predict_fit(self, history):
        """预测拟合（简化）：取默认方法/参数（指数平滑），sMAPE 用历史均值差计算。

        完整实现为遍历方法×参数网格滚动回测（Walk-Forward）选 sMAPE 最小者
        （BR-03/BR-04/BR-05/BR-06）；此处按简化约定取默认组合。"""
        pred_method = "指数平滑"
        pred_params = '{"alpha": 0.3, "trend": false}'
        if not history:
            return pred_method, pred_params, 0.0

        mean = sum(history) / len(history)
        total = 0.0
        cnt = 0
        for d in history:
            if d <= 0:
                continue
            denom = (abs(mean) + d) / 2.0
            if denom <= 0:
                continue
            total += abs(mean - d) / denom
            cnt += 1
        smape = round(total / cnt, 4) if cnt else 0.0
        return pred_method, pred_params, smape

    def _inventory_fit(self, history):
        """库存拟合（简化）：取默认组合（服务系数 1.65、组批窗口 28 天 = 4 周）。

        完整实现为遍历服务系数×组批窗口，在满足率≥目标约束下选成本最小者
        （BR-08/BR-09/BR-10/BR-11/BR-12）；此处按简化约定取默认组合。"""
        service_factor = 1.65
        batch_window = 28.0
        fulfill_rate = 0.95
        safety_level = 0.0
        inv_days = 0.0
        changeover_cnt = 0

        if history:
            mean = sum(history) / len(history)
            std = (sum((d - mean) ** 2 for d in history) / len(history)) ** 0.5
            safety_level = round(service_factor * std, 2)
            daily = mean / 30.0
            inv_days = round(batch_window + (safety_level / daily if daily > 0 else 0.0), 2)
            changeover_cnt = max(1, len(history) // 4)

        return service_factor, safety_level, batch_window, fulfill_rate, inv_days, changeover_cnt

    def _clean_material_no(self, material_no):
        clean = "" if material_no is None else str(material_no).strip()
        if not clean:
            raise FdeError("物料号不能为空")
        return clean

    def _clean_fit_version(self, fit_version):
        clean = "" if fit_version is None else str(fit_version).strip()
        if not clean:
            raise FdeError("拟合版本不能为空")
        if not re.fullmatch(r"\d{6}", clean):
            raise FdeError("拟合版本格式必须为 YYYYMM")
        month = int(clean[4:6])
        if month < 1 or month > 12:
            raise FdeError("拟合版本格式必须为 YYYYMM")
        return clean

    def _to_bool(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y", "是")
        if value is None:
            return None
        return bool(value)

    def _get_row(self, fit_version, material_no):
        return self.db.execute(
            "SELECT material_no, fit_version, pred_method, pred_params, smape, "
            "service_factor, safety_level, batch_window, fulfill_rate, "
            "inv_days, changeover_cnt, abnormal_flag, status "
            "FROM strategy_fitting WHERE fit_version = ? AND material_no = ?",
            (fit_version, material_no),
        ).fetchone()

    def _to_dict(self, row):
        return {
            "material_no": row["material_no"],
            "fit_version": row["fit_version"],
            "pred_method": row["pred_method"],
            "pred_params": row["pred_params"],
            "smape": row["smape"],
            "service_factor": row["service_factor"],
            "safety_level": row["safety_level"],
            "batch_window": row["batch_window"],
            "fulfill_rate": row["fulfill_rate"],
            "inv_days": row["inv_days"],
            "changeover_cnt": row["changeover_cnt"],
            "abnormal_flag": bool(row["abnormal_flag"]),
            "status": row["status"],
        }
