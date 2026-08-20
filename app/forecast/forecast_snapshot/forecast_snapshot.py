from fde import FdeError


class FcstSnapshot:
    """预测快照聚合根。客户 N+1~N+3 月度滚动预测的唯一入口，版本化管理、行不可变。"""

    VALID_DATA_FLAGS = ("正常", "OEM未提供")
    VALID_SOURCE_CHANNELS = ("EDI", "OEM门户", "邮件Excel", "销售转录")

    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS forecast_snapshot (
                fcst_version TEXT NOT NULL,
                oem_code TEXT NOT NULL,
                plant_code TEXT NOT NULL,
                part_no TEXT NOT NULL,
                period TEXT NOT NULL,
                offset TEXT DEFAULT '',
                project_no TEXT DEFAULT '',
                veh_model TEXT DEFAULT '',
                orig_qty REAL NOT NULL DEFAULT 0,
                data_flag TEXT NOT NULL DEFAULT 'OEM未提供' CHECK (data_flag IN ('正常', 'OEM未提供')),
                source_channel TEXT DEFAULT '销售转录',
                recv_date TEXT DEFAULT '',
                collector TEXT DEFAULT '',
                PRIMARY KEY (fcst_version, oem_code, plant_code, part_no, period)
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_fs_version ON forecast_snapshot (fcst_version)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_fs_oem ON forecast_snapshot (oem_code, plant_code)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_fs_part ON forecast_snapshot (part_no)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_fs_period ON forecast_snapshot (period)")

    def open_version(self, fcst_version: str):
        """月度 opening：按活跃零件集自动生成 N+1~N+3 三行（均标记"未提供"）"""
        fcst_version = self._clean(fcst_version)
        if not fcst_version:
            raise FdeError("版本号必填，不能为空")
        # 校验版本存在且活跃
        try:
            ver = self.fde.call("md_fcst_version", "get", fcst_version=fcst_version)
        except FdeError:
            raise FdeError(f"月度版本 {fcst_version} 不存在，请先在 md_fcst_version 创建") from None
        if ver.get("status") != "活跃":
            raise FdeError(f"版本 {fcst_version} 非活跃状态，无法 opening")

        # 检查是否已有数据
        existing = self.db.execute(
            "SELECT COUNT(*) as cnt FROM forecast_snapshot WHERE fcst_version = ?", (fcst_version,)
        ).fetchone()
        if existing and existing["cnt"] > 0:
            raise FdeError(f"版本 {fcst_version} 已有快照数据，不允许重复 opening")

        # 取活跃零件集（进行中项目的零件）
        try:
            active_parts = self.fde.call("md_project_part", "list_active")
        except FdeError:
            raise FdeError("取活跃零件集失败") from None

        if not active_parts:
            raise FdeError("无活跃零件（无进行中项目的零件映射），无法生成快照行")

        # 取版本对应期间
        periods = ver.get("periods", [])
        if not periods or len(periods) < 3:
            raise FdeError(f"版本 {fcst_version} 的对应期间不足 3 期")

        # 为每个活跃零件生成 N+1/N+2/N+3 三行
        offsets = ["M+1", "M+2", "M+3"]
        created = 0
        for pp in active_parts:
            part_no = pp.get("part_no", "")
            project_no = pp.get("project_no", "")
            veh_model = pp.get("veh_model", "")
            if not part_no:
                continue
            # 取项目信息获取客户/工厂
            try:
                proj = self.fde.call("md_project", "get", project_no=project_no)
                oem_code = proj.get("oem_code", "")
                plant_code = proj.get("plant_code", "")
            except FdeError:
                continue
            if not oem_code or not plant_code:
                continue
            for i, period in enumerate(periods[:3]):
                self.db.execute(
                    "INSERT INTO forecast_snapshot (fcst_version, oem_code, plant_code, part_no, period, offset, project_no, veh_model, orig_qty, data_flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'OEM未提供')",
                    (fcst_version, oem_code, plant_code, part_no, period, offsets[i], project_no, veh_model),
                )
                created += 1

        return {"fcst_version": fcst_version, "created": created, "active_parts": len(active_parts)}

    def fill(self, fcst_version: str, oem_code: str, plant_code: str, part_no: str, period: str, orig_qty: float, data_flag: str = None, source_channel: str = None):
        """填/更新预测量（orig_qty 首次录入后即冻结）"""
        fcst_version = self._clean(fcst_version)
        oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code)
        part_no = self._clean(part_no)
        period = self._clean(period)
        if not all([fcst_version, oem_code, plant_code, part_no, period]):
            raise FdeError("版本号、客户编码、工厂编码、零件号、期间均必填")

        row = self._row(fcst_version, oem_code, plant_code, part_no, period)
        if row is None:
            raise FdeError(f"快照行不存在：{fcst_version}/{oem_code}/{plant_code}/{part_no}/{period}")

        # 行不可变：如果已有正常数据（非"未提供"），禁止修改
        if row["data_flag"] == "正常" and row["orig_qty"] > 0:
            raise FdeError("快照行已录入，不可修改——变更请使用新版本")

        qty = self._to_float(orig_qty)
        if qty < 0:
            raise FdeError("需求量不能为负")

        data_flag = self._clean(data_flag) if data_flag else "正常"
        if data_flag not in self.VALID_DATA_FLAGS:
            raise FdeError(f"数据标记只能为 {'/'.join(self.VALID_DATA_FLAGS)}")
        source_channel = self._clean(source_channel) if source_channel else "销售转录"
        if source_channel not in self.VALID_SOURCE_CHANNELS:
            raise FdeError(f"来源渠道只能为 {'/'.join(self.VALID_SOURCE_CHANNELS)}")

        recv_date = self._today()

        self.db.execute(
            "UPDATE forecast_snapshot SET orig_qty = ?, data_flag = ?, source_channel = ?, recv_date = ?, collector = ? WHERE fcst_version = ? AND oem_code = ? AND plant_code = ? AND part_no = ? AND period = ?",
            (qty, data_flag, source_channel, recv_date, self.ctx.get("userno", ""), fcst_version, oem_code, plant_code, part_no, period),
        )
        return self.get(fcst_version, oem_code, plant_code, part_no, period)

    def get(self, fcst_version: str, oem_code: str, plant_code: str, part_no: str, period: str):
        fcst_version = self._clean(fcst_version)
        oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code)
        part_no = self._clean(part_no)
        period = self._clean(period)
        row = self._row(fcst_version, oem_code, plant_code, part_no, period)
        if row is None:
            raise FdeError("快照行不存在")
        return dict(row)

    def list(self, fcst_version: str = None, oem_code: str = None, plant_code: str = None, part_no: str = None,
             period: str = None, data_flag: str = None, page: int = None, page_size: int = None):
        fcst_version = self._clean(fcst_version)
        oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code)
        part_no = self._clean(part_no)
        period = self._clean(period)
        data_flag = self._clean(data_flag)
        if data_flag and data_flag not in self.VALID_DATA_FLAGS:
            raise FdeError("数据标记筛选不合法")

        sql = "SELECT fcst_version, oem_code, plant_code, part_no, period, offset, project_no, veh_model, orig_qty, data_flag, source_channel, recv_date, collector FROM forecast_snapshot"
        clauses, params = [], []
        if fcst_version:
            clauses.append("fcst_version = ?")
            params.append(fcst_version)
        if oem_code:
            clauses.append("oem_code = ?")
            params.append(oem_code)
        if plant_code:
            clauses.append("plant_code = ?")
            params.append(plant_code)
        if part_no:
            clauses.append("part_no = ?")
            params.append(part_no)
        if period:
            clauses.append("period = ?")
            params.append(period)
        if data_flag:
            clauses.append("data_flag = ?")
            params.append(data_flag)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY fcst_version DESC, oem_code, plant_code, part_no, period"
        rows = self.db.execute(sql, tuple(params)).fetchall()
        items = [dict(r) for r in rows]
        total = len(items)
        if page is None and page_size is None:
            return {"total": total, "items": items}
        page_no = self._to_int(page, 1)
        page_sz = self._to_int(page_size, 50)
        if page_no < 1:
            page_no = 1
        if page_sz < 1:
            page_sz = 50
        start = (page_no - 1) * page_sz
        return {"total": total, "items": items[start:start + page_sz]}

    def get_version_status(self, fcst_version: str):
        """取版本状态：行数/未提供行数/接收渠道分布"""
        fcst_version = self._clean(fcst_version)
        if not fcst_version:
            raise FdeError("版本号必填")
        rows = self.db.execute(
            "SELECT data_flag, source_channel, COUNT(*) as cnt FROM forecast_snapshot WHERE fcst_version = ? GROUP BY data_flag, source_channel",
            (fcst_version,),
        ).fetchall()
        total = sum(r["cnt"] for r in rows)
        unfilled = sum(r["cnt"] for r in rows if r["data_flag"] == "OEM未提供")
        return {"fcst_version": fcst_version, "total_rows": total, "unfilled_rows": unfilled, "detail": [dict(r) for r in rows]}

    def lock_version(self, fcst_version: str):
        """R版发布联动锁定——将快照行标记为已锁定（通过版本状态体现）"""
        fcst_version = self._clean(fcst_version)
        if not fcst_version:
            raise FdeError("版本号必填")
        cnt = self.db.execute("SELECT COUNT(*) as cnt FROM forecast_snapshot WHERE fcst_version = ?", (fcst_version,)).fetchone()
        if not cnt or cnt["cnt"] == 0:
            raise FdeError(f"版本 {fcst_version} 无快照数据")
        return {"fcst_version": fcst_version, "locked": True, "rows": cnt["cnt"]}

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _to_int(self, value, default):
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise FdeError("分页参数非法")

    def _to_float(self, value, default=0):
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            raise FdeError("数值参数非法")

    def _today(self):
        from datetime import date
        return date.today().isoformat()

    def _row(self, fcst_version, oem_code, plant_code, part_no, period):
        return self.db.execute(
            "SELECT fcst_version, oem_code, plant_code, part_no, period, offset, project_no, veh_model, orig_qty, data_flag, source_channel, recv_date, collector FROM forecast_snapshot WHERE fcst_version = ? AND oem_code = ? AND plant_code = ? AND part_no = ? AND period = ?",
            (fcst_version, oem_code, plant_code, part_no, period),
        ).fetchone()
