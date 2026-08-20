from fde import FdeError


class FcstProcessing:
    """预测加工聚合根。基线→各调整→独立需求，物料平铺，按版本管理。"""

    VALID_STATUSES = ("进行中", "全部核定", "已锁定")
    VALID_CHK_RESULTS = ("通过", "退回")
    VALID_ONETIME_TAGS = ("一次性", "大一次性", "断点")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS forecast_processing (
                fcst_version TEXT NOT NULL,
                oem_code TEXT NOT NULL,
                plant_code TEXT NOT NULL,
                part_no TEXT NOT NULL,
                period TEXT NOT NULL,
                project_no TEXT DEFAULT '',
                veh_model TEXT DEFAULT '',
                base_qty REAL NOT NULL DEFAULT 0,
                cust_qty REAL DEFAULT 0,
                conf_adj REAL NOT NULL DEFAULT 0,
                conf_reason TEXT DEFAULT '',
                trend_adj REAL NOT NULL DEFAULT 0,
                trend_reason TEXT DEFAULT '',
                onetime_adj REAL NOT NULL DEFAULT 0,
                onetime_reason TEXT DEFAULT '',
                onetime_tag TEXT DEFAULT '一次性',
                indep_qty REAL NOT NULL DEFAULT 0,
                chk_result TEXT DEFAULT '',
                chk_comment TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT '进行中' CHECK (status IN ('进行中', '全部核定', '已锁定')),
                owner TEXT DEFAULT '',
                PRIMARY KEY (fcst_version, oem_code, plant_code, part_no, period)
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_fp_chk ON forecast_processing (chk_result)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_fp_status ON forecast_processing (status)")

    def generate(self, fcst_version: str):
        """按版本自动生成加工行（从基线行集展开，一次版本一份）"""
        fcst_version = self._clean(fcst_version)
        if not fcst_version:
            raise FdeError("版本号必填")

        existing = self.db.execute(
            "SELECT COUNT(*) as cnt FROM forecast_processing WHERE fcst_version = ?", (fcst_version,)
        ).fetchone()
        if existing and existing["cnt"] > 0:
            raise FdeError(f"版本 {fcst_version} 已存在加工数据，每个版本仅一份")

        # 取基线行集
        try:
            base_items = self.fde.call("forecast_baseline", "list", fcst_version=fcst_version, page=1, page_size=10000)
            items = base_items.get("items", [])
        except FdeError:
            raise FdeError(f"取基线版本 {fcst_version} 数据失败") from None
        if not items:
            raise FdeError(f"基线版本 {fcst_version} 无数据，先生成基线")

        # 取快照构建客户预测值映射
        try:
            snap = self.fde.call("forecast_snapshot", "list", fcst_version=fcst_version, page=1, page_size=10000)
            snap_items = snap.get("items", [])
        except FdeError:
            snap_items = []

        snap_map = {}
        for s in snap_items:
            key = (s.get("oem_code", ""), s.get("plant_code", ""), s.get("part_no", ""), s.get("period", ""))
            snap_map[key] = s.get("orig_qty", 0) if s.get("data_flag") == "正常" else 0

        created = 0
        for item in items:
            oem_code = item.get("oem_code", "")
            plant_code = item.get("plant_code", "")
            part_no = item.get("part_no", "")
            period = item.get("period", "")
            project_no = item.get("project_no", "")
            veh_model = item.get("veh_model", "")
            base_qty = item.get("base_qty", 0) or 0
            key = (oem_code, plant_code, part_no, period)
            cust_qty = snap_map.get(key, 0)
            indep_qty = base_qty  # 初始 = 基线

            self.db.execute(
                "INSERT INTO forecast_processing (fcst_version, oem_code, plant_code, part_no, period, project_no, veh_model, base_qty, cust_qty, indep_qty, owner) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fcst_version, oem_code, plant_code, part_no, period, project_no, veh_model, base_qty, cust_qty or 0, indep_qty, self.ctx.get("userno", "")),
            )
            created += 1

        return {"fcst_version": fcst_version, "created": created}

    def fill_line(self, fcst_version: str, oem_code: str, plant_code: str, part_no: str, period: str,
                  conf_adj: float = None, conf_reason: str = None,
                  trend_adj: float = None, trend_reason: str = None,
                  onetime_adj: float = None, onetime_reason: str = None, onetime_tag: str = None):
        """填写调整"""
        row = self._get_row(fcst_version, oem_code, plant_code, part_no, period)
        if row["status"] == "已锁定":
            raise FdeError("版本已锁定，不可修改")

        updates, params = [], []
        if conf_adj is not None:
            updates.append("conf_adj = ?"); params.append(self._to_float(conf_adj))
            if conf_reason:
                updates.append("conf_reason = ?"); params.append(self._clean(conf_reason))
        if trend_adj is not None:
            updates.append("trend_adj = ?"); params.append(self._to_float(trend_adj))
            if trend_reason:
                updates.append("trend_reason = ?"); params.append(self._clean(trend_reason))
        if onetime_adj is not None:
            updates.append("onetime_adj = ?"); params.append(self._to_float(onetime_adj))
            if onetime_reason:
                updates.append("onetime_reason = ?"); params.append(self._clean(onetime_reason))
            tag = self._clean(onetime_tag) if onetime_tag else "一次性"
            if tag not in self.VALID_ONETIME_TAGS:
                raise FdeError(f"一次性标签只能为 {'/'.join(self.VALID_ONETIME_TAGS)}")
            updates.append("onetime_tag = ?"); params.append(tag)

        if updates:
            new_conf = conf_adj if conf_adj is not None else row["conf_adj"]
            new_trend = trend_adj if trend_adj is not None else row["trend_adj"]
            new_onetime = onetime_adj if onetime_adj is not None else row["onetime_adj"]
            indep_qty = round(row["base_qty"] + new_conf + new_trend + new_onetime, 2)
            updates.append("indep_qty = ?"); params.append(indep_qty)
            params.extend([fcst_version, oem_code, plant_code, part_no, period])
            self.db.execute(
                f"UPDATE forecast_processing SET {', '.join(updates)} WHERE fcst_version = ? AND oem_code = ? AND plant_code = ? AND part_no = ? AND period = ?",
                tuple(params),
            )
        return self.get(fcst_version, oem_code, plant_code, part_no, period)

    def review_line(self, fcst_version: str, oem_code: str, plant_code: str, part_no: str, period: str, chk_result: str, chk_comment: str = None):
        """核定/退回单行"""
        chk_result = self._clean(chk_result)
        if chk_result not in self.VALID_CHK_RESULTS:
            raise FdeError(f"核对结论只能为 {'/'.join(self.VALID_CHK_RESULTS)}")
        if chk_result == "退回" and not self._clean(chk_comment):
            raise FdeError("退回必须附理由")
        row = self._get_row(fcst_version, oem_code, plant_code, part_no, period)
        if row["status"] == "已锁定":
            raise FdeError("版本已锁定，不可核定")
        self.db.execute(
            "UPDATE forecast_processing SET chk_result = ?, chk_comment = ? WHERE fcst_version = ? AND oem_code = ? AND plant_code = ? AND part_no = ? AND period = ?",
            (chk_result, self._clean(chk_comment), fcst_version, oem_code, plant_code, part_no, period),
        )
        return self.get(fcst_version, oem_code, plant_code, part_no, period)

    def finalize(self, fcst_version: str):
        """全部核定→锁定"""
        rows = self.db.execute(
            "SELECT chk_result, COUNT(*) as cnt FROM forecast_processing WHERE fcst_version = ? GROUP BY chk_result",
            (fcst_version,),
        ).fetchall()
        if not rows:
            raise FdeError(f"版本 {fcst_version} 无加工数据")
        not_passed = sum(r["cnt"] for r in rows if r["chk_result"] != "通过")
        if not_passed > 0:
            raise FdeError(f"还有 {not_passed} 行未通过核定，无法锁定")
        self.db.execute(
            "UPDATE forecast_processing SET status = '已锁定' WHERE fcst_version = ?", (fcst_version,)
        )
        return {"fcst_version": fcst_version, "status": "已锁定"}

    def add_onetime_line(self, fcst_version: str, oem_code: str, plant_code: str, part_no: str, period: str,
                         onetime_adj: float, onetime_reason: str, onetime_tag: str = None):
        """月中附加一次性行（当期行，基线值为空）"""
        onetime_adj = self._to_float(onetime_adj)
        onetime_reason = self._clean(onetime_reason)
        if not onetime_reason:
            raise FdeError("一次性调整原因必填")
        tag = self._clean(onetime_tag) if onetime_tag else "一次性"
        if tag not in self.VALID_ONETIME_TAGS:
            raise FdeError(f"一次性标签只能为 {'/'.join(self.VALID_ONETIME_TAGS)}")

        existing = self._row(fcst_version, oem_code, plant_code, part_no, period)
        if existing:
            return self.fill_line(fcst_version, oem_code, plant_code, part_no, period,
                                  onetime_adj=onetime_adj, onetime_reason=onetime_reason, onetime_tag=tag)

        self.db.execute(
            "INSERT INTO forecast_processing (fcst_version, oem_code, plant_code, part_no, period, base_qty, cust_qty, conf_adj, trend_adj, onetime_adj, onetime_reason, onetime_tag, indep_qty) VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, ?, ?, ?, ?)",
            (fcst_version, oem_code, plant_code, part_no, period, onetime_adj, onetime_reason, tag, onetime_adj),
        )
        return self.get(fcst_version, oem_code, plant_code, part_no, period)

    def get(self, fcst_version: str, oem_code: str, plant_code: str, part_no: str, period: str):
        return dict(self._get_row(fcst_version, oem_code, plant_code, part_no, period))

    def get_version(self, fcst_version: str):
        """取版本全部行 + 汇总"""
        rows = self.db.execute(
            "SELECT fcst_version, oem_code, plant_code, part_no, period, project_no, veh_model, base_qty, cust_qty, conf_adj, conf_reason, trend_adj, trend_reason, onetime_adj, onetime_reason, onetime_tag, indep_qty, chk_result, chk_comment, status, owner FROM forecast_processing WHERE fcst_version = ? ORDER BY oem_code, plant_code, part_no, period",
            (fcst_version,),
        ).fetchall()
        if not rows:
            raise FdeError(f"版本 {fcst_version} 无加工数据")
        lines = [dict(r) for r in rows]
        statuses = set(r["status"] for r in rows)
        return {
            "fcst_version": fcst_version,
            "status": "已锁定" if statuses == {"已锁定"} else ("全部核定" if all(r["chk_result"] == "通过" for r in rows) else "进行中"),
            "line_count": len(lines),
            "owner": rows[0]["owner"],
            "lines": lines,
        }

    def list(self, fcst_version: str = None, oem_code: str = None, plant_code: str = None, part_no: str = None,
             period: str = None, chk_result: str = None, status: str = None, page: int = None, page_size: int = None):
        fcst_version = self._clean(fcst_version); oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code); part_no = self._clean(part_no)
        period = self._clean(period); chk_result = self._clean(chk_result); status = self._clean(status)
        if chk_result and chk_result not in self.VALID_CHK_RESULTS:
            raise FdeError("核对结论筛选不合法")
        if status and status not in self.VALID_STATUSES:
            raise FdeError("状态筛选不合法")

        sql = "SELECT fcst_version, oem_code, plant_code, part_no, period, project_no, veh_model, base_qty, cust_qty, conf_adj, conf_reason, trend_adj, trend_reason, onetime_adj, onetime_reason, onetime_tag, indep_qty, chk_result, chk_comment, status, owner FROM forecast_processing"
        clauses, params = [], []
        for col, val in [("fcst_version", fcst_version), ("oem_code", oem_code), ("plant_code", plant_code),
                         ("part_no", part_no), ("period", period), ("chk_result", chk_result), ("status", status)]:
            if val:
                clauses.append(f"{col} = ?"); params.append(val)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY fcst_version DESC, oem_code, plant_code, part_no, period"
        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [dict(r) for r in rows]
        total = len(items)
        if page is None and page_size is None:
            return {"total": total, "items": items}
        page_no = self._to_int(page, 1); page_sz = self._to_int(page_size, 50)
        if page_no < 1: page_no = 1
        if page_sz < 1: page_sz = 50
        start = (page_no - 1) * page_sz
        return {"total": total, "items": items[start:start + page_sz]}

    def list_versions(self, fcst_version: str = None, status: str = None, page: int = None, page_size: int = None):
        """按版本汇总（供列表页使用）"""
        fcst_version = self._clean(fcst_version); status = self._clean(status)
        if status and status not in self.VALID_STATUSES:
            raise FdeError("状态筛选不合法")

        sql = "SELECT fcst_version, status, owner, COUNT(*) as line_count, SUM(CASE WHEN chk_result='通过' THEN 1 ELSE 0 END) as reviewed, SUM(CASE WHEN chk_result='' THEN 1 ELSE 0 END) as pending FROM forecast_processing"
        clauses, params = [], []
        if fcst_version:
            clauses.append("fcst_version = ?"); params.append(fcst_version)
        if status:
            clauses.append("status = ?"); params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " GROUP BY fcst_version ORDER BY fcst_version DESC"
        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [dict(r) for r in rows]
        total = len(items)
        if page is None and page_size is None:
            return {"total": total, "items": items}
        page_no = self._to_int(page, 1); page_sz = self._to_int(page_size, 50)
        if page_no < 1: page_no = 1
        if page_sz < 1: page_sz = 50
        start = (page_no - 1) * page_sz
        return {"total": total, "items": items[start:start + page_sz]}

    def _clean(self, value):
        if value is None: return ""
        return str(value).strip()

    def _to_int(self, value, default):
        if value is None: return default
        if isinstance(value, str) and not value.strip(): return default
        try: return int(value)
        except (TypeError, ValueError): raise FdeError("分页参数非法")

    def _to_float(self, value, default=0):
        if value is None: return default
        try: return float(value)
        except (TypeError, ValueError): raise FdeError("数值参数非法")

    def _row(self, fcst_version, oem_code, plant_code, part_no, period):
        fcst_version = self._clean(fcst_version); oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code); part_no = self._clean(part_no); period = self._clean(period)
        return self.db.execute(
            "SELECT fcst_version, oem_code, plant_code, part_no, period, project_no, veh_model, base_qty, cust_qty, conf_adj, conf_reason, trend_adj, trend_reason, onetime_adj, onetime_reason, onetime_tag, indep_qty, chk_result, chk_comment, status, owner FROM forecast_processing WHERE fcst_version = ? AND oem_code = ? AND plant_code = ? AND part_no = ? AND period = ?",
            (fcst_version, oem_code, plant_code, part_no, period),
        ).fetchone()

    def _get_row(self, fcst_version, oem_code, plant_code, part_no, period):
        row = self._row(fcst_version, oem_code, plant_code, part_no, period)
        if row is None:
            raise FdeError(f"加工行不存在：{fcst_version}/{oem_code}/{plant_code}/{part_no}/{period}")
        return row
