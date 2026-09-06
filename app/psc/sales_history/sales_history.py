from __future__ import annotations

from fde import FdeError
import re


class SalesHistory:
    """历史台账（物料销售历史）聚合根。物料×客户×月度粒度的历史干净需求，
    由 ERP 冗余回写（import_batch 批量 / upsert 单条）。数据来源类型：自动参考创建
    ——无 create 服务，前端无手工创建入口。
    对外投影：history_sequence（按期升序聚合数量序列，支持断点链多物料按期求和、缺期补 0）
    与 purchasing_customers（历史采购客户集），供预测/库存/拟合消费。"""

    _PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

    # 显式声明可配置的外部适配器（供 /integration 发现；其余 _ 方法均为内部辅助）
    _EXTERNAL_ADAPTERS = ("_http_fetch_sales_history",)

    def upsert(self, material_no: str, customer_no: str, period: str, qty):
        """ERP 单条回写：同 物料+客户+期间 存在则覆盖 qty，不存在则插入（幂等）。"""
        material_no = self._require(material_no, "物料号")
        customer_no = self._require(customer_no, "客户编码")
        period = self._period(period)
        qty = self._qty(qty)
        forecast = self._pull_forecast(material_no, customer_no, period)

        existing = self.db.execute(
            "SELECT 1 FROM sales_history WHERE material_no = ? AND customer_no = ? AND period = ?",
            (material_no, customer_no, period),
        ).fetchone()
        if existing:
            self.db.execute(
                "UPDATE sales_history SET qty = ?, forecast_qty = ? "
                "WHERE material_no = ? AND customer_no = ? AND period = ?",
                (qty, forecast, material_no, customer_no, period),
            )
        else:
            self.db.execute(
                "INSERT INTO sales_history (material_no, customer_no, period, qty, forecast_qty) "
                "VALUES (?, ?, ?, ?, ?)",
                (material_no, customer_no, period, qty, forecast),
            )
        return {"material_no": material_no, "customer_no": customer_no, "period": period,
                "qty": qty, "forecast_qty": forecast}

    def import_batch(self, rows: list):
        """批量导入（upsert 语义）：逐行校验，合法行入库，失败行返回错误明细，不阻断其余行。"""
        if not isinstance(rows, (list, tuple)):
            raise FdeError("导入数据必须为列表")

        total, success, errors = len(rows), 0, []
        for i, row in enumerate(rows, start=1):
            try:
                if not isinstance(row, dict):
                    errors.append({"row": i, "field": "", "message": "行数据格式非法"})
                    continue
                material_no = self._clean(row.get("material_no"))
                if not material_no:
                    errors.append({"row": i, "field": "material_no", "message": "物料号不能为空"})
                    continue
                customer_no = self._clean(row.get("customer_no"))
                if not customer_no:
                    errors.append({"row": i, "field": "customer_no", "message": "客户编码不能为空"})
                    continue
                try:
                    period = self._period(row.get("period"))
                except FdeError as e:
                    errors.append({"row": i, "field": "period", "message": str(e)})
                    continue
                try:
                    qty = self._qty(row.get("qty"))
                except FdeError as e:
                    errors.append({"row": i, "field": "qty", "message": str(e)})
                    continue
                self.upsert(material_no, customer_no, period, qty)
                success += 1
            except FdeError as e:
                errors.append({"row": i, "field": "", "message": str(e)})
        return {"total": total, "success": success, "fail": len(errors), "errors": errors}

    def sync_external_history(self):
        """对外服务：拉取外部历史台账接口并经 import_batch 落库（供定时任务 / Agent 调用）。

        内部委托给 `_http_fetch_sales_history` 外部适配器（其 URL / 鉴权由 /integration 配置）。
        """
        return self._http_fetch_sales_history()

    # ---- 外部接口适配（CONVENTION §7.3：_<系统>_<操作>，供 /integration 发现与配置）----

    # 外部字段 → 内部字段（外部接口字段名与内部不一致时改这里）
    _EXTERNAL_FIELD_MAP = {
        "material_no": "material_no",
        "customer_no": "customer_no",
        "period": "period",
        "qty": "qty",
        "forecast_qty": "forecast_qty",
    }

    def _http_fetch_sales_history(self):
        """外部系统适配器：从外部历史台账接口拉取数据并经 import_batch 落库。

        目标 URL / 鉴权由 /integration 配置提供（get_endpoint）；本方法负责：调外部接口 →
        解析 JSON → 字段映射 → import_batch 落库 → 记日志。未配置或启用 Mock 时给出明确提示。
        """
        from fde_platform import integration

        ep = integration.get_endpoint("psc/sales_history", "_http_fetch_sales_history")
        if not ep:
            raise FdeError("外部历史台账接口未配置（请先到 /integration 配置目标 URL）")
        if ep.get("mock_enabled"):
            return {"status": "mock", "imported": 0, "message": "Mock 已启用，跳过真实调用"}

        url = (ep.get("url") or "").strip()
        if not url:
            raise FdeError("外部接口未配置 URL")

        body = self._do_http_call(ep, url)
        rows = self._parse_external_rows(body)
        result = self.import_batch(rows)

        integration.log_call(
            "psc/sales_history", "_http_fetch_sales_history",
            ep.get("target", "external"), f"{ep.get('http_method', 'GET')} {url}",
            "success", 0,
            response_summary=f"导入 {result.get('success', 0)}/{result.get('total', 0)} 行",
        )
        return result

    def _do_http_call(self, ep, url):
        """按集成配置发 HTTP 请求（含鉴权），返回响应正文文本；配置方法 404/405 时自动改 GET 探测。"""
        import urllib.error
        import urllib.request

        def _send(method):
            req = urllib.request.Request(url, method=method)
            req.add_header("Content-Type", ep.get("content_type", "application/json"))
            for k, v in (ep.get("extra_headers") or {}).items():
                req.add_header(k, v)
            auth_type = ep.get("auth_type", "none")
            cred = ep.get("auth_credential") or ""
            param_name = ep.get("auth_param_name") or ""
            if auth_type == "basic" and cred:
                import base64
                req.add_header("Authorization", f"Basic {base64.b64encode(cred.encode()).decode()}")
            elif auth_type == "bearer" and cred:
                req.add_header("Authorization", f"Bearer {cred}")
            elif auth_type == "apikey_header" and param_name and cred:
                req.add_header(param_name, cred)
            elif auth_type == "apikey_query":
                sep = "&" if "?" in url else "?"
                req = urllib.request.Request(url + f"{sep}{param_name}={cred}", method=method)
            resp = urllib.request.urlopen(req, timeout=ep.get("timeout_s", 30))
            return resp.read().decode("utf-8", errors="replace")

        configured = ep.get("http_method", "GET")
        try:
            return _send(configured)
        except urllib.error.HTTPError as e:
            if e.code in (404, 405) and configured.upper() != "GET":
                return _send("GET")
            raise

    def _parse_external_rows(self, body):
        """解析外部响应：支持 [...] 或 {rows|data|items:[...]} 结构，逐行字段映射。"""
        import json

        data = json.loads(body)
        raw = None
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            for key in ("rows", "data", "items"):
                if isinstance(data.get(key), list):
                    raw = data[key]
                    break
        if raw is None:
            raise FdeError("外部接口返回结构不符合预期（应为列表或 {rows|data|items:[...]}）")
        return [self._map_external_row(r) for r in raw if isinstance(r, dict)]

    def _map_external_row(self, raw):
        """外部字段 → 内部字段（字段名映射见 _EXTERNAL_FIELD_MAP）。"""
        return {internal: raw[external]
                for external, internal in self._EXTERNAL_FIELD_MAP.items()
                if external in raw}

    # ---- 读服务 ----

    def list(self, material_no: str = None, customer_no: str = None, period: str = None,
             page: int = None, size: int = None):
        """按物料/客户/期间（精确、AND、可选）筛选台账分页列表 {items, total}。"""
        material_no = self._clean(material_no)
        customer_no = self._clean(customer_no)
        period = self._clean(period)

        sql = "SELECT material_no, customer_no, period, qty, forecast_qty FROM sales_history"
        clauses, params = [], []
        if material_no:
            clauses.append("material_no = ?")
            params.append(material_no)
        if customer_no:
            clauses.append("customer_no = ?")
            params.append(customer_no)
        if period:
            clauses.append("period = ?")
            params.append(period)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY period, material_no, customer_no"

        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [self._to_dict(r) for r in rows]
        total = len(items)

        if page is None and size is None:
            return {"items": items, "total": total}

        page_no = self._to_int(page, 1)
        size_n = self._to_int(size, 20)
        if page_no < 1:
            page_no = 1
        if size_n < 1:
            size_n = 20
        start = (page_no - 1) * size_n
        return {"items": items[start:start + size_n], "total": total}

    def history_sequence(self, material_nos=None, customer_no: str = None, limit: int = None):
        """消费方投影：按 period 升序返回干净需求数量序列（数字列表）。
        material_nos 支持单物料（str）或断点链（list 旧→新）：链内各物料按期 SUM；
        期间缺口补 0（保证消费方期间连续语义）；limit 取末尾 N 期。"""
        materials = self._materials(material_nos)
        if not materials:
            return []
        customer_no = self._clean(customer_no)

        ph = ",".join("?" * len(materials))
        sql = "SELECT period, SUM(qty) AS qty FROM sales_history WHERE material_no IN (" + ph + ")"
        params = list(materials)
        if customer_no:
            sql += " AND customer_no = ?"
            params.append(customer_no)
        sql += " GROUP BY period ORDER BY period ASC"

        rows = self.db.execute(sql, tuple(params)).fetchall()
        if not rows:
            return []

        by_period = {r["period"]: (r["qty"] or 0.0) for r in rows}
        seq, p, last = [], min(by_period), max(by_period)
        while p <= last:
            seq.append(by_period.get(p, 0.0))
            p = self._next_month(p)

        n = self._limit_int(limit)
        if n:
            seq = seq[-n:]
        return seq

    def history_series(self, material_nos=None, customer_no: str = None, limit: int = None):
        """与 history_sequence 同口径，但返回 [{period, qty}]（含期间标签）。
        供策略拟合回测横轴使用——history_sequence 只给数量、丢期间，此处补期间语义。"""
        materials = self._materials(material_nos)
        if not materials:
            return []
        customer_no = self._clean(customer_no)

        ph = ",".join("?" * len(materials))
        sql = "SELECT period, SUM(qty) AS qty FROM sales_history WHERE material_no IN (" + ph + ")"
        params = list(materials)
        if customer_no:
            sql += " AND customer_no = ?"
            params.append(customer_no)
        sql += " GROUP BY period ORDER BY period ASC"

        rows = self.db.execute(sql, tuple(params)).fetchall()
        if not rows:
            return []

        by_period = {r["period"]: (r["qty"] or 0.0) for r in rows}
        out, p, last = [], min(by_period), max(by_period)
        while p <= last:
            out.append({"period": p, "qty": by_period.get(p, 0.0)})
            p = self._next_month(p)

        n = self._limit_int(limit)
        if n:
            out = out[-n:]
        return out

    def purchasing_customers(self, material_no: str = None):
        """历史采购客户集（去重升序，可按物料收窄），供销售预测清单客户维度。"""
        material_no = self._clean(material_no)
        if material_no:
            rows = self.db.execute(
                "SELECT DISTINCT customer_no FROM sales_history WHERE material_no = ? ORDER BY customer_no",
                (material_no,),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT DISTINCT customer_no FROM sales_history ORDER BY customer_no"
            ).fetchall()
        return [r["customer_no"] for r in rows]

    def attach_forecast(self, material_no: str, customer_no: str, period: str, qty):
        """预测侧推送：把 N+1 原始预测写入对应台账行的 forecast_qty。
        仅当该 (物料,客户,期间) 实际行已存在时更新；否则跳过（实际写入时再拉取兜底）。"""
        material_no = self._require(material_no, "物料号")
        customer_no = self._require(customer_no, "客户编码")
        period = self._period(period)
        forecast = None if qty is None else self._qty(qty)

        existing = self.db.execute(
            "SELECT 1 FROM sales_history WHERE material_no = ? AND customer_no = ? AND period = ?",
            (material_no, customer_no, period),
        ).fetchone()
        if not existing:
            return {"attached": False, "material_no": material_no,
                    "customer_no": customer_no, "period": period}
        self.db.execute(
            "UPDATE sales_history SET forecast_qty = ? WHERE material_no = ? AND customer_no = ? AND period = ?",
            (forecast, material_no, customer_no, period),
        )
        return {"attached": True, "material_no": material_no,
                "customer_no": customer_no, "period": period, "forecast_qty": forecast}

    def sync_forecast(self):
        """批量回填 forecast_qty：按 (物料,客户) 拉销售预测 N+1 原始预测，按期对齐更新存量台账行。"""
        rows = self.db.execute(
            "SELECT material_no, customer_no, period FROM sales_history"
        ).fetchall()
        pairs = {}
        for r in rows:
            pairs.setdefault((r["material_no"], r["customer_no"]), []).append(r["period"])

        updated = 0
        for (material_no, customer_no), periods in sorted(pairs.items()):
            try:
                fc = self.fde.call("sales_forecast", "customer_forecast_history",
                                   material_no=material_no, customer_no=customer_no)
            except FdeError:
                continue
            fmap = {f.get("period"): f.get("orig_qty") for f in (fc or [])}
            for p in periods:
                if p in fmap:
                    self.db.execute(
                        "UPDATE sales_history SET forecast_qty = ? "
                        "WHERE material_no = ? AND customer_no = ? AND period = ?",
                        (fmap[p], material_no, customer_no, p),
                    )
                    updated += 1
        return {"updated": updated}

    # ---- 内部辅助（_ 前缀，不对外暴露）----

    def _pull_forecast(self, material_no, customer_no, period):
        """拉取该 (物料,客户,期间) 的 N+1 原始预测；无则 None。"""
        try:
            rows = self.fde.call("sales_forecast", "customer_forecast_history",
                                 material_no=material_no, customer_no=customer_no)
        except FdeError:
            return None
        for r in rows or []:
            if r.get("period") == period:
                return r.get("orig_qty")
        return None


    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _require(self, value, label):
        v = self._clean(value)
        if not v:
            raise FdeError(f"{label}不能为空")
        return v

    def _period(self, value):
        v = self._clean(value)
        if not self._PERIOD_RE.match(v):
            raise FdeError("期间格式必须为 YYYY-MM")
        return v

    def _qty(self, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            raise FdeError("数量不能为空")
        if isinstance(value, bool):
            raise FdeError("数量必须为数值")
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise FdeError("数量必须为数值")
        if f < 0:
            raise FdeError("数量不能为负")
        return f

    def _materials(self, material_nos):
        if material_nos is None:
            return []
        if isinstance(material_nos, str):
            v = material_nos.strip()
            return [v] if v else []
        if isinstance(material_nos, (list, tuple)):
            out, seen = [], set()
            for m in material_nos:
                v = self._clean(m)
                if v and v not in seen:
                    seen.add(v)
                    out.append(v)
            return out
        raise FdeError("material_nos 须为物料号或物料号列表")

    def _limit_int(self, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise FdeError("limit 非法")
        if n < 1:
            raise FdeError("limit 非法")
        return n

    def _to_int(self, value, default):
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise FdeError("分页参数非法")

    def _next_month(self, period):
        y, m = int(period[:4]), int(period[5:7])
        m += 1
        if m > 12:
            y, m = y + 1, 1
        return f"{y:04d}-{m:02d}"

    def _to_dict(self, row):
        return {
            "material_no": row["material_no"],
            "customer_no": row["customer_no"],
            "period": row["period"],
            "qty": row["qty"],
            "forecast_qty": row["forecast_qty"],
        }
