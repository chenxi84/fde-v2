from __future__ import annotations

import re

from fde import FdeError

# 类别字典（架构卡片 7 的「类别（TPM/MOP/KPP）」；业务名逐字取自《术语表.md》与材料附录 A 缩略语表）
CATEGORIES = ("tpm", "mop", "kpp")
# 优化方向：判定口径的一半（另一半是阈值）。「越大越好」= 低于阈值即超阈值；「越小越好」反之。
DIRECTIONS = ("higher", "lower")
# 告警状态（聚合内子表，无独立标识）
ALERT_OPEN = "open"
ALERT_HANDLED = "handled"
# 硬终态：到达后一律拒
_TERMINAL = "closed"
# 「已基线」的判据：状态一旦离开 defined 就再也回不去，故 status != 'defined' 即已基线
_UNBASELINED = "defined"
# 判定口径三件 —— 一经基线不可直接改写，只能经 rebaseline 携带变更请求号改写（卡片 I-2 / BR-02）
_SPEC_FIELDS = ("direction", "target_value", "threshold_value")
_STATUS_CN = {"defined": "定义", "measuring": "度量中", "exceeded": "超阈值",
              "corrected": "已纠正", "closed": "已关闭"}
_CATEGORY_CN = {"tpm": "技术绩效指标（TPM）", "mop": "性能度量（MOP）", "kpp": "关键性能参数（KPP）"}
_DIRECTION_CN = {"higher": "越大越好", "lower": "越小越好"}
# 主档字段清单 —— `get` 与 `list` **共用同一份**，杜绝两处口径漂移（CONVENTION §7）
_MAIN_COLS = ("tpm_no, name, category, direction, unit, target_value, threshold_value,"
              " baseline_ver, change_no, current_value, current_period, req_no, owner,"
              " status, close_note, project_no")


class TechnicalMeasure:
    """技术度量聚合根。一条技术绩效指标（TPM / MOP / KPP），含目标值、阈值、阈值基线与实测值序列。

    数据来源类型：**独立创建**（度量的名称与目标/阈值由项目技术团队按技术计划定义，
    不是从别的应用自动生成的单据）。

    一致性边界（见 `architecture.md` 聚合根卡 7）：
      · **I-1 实测值超出阈值必须触发告警记录（度量与告警同事务）** —— 告警并入本聚合，
        没有独立标识（`(tpm_no, seq)` 复合主键），由 `record` 在**同一次调用**里连同实测值一起落库；
        跨度量的「告警汇总」由 `list_alerts` 这个**查询视图**提供，不是独立聚合。
        推论：**一次最多只有一条未了结的告警**（超阈值未纠正前不允许再记录，见 BR-06）。
      · **I-2 目标值与阈值一经基线不可直接改写，须经变更请求** —— 「判定口径」三件
        （优化方向 / 目标值 / 阈值）在 `baseline` 之后移出 `update` 的字段白名单，
        唯一改写入口是 `rebaseline`（必填变更请求号）。
      · **实测值序列**同属聚合内（`tpm_reading`）—— TPM 的本质是「趋势」，只留最新值就看不出趋势
        （材料附录 B：TPMs "monitored by comparing the current actual achievement … with that
        anticipated at the current time and **on future dates**"）。

    业务规则落点：BR-01 超阈值必须同事务写告警（I-1）/ BR-02 基线冻结判定口径（I-2）/
                 BR-03 编号唯一且不可变 / BR-04 类别·方向受字典约束 /
                 BR-05 目标值与阈值必须与方向一致 / BR-06 状态守卫（未基线不得记录、
                 超阈值未纠正不得记录或关闭、已关闭为终态）/ BR-07 度量期次在本度量内唯一 /
                 BR-08 数值字段必须是数字。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, name: str, category: str, direction: str, target_value,
               threshold_value, unit: str = None, req_no: str = None,
               owner: str = None, project_no: str = None):
        """定义一条技术度量（TPM/MOP/KPP），落库为「定义」状态，编号自动生成（`TPM-001` 起）。

        五个必填项逐个校验：名称 / 类别 / 优化方向 / 目标值 / 阈值 —— 类别与方向还要过字典（BR-04），
        目标值与阈值必须与方向一致（BR-05：越大越好时目标值不能低于阈值，反之亦然）。
        `req_no`（度量服务的需求）为**弱引用**，选填；填了就要能查到（跨应用只读校验，非同一事务）。
        """
        name = self._clean(name)
        category = self._clean(category)
        direction = self._clean(direction)
        if not name:
            raise FdeError("度量名称不能为空")
        self._check_category(category)                             # BR-04
        self._check_direction(direction)                           # BR-04
        target = self._num(target_value, "目标值")                  # BR-08
        threshold = self._num(threshold_value, "阈值")              # BR-08
        self._check_band(direction, target, threshold)             # BR-05
        req_no = self._clean(req_no)
        if req_no:
            self._assert_requirement_exists(req_no)                # 跨应用弱引用校验

        tpm_no = self._next_no()
        self.db.execute(
            "INSERT INTO technical_measure (tpm_no, name, category, direction, unit,"
            " target_value, threshold_value, req_no, owner, status, project_no)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'defined', ?)",
            (tpm_no, name, category, direction, self._clean(unit), target, threshold,
             req_no, self._clean(owner), self._clean(project_no)),
        )
        return self.get(tpm_no)

    def baseline(self, tpm_no: str, baseline_ver: str = None):
        """基线化：定义 → 度量中（`defined → measuring`）。

        这一步同时做两件事，是本聚合的**语义枢纽**：
          · **冻结判定口径** —— 目标值 / 阈值 / 优化方向自此不可直接改写（卡片 I-2 / BR-02），
            要改只能走 `rebaseline`（带变更请求号）；
          · **开始度量** —— 只有基线之后才允许记实测值（BR-06）。
        依据：材料 §6.7.1.2.1「technical plans … **identify the technical measures that will be
        tracked and assessed**」—— 先定下来（含目标/阈值），再谈跟踪；拿未冻结的口径去判超阈值，
        判定结果本身就没有意义（FIGRUE 6.7-2 的 (Re-)Planning 在 Execute 之前）。

        `baseline_ver` 选填，缺省 `B1`。**每个度量只能基线一次**（状态离开 `defined` 就回不去）。
        """
        cur = self._need(tpm_no)
        if cur["status"] == _TERMINAL:
            raise FdeError(f"度量 {tpm_no} 已关闭（终态），不能再基线化")
        if cur["status"] != _UNBASELINED:
            raise FdeError(
                f"度量 {tpm_no} 已经基线过了（{cur['baseline_ver'] or 'B1'}），当前为"
                f"「{self._status_cn(cur['status'])}」—— 每个度量只能基线一次；"
                "要改判定口径请用 rebaseline 并携带变更请求号（BR-02）")

        ver = self._clean(baseline_ver) or "B1"
        self.db.execute(
            "UPDATE technical_measure SET status = 'measuring', baseline_ver = ? WHERE tpm_no = ?",
            (ver, tpm_no),
        )
        return self.get(tpm_no)

    def record(self, tpm_no: str, period: str, measured_value, note: str = None):
        """记一期实测值：度量中 / 已纠正 → 度量中（在阈内）或 超阈值（出阈）。

        这是本聚合的**唯一**写实测值的入口，也是告警的**唯一**产生点 ——
        **I-1**：实测值超出阈值时，告警与这条实测值**同事务**落库（同一连接，
        平台保证一次服务调用一个事务），要么一起成功、要么一起失败。

        判定口径（BR-05 保证的一致方向）：
          · `higher`（越大越好）：实测值 `<` 阈值 ⇒ 超阈值，超出量 = 阈值 − 实测值；
          · `lower`（越小越好）：实测值 `>` 阈值 ⇒ 超阈值，超出量 = 实测值 − 阈值。

        两条状态守卫（BR-06）：
          · **未基线不得记录** —— 口径没冻结时的"超阈值"无从判定；
          · **超阈值未纠正不得继续记录** —— 材料 §6.7.1.2.2：「Should there be indications that
            existing trends, if allowed to continue, will yield an unfavorable outcome,
            **corrective action should begin as soon as practical**」—— 有未了结的告警时先纠正，
            不允许靠继续测量把告警冲淡。
        """
        cur = self._need(tpm_no)
        # 守卫顺序 = 安全边界：硬终态排最前（否则被后续分支绕过）
        if cur["status"] == _TERMINAL:
            raise FdeError(f"度量 {tpm_no} 已关闭（终态），不能再记录实测值")
        if cur["status"] == _UNBASELINED:
            raise FdeError(
                f"度量 {tpm_no} 尚未基线化（目标值与阈值未冻结），不能记录实测值 —— "
                "请先 baseline（BR-02）")
        if cur["status"] == "exceeded":
            raise FdeError(
                f"度量 {tpm_no} 已超阈值且尚有 {cur['alert_open']} 条告警未了结，"
                "必须先 correct 登记纠正措施，才能继续记录（BR-06）")

        period = self._clean(period)
        if not period:
            raise FdeError("度量期次不能为空")
        if self.db.execute("SELECT seq FROM tpm_reading WHERE tpm_no = ? AND period = ?",
                           (tpm_no, period)).fetchone():
            raise FdeError(
                f"度量 {tpm_no} 的第「{period}」期已经记过实测值，同一期次不能重复记录（BR-07）")
        value = self._num(measured_value, "实测值")                  # BR-08
        threshold = float(cur["threshold_value"])
        passed, deviation = self._judge(cur["direction"], value, threshold)

        self.db.execute(
            "INSERT INTO tpm_reading (tpm_no, seq, period, measured_value, passed, note)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (tpm_no, self._next_seq("tpm_reading", tpm_no), period, value,
             1 if passed else 0, self._clean(note)),
        )
        status = "measuring" if passed else "exceeded"
        if not passed:                                             # I-1：告警与实测值同事务
            self.db.execute(
                "INSERT INTO tpm_alert (tpm_no, seq, period, measured_value, deviation,"
                " message, status) VALUES (?, ?, ?, ?, ?, ?, 'open')",
                (tpm_no, self._next_seq("tpm_alert", tpm_no), period, value, deviation,
                 self._alert_message(cur, period, value, deviation)),
            )
        self.db.execute(
            "UPDATE technical_measure SET status = ?, current_value = ?, current_period = ?"
            " WHERE tpm_no = ?",
            (status, value, period, tpm_no),
        )
        return self.get(tpm_no)

    def correct(self, tpm_no: str, corrective_action: str):
        """纠正：超阈值 → 已纠正（`exceeded → corrected`）。

        登记纠正措施，并把**当前未了结的告警**一并了结（写入 `handle_note`）——
        两者同事务。材料 §6.7.1.2.2 的 "corrective action should begin as soon as practical"
        与 §6.7.1.3 的 "Assessment Results, Findings, and **Recommendations**" 都要求
        "发现偏差 → 有处置"，只把状态改掉而不写措施，等于没有处置。

        只有 `exceeded` 状态才谈得上纠正 —— 后续 `record` 再测：回到阈内即「度量中」，
        再次出阈则重新置「超阈值」并生成**新**的告警（旧告警已了结，仍留在告警台账里）。
        """
        cur = self._need(tpm_no)
        if cur["status"] == _TERMINAL:
            raise FdeError(f"度量 {tpm_no} 已关闭（终态），不能再纠正")
        if cur["status"] == _UNBASELINED:
            raise FdeError(
                f"度量 {tpm_no} 尚未基线化（「定义」状态），没有超阈值可言，无需纠正（BR-06）")
        if cur["status"] != "exceeded":
            raise FdeError(
                f"度量 {tpm_no} 当前为「{self._status_cn(cur['status'])}」，"
                "只有超阈值的度量才需要纠正")

        action = self._clean(corrective_action)
        if not action:
            raise FdeError("纠正措施不能为空")

        for r in self.db.execute(
                "SELECT seq FROM tpm_alert WHERE tpm_no = ? AND status = 'open'",
                (tpm_no,)).fetchall():
            self.db.execute(
                "UPDATE tpm_alert SET status = 'handled', handle_note = ?"
                " WHERE tpm_no = ? AND seq = ?", (action, tpm_no, r["seq"]))
        self.db.execute("UPDATE technical_measure SET status = 'corrected' WHERE tpm_no = ?",
                        (tpm_no,))
        return self.get(tpm_no)

    def close(self, tpm_no: str, note: str = None):
        """关闭度量：度量中 / 已纠正 → 已关闭（`→ closed`，硬终态）。

        关闸条件是 **BR-06：没有未了结的告警** —— 超阈值未纠正的度量不允许关闭
        （「还有一条告警挂着」的度量不是"收尾"，是被掩埋）。
        定义态（从未基线、从未度量）同样不能直接关闭 —— 没有度量过的度量无「关闭」可言。
        """
        cur = self._need(tpm_no)
        if cur["status"] == _TERMINAL:
            raise FdeError(f"度量 {tpm_no} 已经是关闭状态")
        if cur["status"] == _UNBASELINED:
            raise FdeError(
                f"度量 {tpm_no} 尚未基线化（「定义」状态），从未开始度量，不能关闭")
        if cur["status"] == "exceeded":
            raise FdeError(
                f"度量 {tpm_no} 还有 {cur['alert_open']} 条告警未了结（超阈值未纠正），"
                "不能关闭（BR-06）")

        self.db.execute("UPDATE technical_measure SET status = 'closed', close_note = ?"
                        " WHERE tpm_no = ?", (self._clean(note), tpm_no))
        return self.get(tpm_no)

    def rebaseline(self, tpm_no: str, target_value, threshold_value, change_no: str,
                   direction: str = None):
        """重设基线：改写判定口径（目标值 / 阈值 / 优化方向）的**唯一**入口（卡片 I-2 / BR-02）。

        必填 `change_no`（变更请求号）—— 目标值与阈值一旦基线就是**对外承诺的口径**，
        改它属于变更，不是修数据。本应用只能校验"带了变更请求号"，"该变更是否已批准"
        由 `change_request` 应用保证（该应用尚未被本页接入，见详设 §6.3，与同组
        `configuration_item.bump_version` 的处置一致）。

        基线版本自动递增（B1 → B2 → …）。已关闭的度量为终态，连变更请求号也不接受 ——
        这一点与 `configuration_item` 的 `bump_version`（终态拒绝）同口径。
        """
        cur = self._need(tpm_no)
        if cur["status"] == _TERMINAL:
            raise FdeError(f"度量 {tpm_no} 已关闭（终态），不能再改判定口径（BR-02）")
        if cur["status"] == _UNBASELINED:
            raise FdeError(
                f"度量 {tpm_no} 尚未基线化，目标值 / 阈值可直接经 update 修改，无需变更请求号（BR-02）")
        change_no = self._clean(change_no)
        if not change_no:
            raise FdeError("改写目标值 / 阈值必须经由已批准的变更请求，请提供变更请求号（BR-02）")

        target = self._num(target_value, "目标值")                   # BR-08
        threshold = self._num(threshold_value, "阈值")               # BR-08
        direction = self._clean(direction) or cur["direction"]
        self._check_direction(direction)                            # BR-04
        self._check_band(direction, target, threshold)              # BR-05

        self.db.execute(
            "UPDATE technical_measure SET target_value = ?, threshold_value = ?, direction = ?,"
            " baseline_ver = ?, change_no = ? WHERE tpm_no = ?",
            (target, threshold, direction, self._next_baseline_ver(cur["baseline_ver"]),
             change_no, tpm_no),
        )
        return self.get(tpm_no)

    def update(self, tpm_no: str, name: str = None, category: str = None, unit: str = None,
               req_no: str = None, owner: str = None, direction: str = None,
               target_value=None, threshold_value=None):
        """修改度量的描述性内容（名称 / 类别 / 计量单位 / 关联需求 / 责任人）。

        **判定口径三件（优化方向 / 目标值 / 阈值）只在该度量「定义」态可改** ——
        一经基线即移出白名单，再传就直接拒绝并指向 `rebaseline`（卡片 I-2 / BR-02）。
        这是本页与同组其它页的**语义差**：不是"字段一律只读"，而是"基线前可自由改、基线后须走变更"。
        编号落库不可变（BR-03）—— 没有参数可传，也就无从改起。
        """
        cur = self._need(tpm_no)
        if cur["status"] == _TERMINAL:
            raise FdeError(f"度量 {tpm_no} 已关闭（终态），不能再修改（BR-02）")

        spec_touched = any(v is not None for v in (direction, target_value, threshold_value))
        if spec_touched and cur["status"] != _UNBASELINED:
            raise FdeError(
                f"度量 {tpm_no} 已基线（{cur['baseline_ver'] or 'B1'}），"
                "目标值 / 阈值 / 优化方向不可直接改写，须经变更请求（rebaseline + 变更请求号，BR-02）")

        sets, args = [], []
        if name is not None:
            name = self._clean(name)
            if not name:
                raise FdeError("度量名称不能为空")
            sets.append("name = ?")
            args.append(name)
        if category is not None:
            category = self._clean(category)
            self._check_category(category)                          # BR-04
            sets.append("category = ?")
            args.append(category)
        if unit is not None:
            sets.append("unit = ?")
            args.append(self._clean(unit))
        if req_no is not None:
            req_no = self._clean(req_no)
            if req_no:
                self._assert_requirement_exists(req_no)             # 跨应用弱引用校验
            sets.append("req_no = ?")
            args.append(req_no)
        if owner is not None:
            sets.append("owner = ?")
            args.append(self._clean(owner))
        if spec_touched:
            direction = self._clean(direction) or cur["direction"]  # 只改目标值时不强传方向
            self._check_direction(direction)                        # BR-04
            target = (float(cur["target_value"]) if target_value is None
                      else self._num(target_value, "目标值"))
            threshold = (float(cur["threshold_value"]) if threshold_value is None
                         else self._num(threshold_value, "阈值"))
            self._check_band(direction, target, threshold)          # BR-05
            sets += ["direction = ?", "target_value = ?", "threshold_value = ?"]
            args += [direction, target, threshold]

        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(tpm_no)
        self.db.execute("UPDATE technical_measure SET " + ", ".join(sets) + " WHERE tpm_no = ?",
                        tuple(args))
        return self.get(tpm_no)

    def get(self, tpm_no: str):
        """按度量编号查询（含实测值序列 `readings` 与告警台账 `alerts`）；未命中返回 None，不抛异常。

        计数 `reading_total` / `alert_total` / `alert_open` 与 `list` 同口径
        （前端「告警 未/总」与"能否关闭"都读它）。
        """
        tpm_no = self._clean(tpm_no)
        if not tpm_no:
            return None
        row = self.db.execute(
            "SELECT " + _MAIN_COLS + " FROM technical_measure WHERE tpm_no = ?", (tpm_no,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["readings"] = [dict(r) for r in self.db.execute(
            "SELECT seq, period, measured_value, passed, note FROM tpm_reading"
            " WHERE tpm_no = ? ORDER BY seq", (tpm_no,)).fetchall()]
        out["alerts"] = [dict(r) for r in self.db.execute(
            "SELECT seq, period, measured_value, deviation, message, status, handle_note"
            " FROM tpm_alert WHERE tpm_no = ? ORDER BY seq", (tpm_no,)).fetchall()]
        out.update(self._counts(out["readings"], out["alerts"]))
        return out

    def list(self, category: str = None, status: str = None, direction: str = None,
             req_no: str = None, page: int = None, size: int = None):
        """按类别 / 状态 / 优化方向 / 关联需求筛选，**分页返回 `{items, total}`**，默认按编号升序。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（见 VIEW_CONVENTION）——
        少了它们，前端拿到的 `items` 恒为空、页面静默显示空态而**不报错**（同组实测踩过）。
        返回项与 `get` 同字段口径（`_MAIN_COLS` 共用 + 同一份计数）；
        实测值序列 / 告警台账**明细只在 `get`**（列表不需要 N+1 取子表）。
        """
        where, args = [], []
        for col, val in (("category", category), ("status", status),
                         ("direction", direction), ("req_no", req_no)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = "SELECT " + _MAIN_COLS + " FROM technical_measure"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY tpm_no"
        rows = []
        for r in self.db.execute(sql, tuple(args)).fetchall():
            d = dict(r)
            d.update(self._counts_by_no(d["tpm_no"]))
            rows.append(d)

        total = len(rows)
        if size:
            p = max(int(page or 1), 1)
            n = max(int(size), 1)
            rows = rows[(p - 1) * n: p * n]
        return {"items": rows, "total": total}

    def list_alerts(self, tpm_no: str = None, status: str = None, category: str = None,
                    page: int = None, size: int = None):
        """**跨度量的告警汇总**（查询视图，不是独立聚合）。

        材料 §6.7.1.2.1 的原话就是一句汇总视图的需求：
        「Summarize the condition of the project by using **color-coded (red, yellow, and green)
        alert zones for all technical measures**」—— 一屏看全"哪些度量在告警、差多少"。

        汇总行把所属度量的名称 / 类别 / 单位 / 目标值 / 阈值一并带出，并按 `{items, total}` 分页
        —— 与 `list` 同一契约口径。
        """
        where, args = [], []
        for col, val in (("a.tpm_no", tpm_no), ("a.status", status), ("m.category", category)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = ("SELECT a.tpm_no, a.seq, a.period, a.measured_value, a.deviation, a.message,"
               " a.status, a.handle_note, m.name, m.category, m.unit, m.direction,"
               " m.target_value, m.threshold_value, m.status AS tpm_status"
               " FROM tpm_alert a JOIN technical_measure m ON m.tpm_no = a.tpm_no")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY a.tpm_no, a.seq"
        rows = [dict(r) for r in self.db.execute(sql, tuple(args)).fetchall()]

        total = len(rows)
        if size:
            p = max(int(page or 1), 1)
            n = max(int(size), 1)
            rows = rows[(p - 1) * n: p * n]
        return {"items": rows, "total": total}

    # ── 私有（非服务） ────────────────────────────────────

    @staticmethod
    def _clean(v):
        return str(v).strip() if v is not None else ""

    @staticmethod
    def _num(v, label: str) -> float:
        """把入参解析为数字，非法即拒（None / 空串 / 非数字都拦下 —— BR-08）。"""
        s = str(v).strip() if v is not None else ""
        if not s:
            raise FdeError(f"{label}不能为空")
        try:
            return float(s)
        except ValueError:
            raise FdeError(f"{label}必须是数字，当前为「{s}」") from None

    @staticmethod
    def _num_text(v) -> str:
        """数值 → 人话文本（整数不带小数点：180.0 显示成 180）。仅用于告警信息。"""
        f = float(v)
        return str(int(f)) if f == int(f) else ("%g" % f)

    @staticmethod
    def _judge(direction: str, measured: float, threshold: float):
        """判定实测值是否在阈内，并给出超出量。**判定口径的唯一实现**（record 只用它）。

        返回 `(passed, deviation)`：`passed=False` 时 `deviation` 是恒为正的超出量。
        """
        if direction == "higher":
            passed = measured >= threshold
            raw = threshold - measured
        else:
            passed = measured <= threshold
            raw = measured - threshold
        return passed, (0.0 if passed else round(raw, 6))

    def _alert_message(self, cur: dict, period: str, value: float, deviation: float) -> str:
        """告警信息的人话模板：谁、哪一期、实测多少、阈值多少、差多少（带计量单位）。"""
        unit = cur["unit"] or ""
        cmp_cn = "低于" if cur["direction"] == "higher" else "高于"
        return (f"{cur['name']} 第「{period}」期实测值 {self._num_text(value)}{unit} "
                f"{cmp_cn}阈值 {self._num_text(cur['threshold_value'])}{unit}"
                f"（超出 {self._num_text(deviation)}{unit}）")

    @staticmethod
    def _check_category(category: str):
        if not category:
            raise FdeError("度量类别不能为空")
        if category not in CATEGORIES:
            raise FdeError(f"度量类别只能是 {'/'.join(CATEGORIES)} 之一（BR-04）")

    @staticmethod
    def _check_direction(direction: str):
        if not direction:
            raise FdeError("优化方向不能为空")
        if direction not in DIRECTIONS:
            raise FdeError(f"优化方向只能是 {'/'.join(DIRECTIONS)} 之一（BR-04）")

    @staticmethod
    def _check_band(direction: str, target: float, threshold: float):
        """BR-05：目标值必须落在阈值的「好」这一侧 —— 否则阈值根本不构成底线。

        越大越好 ⇒ 目标值 ≥ 阈值（阈值是**最低**可接受，附录 B "Threshold Requirements:
        A minimum acceptable set … the set could represent the descope position"）；
        越小越好 ⇒ 目标值 ≤ 阈值。
        """
        if direction == "higher" and target < threshold:
            raise FdeError(
                f"优化方向为「越大越好」时，目标值 {TechnicalMeasure._num_text(target)} "
                f"不能低于阈值 {TechnicalMeasure._num_text(threshold)}（BR-05）")
        if direction == "lower" and target > threshold:
            raise FdeError(
                f"优化方向为「越小越好」时，目标值 {TechnicalMeasure._num_text(target)} "
                f"不能高于阈值 {TechnicalMeasure._num_text(threshold)}（BR-05）")

    @staticmethod
    def _status_cn(status: str) -> str:
        return _STATUS_CN.get(status, status or "—")

    def _assert_requirement_exists(self, req_no: str):
        """跨应用校验弱引用：关联需求必须真实存在（只读调用，非同一事务，可悬空留空）。

        ⚠ 目标应用名 / 服务名必须是**字面量**（`self.fde.call("requirement", "get", ...)`）——
        参数化会被静态扫描器标成"动态目标"，契约校验退化为运行期（同组 risk / verification 同口径）。
        """
        try:
            found = self.fde.call("requirement", "get", req_no=req_no)
        except FdeError:
            raise FdeError(f"关联需求 {req_no} 不存在") from None
        except Exception:
            raise FdeError(f"关联需求 {req_no} 校验失败（requirement 应用不可用）") from None
        if not found:
            raise FdeError(f"关联需求 {req_no} 不存在，请先在需求台账中录入")

    def _counts(self, readings: list, alerts: list):
        """由两张子表推导计数 —— `get` 与 `list` 共用同一算法（口径不漂移）。"""
        return {"reading_total": len(readings),
                "alert_total": len(alerts),
                "alert_open": sum(1 for a in alerts if a["status"] == ALERT_OPEN)}

    def _counts_by_no(self, tpm_no: str):
        r = self.db.execute(
            "SELECT (SELECT COUNT(*) FROM tpm_reading WHERE tpm_no = ?) AS rd,"
            " (SELECT COUNT(*) FROM tpm_alert WHERE tpm_no = ?) AS al,"
            " (SELECT COUNT(*) FROM tpm_alert WHERE tpm_no = ? AND status = 'open') AS op",
            (tpm_no, tpm_no, tpm_no),
        ).fetchone()
        return {"reading_total": int(r["rd"] or 0), "alert_total": int(r["al"] or 0),
                "alert_open": int(r["op"] or 0)}

    def _need(self, tpm_no: str):
        tpm_no = self._clean(tpm_no)
        if not tpm_no:
            raise FdeError("度量编号不能为空")
        cur = self.get(tpm_no)
        if not cur:
            raise FdeError(f"度量 {tpm_no} 不存在")
        return cur

    def _next_no(self) -> str:
        """生成下一个度量编号：TPM-<三位序号>（BR-03：编号唯一且不可变）。"""
        rows = self.db.execute("SELECT tpm_no FROM technical_measure").fetchall()
        mx = 0
        for r in rows:
            m = re.match(r"^TPM-(\d+)$", str(r["tpm_no"]))
            if m:
                mx = max(mx, int(m.group(1)))
        return f"TPM-{mx + 1:03d}"

    def _next_baseline_ver(self, cur_ver: str) -> str:
        """基线版本递增：`B<n>` → `B<n+1>`（无版本时给 B1）。"""
        m = re.match(r"^B(\d+)$", self._clean(cur_ver))
        return f"B{(int(m.group(1)) + 1) if m else 1}"

    def _next_seq(self, table: str, tpm_no: str) -> int:
        """聚合内子表的序号：本度量内递增（`(tpm_no, seq)` 是复合主键，无全局标识）。"""
        rows = self.db.execute(
            f"SELECT seq FROM {table} WHERE tpm_no = ?", (tpm_no,)).fetchall()
        mx = 0
        for r in rows:
            mx = max(mx, int(r["seq"]))
        return mx + 1
