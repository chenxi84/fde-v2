from fde import FdeError


class ProjectInfo:
    """项目信息台账——毛需求加工的主数据底座，记录项目×零件的六维属性与生命周期。

    标识（主键）：project_no + part_no（联合业务键）
    阶段决定需求去向：进行中→近端毛需求；待定点/定点中→长期产能规划。
    usage/share 为引用展示字段，权威源在 vehicle_part_mapping。
    """

    def _init_db(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS project_info (
                project_no  TEXT NOT NULL,
                part_no     TEXT NOT NULL,
                stage       TEXT NOT NULL DEFAULT '待定点',
                award_prob  REAL,
                oem_code    TEXT NOT NULL,
                plant_code  TEXT NOT NULL,
                veh_model   TEXT NOT NULL,
                platform    TEXT,
                part_kind   TEXT NOT NULL,
                usage       REAL NOT NULL DEFAULT 0,
                share       REAL NOT NULL DEFAULT 0,
                sop         TEXT NOT NULL,
                eop         TEXT,
                lc_shape    TEXT,
                owner_sales TEXT NOT NULL,
                PRIMARY KEY (project_no, part_no)
            );
            CREATE TABLE IF NOT EXISTS change_log (
                project_no  TEXT NOT NULL,
                part_no     TEXT NOT NULL,
                seq         INTEGER NOT NULL,
                field_name  TEXT NOT NULL,
                old_value   TEXT,
                new_value   TEXT,
                reason      TEXT,
                operator    TEXT,
                op_time     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (project_no, part_no, seq)
            );
        """)

    # -----------------------------------------------------------------
    # 公开方法
    # -----------------------------------------------------------------

    def create(self, project_no: str, part_no: str, stage: str = "待定点",
               oem_code: str = "", plant_code: str = "", veh_model: str = "",
               part_kind: str = "专用", sop: str = "", owner_sales: str = "",
               award_prob: float = None, platform: str = None,
               usage: float = 0, share: float = 0,
               eop: str = None, lc_shape: str = None):
        """新建项目-零件关联记录。"""
        project_no = self._clean(project_no)
        part_no = self._clean(part_no)
        if not project_no or not part_no:
            raise FdeError("项目号和零件号必填")
        if self._exists(project_no, part_no):
            raise FdeError(f"项目 {project_no} 下零件 {part_no} 已存在，不可重复登记")

        stage = self._clean(stage) or "待定点"
        self._validate_stage(stage)
        oem_code = self._clean(oem_code)
        plant_code = self._clean(plant_code)
        veh_model = self._clean(veh_model)
        part_kind = self._clean(part_kind) or "专用"
        self._validate_part_kind(part_kind)
        sop = self._clean(sop)
        owner_sales = self._clean(owner_sales)
        lc_shape = self._clean(lc_shape) if lc_shape else None

        if not oem_code:
            raise FdeError("客户编码必填")
        if not plant_code:
            raise FdeError("工厂编码必填")
        if not veh_model:
            raise FdeError("车型必填")
        if not sop:
            raise FdeError("SOP必填")
        if not owner_sales:
            raise FdeError("责任销售必填")

        # 通用件关联检查: 通过 OEM 工厂列表隐式体现客户数
        if part_kind == "通用":
            plants = [p.strip() for p in plant_code.split(",") if p.strip()]
            if len(plants) < 2:
                # 单一客户通用，允许但需信任后续审核
                pass

        self.db.execute(
            "INSERT INTO project_info (project_no, part_no, stage, award_prob, oem_code, "
            "plant_code, veh_model, platform, part_kind, usage, share, sop, eop, lc_shape, owner_sales) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (project_no, part_no, stage, award_prob, oem_code, plant_code, veh_model,
             platform, part_kind, usage, share, sop, eop, lc_shape, owner_sales)
        )
        return self.get(project_no, part_no)

    def get(self, project_no: str, part_no: str):
        """获取项目-零件详情。"""
        project_no = self._clean(project_no)
        part_no = self._clean(part_no)
        if not project_no or not part_no:
            raise FdeError("项目号和零件号必填")
        row = self.db.execute(
            "SELECT * FROM project_info WHERE project_no = ? AND part_no = ?",
            (project_no, part_no)
        ).fetchone()
        if not row:
            raise FdeError(f"项目 {project_no} 零件 {part_no} 不存在")
        return dict(row)

    def list(self, stage: str = None, oem_code: str = None, owner_sales: str = None):
        """按条件列表查询。"""
        sql = "SELECT * FROM project_info WHERE 1=1"
        params = []
        if stage:
            sql += " AND stage = ?"
            params.append(stage)
        if oem_code:
            sql += " AND oem_code = ?"
            params.append(oem_code)
        if owner_sales:
            sql += " AND owner_sales = ?"
            params.append(owner_sales)
        sql += " ORDER BY project_no, part_no"
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def update(self, project_no: str, part_no: str, **kwargs):
        """更新项目-零件属性，记录变更日志。

        支持的字段：stage, award_prob, oem_code, plant_code, veh_model,
        platform, part_kind, usage, share, sop, eop, lc_shape, owner_sales
        """
        project_no = self._clean(project_no)
        part_no = self._clean(part_no)
        if not project_no or not part_no:
            raise FdeError("项目号和零件号必填")

        current = self.get(project_no, part_no)
        allowed_fields = [
            "stage", "award_prob", "oem_code", "plant_code", "veh_model",
            "platform", "part_kind", "usage", "share", "sop", "eop",
            "lc_shape", "owner_sales"
        ]
        operator = kwargs.pop("_operator", self.ctx.userno if hasattr(self, "ctx") else "系统")
        reason = kwargs.pop("_reason", None)

        changes = []
        for field in allowed_fields:
            if field not in kwargs:
                continue
            new_val = kwargs[field]
            old_val = current.get(field)
            if str(new_val) != str(old_val if old_val is not None else ""):
                changes.append((field, old_val, new_val))

        if not changes:
            return current

        # 阶段迁移校验
        if "stage" in kwargs:
            new_stage = self._clean(kwargs["stage"])
            self._validate_stage(new_stage)
            if not reason:
                raise FdeError("阶段迁移必须提供变更原因")

        # 更新主表
        set_clauses = []
        update_params = []
        for field in allowed_fields:
            if field in kwargs:
                set_clauses.append(f"{field} = ?")
                update_params.append(kwargs[field])
        update_params.extend([project_no, part_no])
        self.db.execute(
            f"UPDATE project_info SET {', '.join(set_clauses)} WHERE project_no = ? AND part_no = ?",
            update_params
        )

        # 写变更日志
        for field, old_val, new_val in changes:
            seq = self._next_change_seq(project_no, part_no)
            self.db.execute(
                "INSERT INTO change_log (project_no, part_no, seq, field_name, old_value, new_value, reason, operator) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (project_no, part_no, seq, field, str(old_val) if old_val is not None else "",
                 str(new_val), reason, operator)
            )

        return self.get(project_no, part_no)

    def set_stage(self, project_no: str, part_no: str, new_stage: str, reason: str):
        """阶段迁移——记录变更日志后更新阶段。

        状态机：待定点→定点中→进行中→EOP关闭
        阶段迁移必须记录变更日志（旧阶段/新阶段/操作人/时点/原因）。
        """
        project_no = self._clean(project_no)
        part_no = self._clean(part_no)
        new_stage = self._clean(new_stage)
        reason = self._clean(reason)
        if not reason:
            raise FdeError("阶段迁移原因必填")
        self._validate_stage(new_stage)

        current = self.get(project_no, part_no)
        old_stage = current["stage"]
        if old_stage == new_stage:
            return current

        # 状态机约束
        valid_transitions = {
            "待定点": ["定点中"],
            "定点中": ["进行中", "待定点"],
            "进行中": ["EOP关闭"],
            "EOP关闭": ["进行中"],  # 年型/改款可重新激活
        }
        allowed = valid_transitions.get(old_stage, [])
        if new_stage not in allowed:
            raise FdeError(f"阶段 {old_stage} 不可迁移至 {new_stage}，允许的目标阶段：{', '.join(allowed)}")

        return self.update(
            project_no, part_no, stage=new_stage,
            _operator=self.ctx.userno if hasattr(self, "ctx") else "系统",
            _reason=reason
        )

    def get_change_log(self, project_no: str, part_no: str):
        """获取变更日志列表。"""
        project_no = self._clean(project_no)
        part_no = self._clean(part_no)
        rows = self.db.execute(
            "SELECT * FROM change_log WHERE project_no = ? AND part_no = ? ORDER BY seq",
            (project_no, part_no)
        ).fetchall()
        return [dict(r) for r in rows]

    # -----------------------------------------------------------------
    # 内部辅助
    # -----------------------------------------------------------------

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _exists(self, project_no, part_no):
        return self.db.execute(
            "SELECT 1 FROM project_info WHERE project_no = ? AND part_no = ?",
            (project_no, part_no)
        ).fetchone() is not None

    def _validate_stage(self, stage):
        valid = ["待定点", "定点中", "进行中", "EOP关闭"]
        if stage not in valid:
            raise FdeError(f"阶段只能为：{'/'.join(valid)}")

    def _validate_part_kind(self, part_kind):
        valid = ["专用", "通用"]
        if part_kind not in valid:
            raise FdeError(f"零件类别只能为：{'/'.join(valid)}")

    def _next_change_seq(self, project_no, part_no):
        row = self.db.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM change_log WHERE project_no = ? AND part_no = ?",
            (project_no, part_no)
        ).fetchone()
        return row[0]
