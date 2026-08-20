from fde import FdeError


class IndependentEvent:
    """独立事件登记表——叠加结构中独立加项的唯一载体。

    标识（主键）：event_no（编码规则 EVT-YYYYMM-NNN）
    承载三类事件：水位脉冲（拆解产出）、断点（ECN/零件切换）、其他一次性事件。
    事件量当期计入、不进趋势外推——in_demand 恒"是"、in_trend 恒"否"（系统强制）。
    """

    def _init_db(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS independent_event (
                event_no     TEXT PRIMARY KEY,
                event_type   TEXT NOT NULL,
                part_no      TEXT NOT NULL,
                oem_code     TEXT NOT NULL,
                veh_model    TEXT NOT NULL,
                period       TEXT NOT NULL,
                event_qty    REAL NOT NULL DEFAULT 0,
                in_demand    INTEGER NOT NULL DEFAULT 1,
                in_trend     INTEGER NOT NULL DEFAULT 0,
                source_basis TEXT NOT NULL,
                source_ref   TEXT,
                bp_batch     TEXT,
                bp_date      TEXT,
                status       TEXT NOT NULL DEFAULT '待确认',
                creator      TEXT NOT NULL,
                create_date  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                close_basis  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ie_part_no ON independent_event (part_no);
            CREATE INDEX IF NOT EXISTS idx_ie_status ON independent_event (status);
            CREATE INDEX IF NOT EXISTS idx_ie_period ON independent_event (period);
            CREATE INDEX IF NOT EXISTS idx_ie_bp_batch ON independent_event (bp_batch);
        """)

    # -----------------------------------------------------------------
    # 公开方法
    # -----------------------------------------------------------------

    def create(self, event_type: str, part_no: str, period: str, event_qty: float,
               source_basis: str, oem_code: str = "", veh_model: str = "",
               source_ref: str = None, bp_batch: str = None, bp_date: str = None):
        """新建独立事件。

        系统常量 in_demand=1（是）、in_trend=0（否），不可通过参数修改。
        人工登记必须附依据（source_basis 必填）。
        断点类事件的 bp_batch/bp_date 在 create_bp_pair 中自动设置。
        """
        event_type = self._clean(event_type)
        self._validate_event_type(event_type)
        part_no = self._clean(part_no)
        period = self._clean(period)
        source_basis = self._clean(source_basis)
        oem_code = self._clean(oem_code)
        veh_model = self._clean(veh_model)

        if not part_no:
            raise FdeError("零件号必填")
        if not period:
            raise FdeError("归属期间必填")
        if not source_basis:
            raise FdeError("来源依据必填（人工登记必须附依据）")
        if source_basis not in ("阶跃检测", "发运−结算倒推", "设变通知", "人工登记+说明"):
            raise FdeError("来源依据只能为：阶跃检测/发运−结算倒推/设变通知/人工登记+说明")
        if not oem_code:
            raise FdeError("客户编码必填")
        if not veh_model:
            raise FdeError("车型编码必填")

        # 断点必须成对登记（通过 create_bp_pair 入口）
        if event_type in ("断点·旧件截断", "断点·新件启动"):
            if not bp_batch:
                raise FdeError("断点类事件必须通过 create_bp_pair 成对登记，不可单独创建")

        # 脉冲防重：同一零件+期间+脉冲类型+生效/持续中 不得重复
        if event_type == "水位脉冲":
            dup = self.db.execute(
                "SELECT 1 FROM independent_event WHERE part_no = ? AND period = ? "
                "AND event_type = '水位脉冲' AND status IN ('生效', '持续中')",
                (part_no, period)
            ).fetchone()
            if dup:
                raise FdeError(f"零件 {part_no} 期间 {period} 已存在持续中的水位脉冲，不得重复登记")

        creator = self.ctx.userno if hasattr(self, "ctx") else "系统"
        event_no = self._generate_event_no()

        self.db.execute(
            "INSERT INTO independent_event (event_no, event_type, part_no, oem_code, veh_model, "
            "period, event_qty, in_demand, in_trend, source_basis, source_ref, bp_batch, bp_date, "
            "status, creator) VALUES (?,?,?,?,?,?,?,1,0,?,?,?,?,?,?)",
            (event_no, event_type, part_no, oem_code, veh_model, period, event_qty,
             source_basis, source_ref, bp_batch, bp_date, "待确认", creator)
        )
        return self.get(event_no)

    def get(self, event_no: str):
        """获取事件详情。"""
        event_no = self._clean(event_no)
        if not event_no:
            raise FdeError("事件编号必填")
        row = self.db.execute(
            "SELECT * FROM independent_event WHERE event_no = ?", (event_no,)
        ).fetchone()
        if not row:
            raise FdeError(f"事件 {event_no} 不存在")
        return dict(row)

    def list(self, part_no: str = None, event_type: str = None,
             status: str = None, period: str = None):
        """按条件列表查询。"""
        sql = "SELECT * FROM independent_event WHERE 1=1"
        params = []
        if part_no:
            sql += " AND part_no = ?"
            params.append(part_no)
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if period:
            sql += " AND period = ?"
            params.append(period)
        sql += " ORDER BY create_date DESC, event_no DESC"
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def confirm(self, event_no: str):
        """确认事件——待确认→生效。仅总部计划可操作。"""
        event_no = self._clean(event_no)
        event = self.get(event_no)
        if event["status"] != "待确认":
            raise FdeError(f"仅待确认事件可确认，当前状态：{event['status']}")
        self.db.execute(
            "UPDATE independent_event SET status = '生效' WHERE event_no = ?", (event_no,)
        )
        return self.get(event_no)

    def mark_sustained(self, event_no: str):
        """标记持续中——生效→持续中（水位脉冲未达标，不重复登记）。"""
        event_no = self._clean(event_no)
        event = self.get(event_no)
        if event["status"] != "生效":
            raise FdeError(f"仅生效事件可标记持续中，当前状态：{event['status']}")
        self.db.execute(
            "UPDATE independent_event SET status = '持续中' WHERE event_no = ?", (event_no,)
        )
        return self.get(event_no)

    def mark_subsided(self, event_no: str, close_basis: str):
        """标记已回落——生效→已回落（水位达标）。close_basis 必填，记录水位达标证明。"""
        event_no = self._clean(event_no)
        close_basis = self._clean(close_basis)
        if not close_basis:
            raise FdeError("回落依据必填（水位达标证明）")
        event = self.get(event_no)
        if event["status"] not in ("生效", "持续中"):
            raise FdeError(f"仅生效/持续中事件可标记回落，当前状态：{event['status']}")
        self.db.execute(
            "UPDATE independent_event SET status = '已回落', close_basis = ? WHERE event_no = ?",
            (close_basis, event_no)
        )
        return self.get(event_no)

    def close(self, event_no: str, close_basis: str):
        """关闭事件——已回落/生效→已关闭。close_basis 必填。"""
        event_no = self._clean(event_no)
        close_basis = self._clean(close_basis)
        if not close_basis:
            raise FdeError("关闭依据必填")
        event = self.get(event_no)
        if event["status"] == "已关闭":
            raise FdeError("事件已关闭，不可重复关闭")
        if event["status"] == "已取消":
            raise FdeError("已取消事件不可关闭")
        self.db.execute(
            "UPDATE independent_event SET status = '已关闭', close_basis = ? WHERE event_no = ?",
            (close_basis, event_no)
        )
        return self.get(event_no)

    def cancel(self, event_no: str, close_basis: str):
        """取消事件——误判/误登记时使用。状态→已取消，close_basis 记录复盘结论。"""
        event_no = self._clean(event_no)
        close_basis = self._clean(close_basis)
        if not close_basis:
            raise FdeError("取消原因必填（复盘结论）")
        event = self.get(event_no)
        if event["status"] == "已关闭":
            raise FdeError("已关闭事件不可取消")
        if event["status"] == "已取消":
            raise FdeError("事件已取消")
        self.db.execute(
            "UPDATE independent_event SET status = '已取消', close_basis = ? WHERE event_no = ?",
            (close_basis, event_no)
        )
        return self.get(event_no)

    def create_bp_pair(self, old_part_no: str, new_part_no: str,
                       bp_date: str, old_qty: float, new_qty: float,
                       oem_code: str, veh_model: str, period: str,
                       source_basis: str = "设变通知", source_ref: str = None):
        """创建成对断点——旧件截断+新件启动，同 bp_batch 关联。

        断点必须成对登记，禁止单边登记。
        """
        old_part_no = self._clean(old_part_no)
        new_part_no = self._clean(new_part_no)
        bp_date = self._clean(bp_date)
        oem_code = self._clean(oem_code)
        veh_model = self._clean(veh_model)
        period = self._clean(period)
        source_basis = self._clean(source_basis) or "设变通知"
        source_ref = self._clean(source_ref) if source_ref else None

        if not old_part_no or not new_part_no:
            raise FdeError("新旧零件号均必填")
        if not bp_date:
            raise FdeError("断点时点必填")
        if not oem_code:
            raise FdeError("客户编码必填")
        if not veh_model:
            raise FdeError("车型编码必填")
        if not period:
            raise FdeError("归属期间必填")

        bp_batch = self._generate_bp_batch()
        creator = self.ctx.userno if hasattr(self, "ctx") else "系统"

        # 旧件截断（负量）
        old_event_no = self._generate_event_no()
        self.db.execute(
            "INSERT INTO independent_event (event_no, event_type, part_no, oem_code, veh_model, "
            "period, event_qty, in_demand, in_trend, source_basis, source_ref, bp_batch, bp_date, "
            "status, creator) VALUES (?,?,?,?,?,?,?,1,0,?,?,?,?,?,?)",
            (old_event_no, "断点·旧件截断", old_part_no, oem_code, veh_model, period,
             -abs(old_qty), source_basis, source_ref, bp_batch, bp_date, "待确认", creator)
        )

        # 新件启动（正量）
        new_event_no = self._generate_event_no()
        self.db.execute(
            "INSERT INTO independent_event (event_no, event_type, part_no, oem_code, veh_model, "
            "period, event_qty, in_demand, in_trend, source_basis, source_ref, bp_batch, bp_date, "
            "status, creator) VALUES (?,?,?,?,?,?,?,1,0,?,?,?,?,?,?)",
            (new_event_no, "断点·新件启动", new_part_no, oem_code, veh_model, period,
             abs(new_qty), source_basis, source_ref, bp_batch, bp_date, "待确认", creator)
        )

        return {
            "bp_batch": bp_batch,
            "bp_date": bp_date,
            "old_event": self.get(old_event_no),
            "new_event": self.get(new_event_no),
        }

    # -----------------------------------------------------------------
    # 内部辅助
    # -----------------------------------------------------------------

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _validate_event_type(self, event_type):
        valid = ["水位脉冲", "断点·旧件截断", "断点·新件启动", "其他"]
        if event_type not in valid:
            raise FdeError(f"事件类型只能为：{'/'.join(valid)}")

    def _generate_event_no(self):
        """生成事件编号 EVT-YYYYMM-NNN。"""
        from datetime import datetime, timezone
        yyyymm = datetime.now(timezone.utc).strftime("%Y%m")
        for _ in range(5):
            max_seq = self.db.execute(
                "SELECT event_no FROM independent_event WHERE event_no LIKE ? ORDER BY event_no DESC LIMIT 1",
                (f"EVT-{yyyymm}-%",)
            ).fetchone()
            if max_seq:
                try:
                    seq = int(max_seq["event_no"].split("-")[-1]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            event_no = f"EVT-{yyyymm}-{seq:03d}"
            if not self.db.execute(
                "SELECT 1 FROM independent_event WHERE event_no = ?", (event_no,)
            ).fetchone():
                return event_no
        raise FdeError("事件编号生成失败，请重试")

    def _generate_bp_batch(self):
        """生成断点批次号 BP-YYYYMM-NN。"""
        from datetime import datetime, timezone
        yyyymm = datetime.now(timezone.utc).strftime("%Y%m")
        for _ in range(5):
            max_batch = self.db.execute(
                "SELECT bp_batch FROM independent_event WHERE bp_batch LIKE ? ORDER BY bp_batch DESC LIMIT 1",
                (f"BP-{yyyymm}-%",)
            ).fetchone()
            if max_batch and max_batch["bp_batch"]:
                try:
                    seq = int(max_batch["bp_batch"].split("-")[-1]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            bp_batch = f"BP-{yyyymm}-{seq:02d}"
            # 确保未使用
            dup = self.db.execute(
                "SELECT 1 FROM independent_event WHERE bp_batch = ?", (bp_batch,)
            ).fetchone()
            if not dup:
                return bp_batch
        raise FdeError("断点批次号生成失败，请重试")
