from __future__ import annotations

from fde import FdeError
from typing import Optional
import re
from datetime import datetime


class StrategyFitting:
    """策略拟合聚合根：按物料滚动回测拟合最优预测方法与库存参数，
    结果先落表（待复核），人工复核通过后回填物料主数据（已生效）。"""

    VALID_STATUSES = ("待复核", "已生效", "已否决")

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
        series = self._load_sales_history(clean_material)
        history = [s["qty"] for s in series]
        periods = [s["period"] for s in series]

        # 响应窗口（天）= 生产 + 物流：预测误差 σ_L 的窗口 L = lead_days/30
        try:
            lead_days = float(material.get("prod_days") or 0) + float(material.get("logistics_days") or 0)
        except (TypeError, ValueError):
            lead_days = 0.0

        # 预测拟合（statsforecast 统计模型池回测，MASE 选 winner + 出预测值 + 响应窗口预测误差 σ_L）
        r = self._predict_fit(history, lead_days=lead_days, periods=periods)

        # 库存拟合（实际干净需求回放，BR-02/BR-11 约束优化）
        (service_factor, safety_level, batch_window,
         fulfill_rate, inv_days, changeover_cnt) = self._inventory_fit(history)

        import json
        detail_json = json.dumps(r["detail"], ensure_ascii=False)

        # 自动标记异常：候选为空（数据不足/拟合失败，预测方法留空）或 winner MASE >= 1（不比季节朴素强）
        _detail = r.get("detail") or {}
        _candidates = _detail.get("candidates") or []
        _mase = float(r.get("mase") or 0.0)
        abnormal_flag = 1 if (not _candidates or _mase >= 1.0) else 0

        # BR-13 拟合结果先落表 status=待复核，人工复核通过才回填
        values = (
            r["pred_method"], r["pred_params"], r["mase"], r["smape"],
            r["pred_qty"], r["pred_lo"], r["pred_hi"], r["sigma_l"], detail_json,
            service_factor, safety_level, batch_window,
            fulfill_rate, inv_days, changeover_cnt, abnormal_flag,
        )

        existing = self.db.execute(
            "SELECT 1 FROM strategy_fitting WHERE fit_version = ? AND material_no = ?",
            (clean_version, clean_material),
        ).fetchone()

        if existing is None:
            self.db.execute(
                """
                    INSERT INTO strategy_fitting (
                        material_no, fit_version, pred_method, pred_params, mase, smape,
                        pred_qty, pred_lo, pred_hi, sigma_l, detail_json,
                        service_factor, safety_level, batch_window,
                        fulfill_rate, inv_days, changeover_cnt, abnormal_flag, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '待复核')
                """,
                (clean_material, clean_version) + values,
            )
        else:
            # BR-01 幂等：同一 fit_version+material_no 重复拟合覆盖（重置为待复核）
            self.db.execute(
                """
                    UPDATE strategy_fitting SET
                        pred_method = ?, pred_params = ?, mase = ?, smape = ?,
                        pred_qty = ?, pred_lo = ?, pred_hi = ?, sigma_l = ?, detail_json = ?,
                        service_factor = ?, safety_level = ?, batch_window = ?,
                        fulfill_rate = ?, inv_days = ?, changeover_cnt = ?,
                        abnormal_flag = ?, status = '待复核'
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

    def get_latest(self, material_no: str):
        """取某物料最新一版拟合结果（按 fit_version 降序）。无拟合返回 None（不抛错）。"""
        clean_material = self._clean_material_no(material_no)
        row = self.db.execute(
            "SELECT material_no, fit_version, pred_method, pred_params, smape, "
            "mase, pred_qty, pred_lo, pred_hi, sigma_l, detail_json, "
            "service_factor, safety_level, batch_window, fulfill_rate, "
            "inv_days, changeover_cnt, abnormal_flag, status "
            "FROM strategy_fitting WHERE material_no = ? ORDER BY fit_version DESC LIMIT 1",
            (clean_material,),
        ).fetchone()
        if row is None:
            return None
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

        # BR-14 拟合异常（数据不足或 MASE≥1）强制人工二次确认
        if row["abnormal_flag"] and not confirm:
            raise FdeError("拟合异常（数据不足或 MASE≥1 不可预测），需人工二次确认")

        # BR-13/BR-15 复核通过才回填物料主数据（带版本记录，支持回滚）
        import json as _json
        model_blob = None
        try:
            _d = row["detail_json"]
            if _d:
                _d = _json.loads(_d) if isinstance(_d, str) else _d
                model_blob = _d.get("model_blob")
        except Exception:
            model_blob = None

        # 数据不足/拟合失败（pred_method 为空）时无方法可回填：跳过回填，仅登记复核结论，
        # 物料 base_method 保持为空，销售预测走「预测留空、以人工为准」路径。
        if row["pred_method"]:
            self.fde.call(
                "md_material", "set_fit_params",
                material_no=clean_material,
                base_method=row["pred_method"],
                base_params=row["pred_params"],
                batch_window=row["batch_window"],
                service_level=row["fulfill_rate"],
                fit_version=clean_version,
                model_blob=model_blob,
                sigma_l=row["sigma_l"] if "sigma_l" in row.keys() else None,
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
        """历史台账适配器（替代 V1 stub）：md_material.history_chain（前序链 ∪ 断点链）取链，
        再 history_series 近 periods 期（返回 [{period, qty}]，含期间标签供回测横轴）。
        失败/台账为空 → []（回测兜底不变），不改动公共方法。"""
        try:
            chain = self.fde.call("md_material", "history_chain", material_no=material_no)
            materials = chain if isinstance(chain, list) and chain else [material_no]
            series = self.fde.call("sales_history", "history_series",
                                   material_nos=materials, limit=periods)
            return series if isinstance(series, list) else []
        except FdeError:
            return []

    # ---- 预测拟合（statsforecast 统计模型池 + cross_validation 回测 + MASE 选 winner + predict）----

    _K_MIN = 12                # 常规模型最小训练窗口（Auto 模型 + MASE 季节性基线需 ≥12 期）
    _INTERMITTENT_K_MIN = 4    # 间歇模型最小训练窗口（Croston/TSB 不需季节性，可容忍更少历史）
    _RECENT_WINDOW = 6         # 近期窗口（趋势对比，用户自己判断）

    def _predict_fit(self, history, lead_days=0.0, periods=None):
        """预测拟合：statsforecast 统计模型池 + cross_validation 回测 + MASE 选 winner + predict。

        按历史非零占比分流（常规 AutoTheta/AutoARIMA/AutoETS，间歇 Croston/TSB）。
        常规需 ≥12 期，间歇需 ≥4 期；MASE 基线由库函数按 seasonality 从训练集计算
        （常规/长序列 = 季节性朴素 12，短间歇序列 = naive 1）。lead_days>0 时顺带算 σ_L。
        periods 为真实历史期间（YYYY-MM），用于回测横轴；缺失则回退"今天往前推"。
        返回 dict（pred_method/pred_params/mase/smape/pred_qty/pred_lo/pred_hi/sigma_l/detail）。"""
        import json
        import pandas as pd
        from statsforecast import StatsForecast
        from statsforecast.models import (AutoTheta, AutoARIMA, AutoETS,
                                          SeasonalNaive, CrostonOptimized, TSB)

        n = len(history)
        if n == 0:
            return self._default_result()

        # 分流先于门槛：间歇需求（非零占比 < 0.3）可容忍更少历史（Croston/TSB 不需季节性）
        nonzero_ratio = sum(1 for v in history if v > 0) / n
        intermittent = nonzero_ratio < 0.3
        if intermittent:
            k_min = self._INTERMITTENT_K_MIN
            # 短间歇序列（<12 期）无法算季节性朴素基线，退化为 naive（y[t−1]）作 MASE 标尺
            mase_seasonality = 12 if n >= 12 else 1
            models = [CrostonOptimized(), TSB(alpha_d=0.1, alpha_p=0.1)]
        else:
            k_min = self._K_MIN
            mase_seasonality = 12
            models = [AutoTheta(season_length=12), AutoARIMA(season_length=12),
                      AutoETS(season_length=12)]

        if n < k_min:
            return self._default_result()

        if periods and len(periods) == n:
            ds = pd.to_datetime(periods)  # 真实历史期间 YYYY-MM → 月初
        else:
            ds = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq="MS")
        df = pd.DataFrame({"unique_id": "M", "ds": ds, "y": history})

        # 回测窗口数自适应：短序列减少留出窗口，保证每个窗口有足够训练数据
        n_windows = max(1, min(3, n - k_min))
        sf = StatsForecast(models=models, freq="MS", n_jobs=1)
        try:
            cv = sf.cross_validation(h=1, df=df, n_windows=n_windows)
        except Exception:
            return self._default_result()
        if cv is None or cv.empty:
            return self._default_result()

        # MASE 用库版 utilsforecast.losses.mase：分母 = 训练集内 seasonal naive（或 naive）误差，
        # 教科书定义，比手写「MAE ÷ SeasonalNaive 的 CV 误差」口径更标准。逐模型取跨 cutoff 均值。
        from utilsforecast.losses import mase as _mase_loss
        import numpy as np
        model_names = [str(m) for m in models]
        mase_map = {}
        try:
            mase_df = _mase_loss(cv, models=model_names, seasonality=mase_seasonality, train_df=df)
            for name in model_names:
                if name not in mase_df.columns:
                    continue
                val = float(mase_df[name].mean())
                mase_map[name] = round(val, 4) if np.isfinite(val) else 0.0
        except Exception:
            mase_map = {}

        # MASE 基线（训练集内 seasonal naive / naive 误差），供详情展示/复核参考
        _scale = (df["y"].shift(mase_seasonality) - df["y"]).abs().dropna()
        base = float(_scale.mean()) if len(_scale) else 0.0

        candidates = []
        for m in models:
            name = str(m)
            if name not in cv.columns:
                continue
            preds = cv[name]
            actuals = cv["y"]
            smape_vals = []
            for p, a in zip(preds, actuals):
                if a <= 0:
                    continue
                denom = (abs(p) + a) / 2.0
                if denom <= 0:
                    continue
                smape_vals.append(abs(p - a) / denom)
            smape = round(sum(smape_vals) / len(smape_vals), 4) if smape_vals else 0.0
            steps = [{"period": str(row["ds"].date())[:7],
                      "pred": round(float(row[name]), 2), "actual": row["y"]}
                     for _, row in cv.iterrows()]
            _p = {"season_length": 12} if name in ("AutoTheta", "AutoARIMA", "AutoETS") else {}
            candidates.append({"method": name, "params": _p, "mase": mase_map.get(name, 0.0),
                               "smape": smape, "steps": steps})

        if not candidates:
            return self._default_result()

        candidates.sort(key=lambda c: c["mase"])
        best = candidates[0]

        # 全量历史拟合曲线：为每个候选模型做 in-sample 拟合，覆盖 CV 的末 3 个测试点为完整历史
        import numpy as np
        for c in candidates:
            try:
                m = self._make_model(c["method"])
                m.fit(np.array(history, dtype=np.float64))
                fits = m.predict_in_sample()
                fitted = (fits or {}).get("fitted") if isinstance(fits, dict) else None
                if fitted is None or len(fitted) != n:
                    continue
                steps = []
                for i in range(n):
                    v = fitted[i]
                    if v != v:  # 跳过 NaN（如首期拟合缺失）
                        continue
                    steps.append({
                        "period": (periods[i] if periods and len(periods) == n else str(ds[i].date())[:7]),
                        "actual": history[i],
                        "pred": round(float(v), 2),
                    })
                c["steps"] = steps
            except Exception:
                pass

        import base64
        import pickle
        import numpy as np
        pred_qty = pred_lo = pred_hi = None
        model_blob = None
        try:
            winner_model = self._make_model(best["method"])
            winner_model.fit(np.array(history, dtype=np.float64))
            fc = winner_model.predict(1, level=[80])
            pred_qty = round(float(fc["mean"][0]), 2)
            pred_lo = round(float(fc["lo-80"][0]), 2)
            pred_hi = round(float(fc["hi-80"][0]), 2)
            model_blob = base64.b64encode(pickle.dumps(winner_model)).decode()
        except Exception:
            pass

        # 响应窗口预测误差 σ_L：再跑 h=L 的 cross_validation，按 cutoff 累计误差取样本标准差
        sigma_l = self._forecast_error_sigma(history, lead_days, best["method"])

        detail = {
            "candidates": candidates, "winner": best["method"],
            "predict": {"qty": pred_qty, "lo": pred_lo, "hi": pred_hi},
            "model_blob": model_blob,
            "sigma_l": sigma_l,
            "mase_baseline": round(base, 2),
            "k_min": self._K_MIN, "recent_window": self._RECENT_WINDOW,
        }
        return {"pred_method": best["method"],
                "pred_params": json.dumps(best["params"], ensure_ascii=False),
                "mase": best["mase"], "smape": best["smape"],
                "pred_qty": pred_qty, "pred_lo": pred_lo, "pred_hi": pred_hi,
                "sigma_l": sigma_l,
                "detail": detail}

    @staticmethod
    def _make_model(method, season_length=12):
        """按 winner 方法名构造 statsforecast 模型实例（用于全量 refit + pickle 固化）。
        间歇模型（Croston/TSB）需显式传 prediction_intervals（共形区间），否则 predict(level=..) 抛异常。"""
        from statsforecast.models import (AutoTheta, AutoARIMA, AutoETS,
                                          SeasonalNaive, CrostonOptimized, TSB)
        from statsforecast.utils import ConformalIntervals
        if method == "AutoTheta":
            return AutoTheta(season_length=season_length)
        if method == "AutoARIMA":
            return AutoARIMA(season_length=season_length)
        if method == "AutoETS":
            return AutoETS(season_length=season_length)
        if method == "SeasonalNaive":
            return SeasonalNaive(season_length=season_length)
        if method == "CrostonOptimized":
            return CrostonOptimized(prediction_intervals=ConformalIntervals(h=1, n_windows=2))
        if method == "TSB":
            return TSB(alpha_d=0.1, alpha_p=0.1,
                       prediction_intervals=ConformalIntervals(h=1, n_windows=2))
        return None

    def _forecast_error_sigma(self, history, lead_days, method):
        """响应窗口预测误差 σ_L（L = lead_days/30 月）：再跑一次 cross_validation(h=L)，
        按 cutoff 累计「实际 − 预测」误差取样本标准差。L<1 时用 1 步误差 × L 缩放；
        历史不足 / 模型不支持 / 回测失败 → None（调用方回退历史口径）。"""
        if not history or lead_days <= 0 or len(history) < self._K_MIN:
            return None
        import pandas as pd
        from statsforecast import StatsForecast
        model = self._make_model(method)
        if model is None:
            return None
        L = lead_days / 30.0
        if L < 1.0:
            h, scale = 1, L
        else:
            h, scale = max(1, int(round(L))), 1.0
        ds = pd.date_range(end=pd.Timestamp.today().normalize(), periods=len(history), freq="MS")
        df = pd.DataFrame({"unique_id": "M", "ds": ds, "y": history})
        sf = StatsForecast(models=[model], freq="MS", n_jobs=1)
        try:
            cv = sf.cross_validation(h=h, df=df, n_windows=3)
        except Exception:
            return None
        if cv is None or cv.empty:
            return None
        name = str(model)
        if name not in cv.columns or "cutoff" not in cv.columns:
            return None
        errs = []
        for _, grp in cv.groupby("cutoff"):
            act = float(grp["y"].sum())
            pred = float(grp[name].sum())
            errs.append(act - pred)
        if len(errs) < 2:
            return None
        mean = sum(errs) / len(errs)
        var = sum((e - mean) ** 2 for e in errs) / (len(errs) - 1)
        return round((var ** 0.5) * scale, 4)

    def _default_result(self):
        # 数据不足/拟合失败：不产出方法（pred_method 留空），仅登记异常待复核，
        # 避免用「指数平滑」等占位名误导。强行通过时不回填 base_method（见 approve）。
        return {"pred_method": None, "pred_params": None,
                "mase": 0.0, "smape": 0.0,
                "pred_qty": None, "pred_lo": None, "pred_hi": None, "sigma_l": None,
                "detail": {"candidates": [], "k_min": self._K_MIN,
                           "recent_window": self._RECENT_WINDOW}}

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
            "mase, pred_qty, pred_lo, pred_hi, sigma_l, detail_json, "
            "service_factor, safety_level, batch_window, fulfill_rate, "
            "inv_days, changeover_cnt, abnormal_flag, status "
            "FROM strategy_fitting WHERE fit_version = ? AND material_no = ?",
            (fit_version, material_no),
        ).fetchone()

    def _to_dict(self, row):
        keys = row.keys()
        return {
            "material_no": row["material_no"],
            "fit_version": row["fit_version"],
            "pred_method": row["pred_method"],
            "pred_params": row["pred_params"],
            "smape": row["smape"],
            "mase": row["mase"] if "mase" in keys else None,
            "pred_qty": row["pred_qty"] if "pred_qty" in keys else None,
            "pred_lo": row["pred_lo"] if "pred_lo" in keys else None,
            "pred_hi": row["pred_hi"] if "pred_hi" in keys else None,
            "sigma_l": row["sigma_l"] if "sigma_l" in keys else None,
            "detail_json": row["detail_json"] if "detail_json" in keys else None,
            "service_factor": row["service_factor"],
            "safety_level": row["safety_level"],
            "batch_window": row["batch_window"],
            "fulfill_rate": row["fulfill_rate"],
            "inv_days": row["inv_days"],
            "changeover_cnt": row["changeover_cnt"],
            "abnormal_flag": bool(row["abnormal_flag"]),
            "status": row["status"],
        }
