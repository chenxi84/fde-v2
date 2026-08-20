from fde import FdeError


class VehiclePartMap:
    """车型—零件映射表——车型级外部数据到零件级的桥接，量纲（单车用量/份额）的权威源。

    标识（主键）：part_no + veh_model（联合业务键）
    含量纲历史版本子表——基线校准、FVA 复盘需要"当时的口径"。
    单一权威原则：用量/份额以本表为准，prj_ledger 仅引用展示。
    """

    def _init_db(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS veh_part_map (
                part_no   TEXT NOT NULL,
                veh_model TEXT NOT NULL,
                platform  TEXT,
                usage     REAL NOT NULL DEFAULT 0,
                share     REAL NOT NULL DEFAULT 0,
                lc_stage  TEXT NOT NULL,
                lc_shape  TEXT NOT NULL DEFAULT '传统',
                sop       TEXT NOT NULL,
                eop       TEXT,
                status    TEXT NOT NULL DEFAULT '生效',
                source    TEXT NOT NULL,
                PRIMARY KEY (part_no, veh_model)
            );""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS usage_history (
                part_no        TEXT NOT NULL,
                veh_model      TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                field_name     TEXT NOT NULL,
                value          REAL NOT NULL,
                effective_to   TEXT,
                change_basis   TEXT NOT NULL,
                PRIMARY KEY (part_no, veh_model, effective_from, field_name)
            );""")

    # -----------------------------------------------------------------
    # 公开方法
    # -----------------------------------------------------------------

    def create(self, part_no: str, veh_model: str, platform: str = None,
               usage: float = 0, share: float = 0, lc_stage: str = "",
               lc_shape: str = "传统", sop: str = "", eop: str = None,
               source: str = "", status: str = "生效"):
        """新建车型-零件映射。"""
        part_no = self._clean(part_no)
        veh_model = self._clean(veh_model)
        if not part_no or not veh_model:
            raise FdeError("零件号和车型必填")
        if self._exists(part_no, veh_model):
            raise FdeError(f"零件 {part_no} 车型 {veh_model} 映射已存在")

        lc_stage = self._clean(lc_stage)
        self._validate_lc_stage(lc_stage)
        lc_shape = self._clean(lc_shape) or "传统"
        self._validate_lc_shape(lc_shape)
        sop = self._clean(sop)
        source = self._clean(source)
        status = self._clean(status) or "生效"
        self._validate_status(status)
        platform = self._clean(platform) if platform else None
        eop = self._clean(eop) if eop else None

        if not lc_stage:
            raise FdeError("生命周期阶段必填")
        if not sop:
            raise FdeError("SOP必填")
        if not source:
            raise FdeError("映射依据必填（BOM/设变通知/商务确认）")
        if source not in ("BOM", "设变通知", "商务确认"):
            raise FdeError("映射依据只能为：BOM/设变通知/商务确认")

        self.db.execute(
            "INSERT INTO veh_part_map (part_no, veh_model, platform, usage, share, "
            "lc_stage, lc_shape, sop, eop, status, source) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (part_no, veh_model, platform, usage, share, lc_stage, lc_shape, sop, eop, status, source)
        )
        return self.get(part_no, veh_model)

    def get(self, part_no: str, veh_model: str):
        """获取映射详情。"""
        part_no = self._clean(part_no)
        veh_model = self._clean(veh_model)
        if not part_no or not veh_model:
            raise FdeError("零件号和车型必填")
        row = self.db.execute(
            "SELECT * FROM veh_part_map WHERE part_no = ? AND veh_model = ?",
            (part_no, veh_model)
        ).fetchone()
        if not row:
            raise FdeError(f"零件 {part_no} 车型 {veh_model} 映射不存在")
        return dict(row)

    def list(self, part_no: str = None, veh_model: str = None,
             lc_stage: str = None, status: str = None, page: int = None, size: int = None):
        """按条件列表查询。"""
        sql = "SELECT * FROM veh_part_map WHERE 1=1"
        params = []
        if part_no:
            sql += " AND part_no = ?"
            params.append(part_no)
        if veh_model:
            sql += " AND veh_model = ?"
            params.append(veh_model)
        if lc_stage:
            sql += " AND lc_stage = ?"
            params.append(lc_stage)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY part_no, veh_model"
        rows = self.db.execute(sql, params).fetchall()
        total = len(rows)
        # 服务端分页
        if page is not None and size is not None:
            page_no = max(1, int(page) if page else 1)
            size_n = max(1, int(size) if size else 50)
            start = (page_no - 1) * size_n
            rows = rows[start:start + size_n]

        return {"items": [dict(r) for r in rows], "total": total}

    def update(self, part_no: str, veh_model: str, **kwargs):
        """更新映射属性（不含量纲字段；量纲变更必须走 set_usage/set_share）。"""
        part_no = self._clean(part_no)
        veh_model = self._clean(veh_model)
        if not part_no or not veh_model:
            raise FdeError("零件号和车型必填")

        current = self.get(part_no, veh_model)
        # 量纲字段不允许直接更新
        for blocked in ("usage", "share"):
            if blocked in kwargs:
                raise FdeError(f"{blocked} 变更必须通过 set_{blocked} 方法生成历史版本，不可直接覆盖")

        allowed = ["platform", "lc_stage", "lc_shape", "sop", "eop", "status", "source"]
        set_clauses = []
        params = []
        for field in allowed:
            if field in kwargs:
                val = kwargs[field]
                if field == "lc_stage":
                    self._validate_lc_stage(val)
                elif field == "lc_shape":
                    self._validate_lc_shape(val)
                elif field == "status":
                    self._validate_status(val)
                elif field == "source":
                    if val not in ("BOM", "设变通知", "商务确认"):
                        raise FdeError("映射依据只能为：BOM/设变通知/商务确认")
                set_clauses.append(f"{field} = ?")
                params.append(val)
        if not set_clauses:
            return current
        params.extend([part_no, veh_model])
        self.db.execute(
            f"UPDATE veh_part_map SET {', '.join(set_clauses)} WHERE part_no = ? AND veh_model = ?",
            params
        )
        return self.get(part_no, veh_model)

    def set_usage(self, part_no: str, veh_model: str, new_usage: float,
                  effective_date: str, basis: str):
        """变更单车用量——生成历史版本，旧版本按生效期间保留。

        new_usage: 新单车用量
        effective_date: 生效日期 YYYY-MM-DD
        basis: 变更依据（设变通知号/商务函件号等）
        """
        part_no = self._clean(part_no)
        veh_model = self._clean(veh_model)
        effective_date = self._clean(effective_date)
        basis = self._clean(basis)
        if not basis:
            raise FdeError("量纲变更依据必填（设变通知/商务函件号）")

        current = self.get(part_no, veh_model)
        old_usage = current["usage"]
        if old_usage == new_usage:
            return current

        # 历史版本：旧usage的effective_to设为新生效日期
        self.db.execute(
            "UPDATE usage_history SET effective_to = ? "
            "WHERE part_no = ? AND veh_model = ? AND field_name = 'usage' AND effective_to IS NULL",
            (effective_date, part_no, veh_model)
        )
        # 插入旧值历史版本
        self.db.execute(
            "INSERT INTO usage_history (part_no, veh_model, effective_from, field_name, value, effective_to, change_basis) "
            "VALUES (?,?,?,?,?,?,?)",
            (part_no, veh_model, current.get("sop", effective_date), "usage", old_usage, effective_date, basis)
        )

        # 更新主表
        self.db.execute(
            "UPDATE veh_part_map SET usage = ? WHERE part_no = ? AND veh_model = ?",
            (new_usage, part_no, veh_model)
        )
        return self.get(part_no, veh_model)

    def set_share(self, part_no: str, veh_model: str, new_share: float,
                  effective_date: str, basis: str):
        """变更供应份额——生成历史版本。

        new_share: 新份额（%）
        effective_date: 生效日期 YYYY-MM-DD
        basis: 变更依据（设变通知号/商务函件号等）
        """
        part_no = self._clean(part_no)
        veh_model = self._clean(veh_model)
        effective_date = self._clean(effective_date)
        basis = self._clean(basis)
        if not basis:
            raise FdeError("份额变更依据必填（设变通知/商务函件号）")

        current = self.get(part_no, veh_model)
        old_share = current["share"]
        if old_share == new_share:
            return current

        # 历史版本：旧share的effective_to设为新生效日期
        self.db.execute(
            "UPDATE usage_history SET effective_to = ? "
            "WHERE part_no = ? AND veh_model = ? AND field_name = 'share' AND effective_to IS NULL",
            (effective_date, part_no, veh_model)
        )
        # 插入旧值历史版本
        self.db.execute(
            "INSERT INTO usage_history (part_no, veh_model, effective_from, field_name, value, effective_to, change_basis) "
            "VALUES (?,?,?,?,?,?,?)",
            (part_no, veh_model, current.get("sop", effective_date), "share", old_share, effective_date, basis)
        )

        # 更新主表
        self.db.execute(
            "UPDATE veh_part_map SET share = ? WHERE part_no = ? AND veh_model = ?",
            (new_share, part_no, veh_model)
        )
        return self.get(part_no, veh_model)

    def get_usage_history(self, part_no: str, veh_model: str):
        """查询量纲历史版本（用量+份额）。"""
        part_no = self._clean(part_no)
        veh_model = self._clean(veh_model)
        rows = self.db.execute(
            "SELECT * FROM usage_history WHERE part_no = ? AND veh_model = ? ORDER BY effective_from DESC, field_name",
            (part_no, veh_model)
        ).fetchall()
        return {"items": [dict(r) for r in rows], "total": total}

    def disable(self, part_no: str, veh_model: str, reason: str = ""):
        """停用映射——设变替代或EOP。"""
        part_no = self._clean(part_no)
        veh_model = self._clean(veh_model)
        current = self.get(part_no, veh_model)
        if current["status"] == "停用":
            return current
        self.db.execute(
            "UPDATE veh_part_map SET status = '停用' WHERE part_no = ? AND veh_model = ?",
            (part_no, veh_model)
        )
        return self.get(part_no, veh_model)

    def get_active_mapping(self, part_no: str):
        """取零件当前生效的车型映射——供 D03/D08 调用。"""
        rows = self.db.execute(
            "SELECT * FROM veh_part_map WHERE part_no = ? AND status = '生效'", (part_no,)
        ).fetchall()
        return {"items": [dict(r) for r in rows], "total": total}

    # -----------------------------------------------------------------
    # 内部辅助
    # -----------------------------------------------------------------

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _exists(self, part_no, veh_model):
        return self.db.execute(
            "SELECT 1 FROM veh_part_map WHERE part_no = ? AND veh_model = ?",
            (part_no, veh_model)
        ).fetchone() is not None

    def _validate_lc_stage(self, stage):
        valid = ["爬坡", "成熟", "衰退", "EOP临近"]
        if stage not in valid:
            raise FdeError(f"生命周期阶段只能为：{'/'.join(valid)}")

    def _validate_lc_shape(self, shape):
        valid = ["传统", "上市高后下滑"]
        if shape not in valid:
            raise FdeError(f"生命周期形态只能为：{'/'.join(valid)}")

    def _validate_status(self, status):
        valid = ["生效", "停用"]
        if status not in valid:
            raise FdeError(f"状态只能为：{'/'.join(valid)}")
