from __future__ import annotations

import re

from fde import FdeError

# 计划类型字典（术语表已收 SEMP / 验证与确认计划（V&V Plan）/ 集成计划 / 技术开发计划 /
# HSI Plan 五种；风险管理计划、评审计划、配置管理计划取自材料附录 K TABLE K-1 的
# 「Key Technical Plans」清单 —— 本步回填，见 新增术语.md）。
# ⚠ 「项目计划（Project Plan）」**不在本字典内**：材料 §6.1.1.2.1 明确「The SEMP is a
#    **subordinate document to the project plan**」—— 项目计划是技术计划的上位，不是技术计划之一。
PLAN_TYPES = ("semp", "verification", "integration", "technology_dev", "hsi",
              "risk_mgmt", "review", "cm")
# 阶段字典：与同组 review 同口径（术语表的 Pre-Phase A / Phase A..E；阶段在本聚合里是
# **枚举属性**，不独立成聚合 —— `architecture.md` 关键设计决策 3）
PHASES = ("pre_a", "a", "b", "c", "d", "e")
# 成熟度字典（材料附录 K TABLE K-1 的图例："A = Approach / B = Baseline / P = Preliminary / U = Update"）
MATURITIES = ("approach", "preliminary", "baseline", "update")
DEFAULT_MATURITY = "approach"
# 状态机（卡片 10：草稿 → 审批中 → 已批准 → 已修订）
# ⚠ 与同组其它页的**语义差**：本页**没有硬终态** —— 已修订 → 审批中 → 已批准 是一条**环**，
#    「内容锁定」的两个状态各有自己的解锁入口（审批中 → withdraw 撤回；已批准 → revise 修订）。
_EDITABLE = ("draft", "revised")
_FROZEN = ("in_review", "approved")
_REVISABLE = "approved"
_STATUS_CN = {"draft": "草稿", "in_review": "审批中", "approved": "已批准", "revised": "已修订"}
# 阶段中文名（仅用于**错误文案**与覆盖视图的可读性 —— 前端的业务名带英文码，见 新增术语.md）
_PHASE_CN = {"pre_a": "预 A 阶段", "a": "A 阶段", "b": "B 阶段",
             "c": "C 阶段", "d": "D 阶段", "e": "E 阶段"}
# 主档字段清单 —— `get` 与 `list` **共用同一份**，杜绝两处口径漂移（CONVENTION §7）
_MAIN_COLS = ("plan_no, name, plan_type, phase, maturity, version, status,"
              " scope, revise_note, owner, project_no")


class TechPlan:
    """技术计划聚合根。计划类文档（SEMP / 验证与确认计划 / 集成计划 / 技术开发计划 / HSI Plan …）
    的统一管理，以「计划类型」属性区分。数据来源类型：**独立创建**。

    一致性边界（见 `architecture.md` 聚合根卡 10）：
      · **I-1 每个阶段至少有一份已批准的该类计划（计划与阶段绑定）** —— 拆成三个落点：
          - 「计划与阶段绑定」= `phase` 必填且过阶段字典（BR-02）；
          - 「生效唯一」= 同一 `(plan_type, phase)` 下**只允许一份「已批准」**（BR-03），
            由 `approve` **同事务**校验并拦截 —— 两份都批了，"该阶段该类的计划是哪一份"就没有答案；
          - 「至少一份」= **集合层面**的事实：缺计划的阶段**没有任何一条记录可以被拿来拦截**
            （没有写入动作，就没有拒绝的落点），故它落在 `coverage` 这个**查询视图**上
            （阶段 × 计划类型的覆盖矩阵，材料附录 K TABLE K-1 就是它）。
            这与同组 `technical_measure` 把 I-1 拆成「同事务写告警」+ `list_alerts` 视图**同构**。
      · **I-2 计划随阶段推进更新版本，历史版本保留** ——
        `revise` 是版本递增的**唯一**入口，且**只能从「已批准」发起**
        （没生效的计划谈不上"推进"；草稿改内容走 `update`，不动版本号）；
        每次 `approve` 在**同一次调用**里往 `plan_version` 落一行版本台账
        （版本号 / 阶段 / 成熟度 / 批准人 / 审批意见 —— 全是**当时的快照**，不回溯改写）。
        故「历史版本保留」有两重含义：**版本号只增不减**（不存在 V3 之后回到 V2），
        **旧版本行不会被后来的推进抹掉**（计划推进到 B 阶段后，A 阶段那一版仍在台账里）。

    业务规则落点：BR-01 编号唯一且不可变 / BR-02 计划与阶段（类型）绑定 + 字典 /
                 BR-03（I-1）同一阶段同一类型只允许一份已批准 / BR-04（I-2）版本只增不减、
                 历史版本保留 / BR-05 状态守卫（审批中与已批准内容锁定，各有解锁入口）/
                 BR-06 修订只能从已批准发起且必须给修订说明 / BR-07 成熟度字典 +
                 「更新」须已有获批版本 / BR-08 批准必须记名（批准人非空）。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, name: str, plan_type: str, phase: str, maturity: str = None,
               scope: str = None, owner: str = None, project_no: str = None):
        """建一份技术计划，落库为「草稿」状态、版本 `V1`，编号自动生成（`PLAN-001` 起）。

        必填三项逐个校验：名称 / 计划类型 / 覆盖阶段 —— 后两者还要过字典（BR-02，
        这是卡片 I-1「计划与阶段绑定」的落点）。`maturity`（成熟度）选填，缺省「方法」
        （材料附录 K TABLE K-1 的图例 A = Approach —— 一份刚起头的计划就是这个成熟度）。
        """
        name = self._clean(name)
        if not name:
            raise FdeError("计划名称不能为空")
        plan_type = self._check_type(plan_type)                     # BR-02
        phase = self._check_phase(phase)                            # BR-02
        mat = self._maturity(maturity)                              # BR-07
        self._check_update_maturity(mat, 0)                         # BR-07：「更新」须已有基线

        plan_no = self._next_no()
        self.db.execute(
            "INSERT INTO tech_plan (plan_no, name, plan_type, phase, maturity, version,"
            " status, scope, owner, project_no)"
            " VALUES (?, ?, ?, ?, ?, 1, 'draft', ?, ?, ?)",
            (plan_no, name, plan_type, phase, mat, self._clean(scope),
             self._clean(owner), self._clean(project_no)),
        )
        return self.get(plan_no)

    def update(self, plan_no: str, name: str = None, plan_type: str = None,
               phase: str = None, maturity: str = None, scope: str = None,
               owner: str = None, project_no: str = None):
        """修改计划的内容（名称 / 类型 / 覆盖阶段 / 成熟度 / 范围 / 责任人 / 所属项目）。

        **只在「草稿」与「已修订」两态可改**（BR-05）—— 那两态是"内容还没定下来"：
          · 「审批中」内容锁定：**审的就是这一版**，改了审批对象就变了 → 解锁入口是 `withdraw`（撤回）；
          · 「已批准」内容锁定：要改须走 `revise`（**版本递增**），不是原地改 → 解锁入口是"出下一版"。
        版本号 / 状态 / 修订说明**不在字段白名单里**：它们是流转产物（`submit` / `approve` /
        `revise` 写），没有参数可传，也就无从改起（BR-04）；编号同理（BR-01）。
        """
        cur = self._need(plan_no)
        self._check_editable(cur)                                   # BR-05

        sets, args = [], []
        if name is not None:
            name = self._clean(name)
            if not name:
                raise FdeError("计划名称不能为空")
            sets.append("name = ?")
            args.append(name)
        if plan_type is not None:
            sets.append("plan_type = ?")
            args.append(self._check_type(plan_type))                # BR-02
        if phase is not None:
            sets.append("phase = ?")
            args.append(self._check_phase(phase))                   # BR-02
        if maturity is not None:
            mat = self._maturity(maturity)                          # BR-07
            self._check_update_maturity(mat, cur["version_total"])  # BR-07
            sets.append("maturity = ?")
            args.append(mat)
        if scope is not None:
            sets.append("scope = ?")
            args.append(self._clean(scope))
        if owner is not None:
            sets.append("owner = ?")
            args.append(self._clean(owner))
        if project_no is not None:
            sets.append("project_no = ?")
            args.append(self._clean(project_no))

        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(plan_no)
        self.db.execute("UPDATE tech_plan SET " + ", ".join(sets) + " WHERE plan_no = ?",
                        tuple(args))
        return self.get(plan_no)

    def submit(self, plan_no: str):
        """提交审批：草稿 / 已修订 → 审批中（`draft|revised → in_review`）。

        提交之后内容即锁定（BR-05）—— 审批对着的必须是**定下来的那一版**。
        已批准的不能再提交（要改走 `revise`），已在审批中的不能重复提交
        （要改先 `withdraw` 撤回）。
        """
        cur = self._need(plan_no)
        # 守卫顺序 = 安全边界：最"往前走不回去"的状态排最前
        if cur["status"] == "approved":
            raise FdeError(
                f"计划 {plan_no} 已批准（第 {cur['version']} 版），不能重复提交 —— "
                "要改内容请「修订」（revise）出下一版（BR-04）")
        if cur["status"] == "in_review":
            raise FdeError(
                f"计划 {plan_no} 已经在审批中，等待批准 —— 若要改内容请先 withdraw 撤回（BR-05）")

        self.db.execute("UPDATE tech_plan SET status = 'in_review' WHERE plan_no = ?",
                        (plan_no,))
        return self.get(plan_no)

    def withdraw(self, plan_no: str, reason: str = None):
        """撤回审批：审批中 → 回到**提交前的状态**（`in_review → draft | revised`）。

        「审批中」是内容锁定态里**唯一可退回**的那一个 —— 审批人对这一版有意见时，
        退回让编制方修（改完重新 `submit`），而不是"要么批要么僵着"。
        ⚠ 回到哪一态是**推断**出来的而不是另外存的：`V1` 回「草稿」、`V2` 及以后回「已修订」
        （能走到 V2 只可能是因为 V1 曾获批并被 `revise`），这样撤回**不丢信息**。
        `reason`（撤回原因）选填，本版只作接口保留（不落库、不改版本号 —— 版本是"批准过什么"的
        台账，撤回没有产生任何被批准的版本）。
        """
        cur = self._need(plan_no)
        if cur["status"] == "approved":
            raise FdeError(
                f"计划 {plan_no} 已批准，不能撤回 —— 要改内容请「修订」（revise）出下一版（BR-04）")
        if cur["status"] != "in_review":
            raise FdeError(
                f"计划 {plan_no} 当前为「{self._status_cn(cur['status'])}」，不在审批中，无需撤回")

        target = "revised" if int(cur["version"]) > 1 else "draft"
        self.db.execute("UPDATE tech_plan SET status = ? WHERE plan_no = ?", (target, plan_no))
        return self.get(plan_no)

    def approve(self, plan_no: str, approver: str, note: str = None):
        """批准：审批中 → 已批准（`in_review → approved`）。**I-1 的「生效唯一」面落在这里。**

        三件事收在**同一次调用**里（同一连接，平台保证一个事务）：
          · **BR-08 批准要记名** —— `approver` 非空（"谁批的"必须能回答）；
          · **BR-03（I-1）生效唯一** —— 同一 `(plan_type, phase)` 下已有另一份已批准的计划时**拒绝**
            （两份都生效 ⇒ "该阶段该类的计划是哪一份"没有答案；要换就修订那一份，而不是再批一份）；
          · **BR-04（I-2）版本台账** —— 往 `plan_version` 落一行快照
            （`version` / `phase` / `maturity` / `approver` / `note`），与状态变更同事务。
            这一行就是"历史版本保留"里那个"历史版本"——**批准过的版本才有资格进台账**。
        """
        cur = self._need(plan_no)
        if cur["status"] == "approved":
            raise FdeError(f"计划 {plan_no} 已经批准（第 {cur['version']} 版），不能重复批准")
        if cur["status"] != "in_review":
            raise FdeError(
                f"计划 {plan_no} 当前为「{self._status_cn(cur['status'])}」，"
                "须先 submit 提交审批（BR-05）")

        approver = self._clean(approver)
        if not approver:
            raise FdeError("批准人不能为空 —— 批准要记名留痕（BR-08）")
        self._check_phase_unique(cur)                               # BR-03（I-1）

        self.db.execute(
            "INSERT INTO plan_version (plan_no, seq, version, phase, maturity, approver, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (plan_no, self._next_seq(plan_no), int(cur["version"]), cur["phase"],
             cur["maturity"], approver, self._clean(note)),
        )
        self.db.execute("UPDATE tech_plan SET status = 'approved' WHERE plan_no = ?", (plan_no,))
        return self.get(plan_no)

    def revise(self, plan_no: str, summary: str, phase: str = None, maturity: str = None):
        """修订（阶段推进的唯一入口）：已批准 → 已修订（`approved → revised`），**版本递增**。

        **卡片 I-2「计划随阶段推进更新版本」的落点** —— 阶段推进不是改一个字段，而是
        **出一版新的**（材料 §6.1 开篇："these plans should be updated as necessary to reflect
        the current environment and resources"；附录 K TABLE K-1 里同一份计划在 A 阶段标 P、
        在 PDR 标 B、其后标 U —— 一版一版往上走）：
          · `version` +1（只增不减，BR-04）；
          · `phase` / `maturity` **可选**随这次修订一起推进（如 A 阶段「初步」→ B 阶段「基线」，
            正对应 TABLE K-1 的 P → B）；
          · **旧版本留在 `plan_version` 台账里**（`approve` 时落的行，不因本次推进而改）。

        两条守卫（BR-06）：
          · **只能从「已批准」发起** —— 草稿/审批中改内容走 `update`（不动版本号），
            没生效的计划谈不上"推进"；已修订的（新版待提交）不能连续修订，改内容走 `update`；
          · **`summary`（修订说明）必填** —— 版本因何而升要留痕，否则两个版本的差别无从追溯。
        """
        cur = self._need(plan_no)
        if cur["status"] == "revised":
            raise FdeError(
                f"计划 {plan_no} 已修订（第 {cur['version']} 版待提交），不能连续修订 —— "
                "先 submit 提交审批，或直接 update 改这一版的内容")
        if cur["status"] != _REVISABLE:
            raise FdeError(
                f"计划 {plan_no} 当前为「{self._status_cn(cur['status'])}」，"
                "只有已批准的计划才能修订（先 submit → approve，BR-06）")

        summary = self._clean(summary)
        if not summary:
            raise FdeError("修订说明不能为空 —— 版本因何而升要留痕（BR-06）")

        new_phase = self._check_phase(phase) if self._clean(phase) else cur["phase"]  # BR-02
        # 成熟度：不传沿用当前。此处**不必**再查「更新」须已有基线 —— 能走到 revise 就说明
        # 该计划已有获批版本（_REVISABLE 的推论），`update` 才需要那条检查。
        new_mat = self._maturity(maturity) if self._clean(maturity) else cur["maturity"]

        self.db.execute(
            "UPDATE tech_plan SET version = ?, status = 'revised', revise_note = ?,"
            " phase = ?, maturity = ? WHERE plan_no = ?",
            (int(cur["version"]) + 1, summary, new_phase, new_mat, plan_no),
        )
        return self.get(plan_no)

    def get(self, plan_no: str):
        """按计划编号查询（含版本台账 `versions`）；未命中返回 None，不抛异常。

        计数 `version_total`（已获批版本数）与 `latest_approved_ver` / `latest_approver`
        与 `list` 同口径（前端"批到第几版、谁批的"都读它）。
        """
        plan_no = self._clean(plan_no)
        if not plan_no:
            return None
        row = self.db.execute(
            "SELECT " + _MAIN_COLS + " FROM tech_plan WHERE plan_no = ?", (plan_no,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["versions"] = [dict(r) for r in self.db.execute(
            "SELECT seq, version, phase, maturity, approver, note FROM plan_version"
            " WHERE plan_no = ? ORDER BY seq", (plan_no,)).fetchall()]
        out.update(self._counts(out["versions"]))
        return out

    def list(self, plan_type: str = None, phase: str = None, status: str = None,
             owner: str = None, page: int = None, size: int = None):
        """按计划类型 / 覆盖阶段 / 状态 / 责任人筛选，**分页返回 `{items, total}`**，默认按编号升序。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（见 VIEW_CONVENTION）——
        少了它们，前端拿到的 `items` 恒为空、页面静默显示空态而**不报错**（同组实测踩过）。
        返回项与 `get` 同字段口径（`_MAIN_COLS` 共用 + 同一份版本计数）；
        版本台账**明细只在 `get`**（列表不需要 N+1 取子表）。
        """
        where, args = [], []
        for col, val in (("plan_type", plan_type), ("phase", phase),
                         ("status", status), ("owner", owner)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = "SELECT " + _MAIN_COLS + " FROM tech_plan"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY plan_no"
        rows = []
        for r in self.db.execute(sql, tuple(args)).fetchall():
            d = dict(r)
            d.update(self._counts_by_no(d["plan_no"]))
            rows.append(d)

        total = len(rows)
        if size:
            p = max(int(page or 1), 1)
            n = max(int(size), 1)
            rows = rows[(p - 1) * n: p * n]
        return {"items": rows, "total": total}

    def coverage(self, phase: str = None, plan_type: str = None,
                 page: int = None, size: int = None):
        """**阶段 × 计划类型的覆盖矩阵**（查询视图，不是独立聚合）—— 卡片 I-1「每个阶段至少
        有一份已批准的该类计划」里那个「**至少一份**」面的可见落点。

        为什么要它：I-1 的「生效唯一」（`approve` 里拦"第二份已批准"）与「至少一份」
        （"这个阶段还缺哪类计划"）是**两个方向**的需求。前者是写入动作，能被同事务守卫生效；
        后者是**缺计划**——那个格子没有任何记录、没有任何写入动作可以拦截，所以它只能靠视图
        把缺口**显出来**。材料附录 K TABLE K-1「Example of Expected Maturity of Key Technical
        Plans」本身就是一张"计划 × 阶段 × 成熟度"的矩阵，本服务就是那张矩阵的可查询落点。

        逐格判定「被覆盖」（**两个来源，如实区分**）：
          · `covered_by="current"` —— 此刻就有一份 `(plan_type, phase)` 匹配、状态为「已批准」的计划
            （取编号最小者），带出它的当前版本与成熟度；
          · `covered_by="history"` —— 此刻没有，但**版本台账里**有该类型计划覆盖该阶段的获批版本
            （计划推进到新阶段后，旧阶段那一版仍在台账里 —— I-2 的"历史版本保留"由此获得意义），
            取版本号最高者；
          · `covered_by=""` —— 两处都没有，**这一格就是缺口**。
        `plan_count` 是**计划主档**里此刻声明覆盖该阶段的该类计划数（批没批都算）——
        它可以是 0 而格子仍被覆盖（那就是 `history` 那一支）。

        `page`/`size` 与 `{items, total}` 契约与 `list` 同口径。
        """
        ph_f = self._clean(phase)
        pt_f = self._clean(plan_type)
        rows = []
        for ph in PHASES:
            if ph_f and ph_f != ph:
                continue
            for pt in PLAN_TYPES:
                if pt_f and pt_f != pt:
                    continue
                rows.append(self._coverage_cell(ph, pt))

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
    def _status_cn(status: str) -> str:
        return _STATUS_CN.get(status, status or "—")

    @staticmethod
    def _check_type(plan_type: str) -> str:
        """计划类型非空 + 过字典（BR-02）。返回清洗后的值，供写入。

        ⚠ 先 `_clean` 再判空再查字典 —— 漏了 clean 会把 `"  "` 当真值，
        报错文案会变成"只能是 X"而不是"不能为空"（同组实测踩过）。
        """
        t = TechPlan._clean(plan_type)
        if not t:
            raise FdeError("计划类型不能为空")
        if t not in PLAN_TYPES:
            raise FdeError(f"计划类型只能是 {'/'.join(PLAN_TYPES)} 之一（BR-02）")
        return t

    @staticmethod
    def _check_phase(phase: str) -> str:
        """覆盖阶段非空 + 过字典（BR-02，卡片 I-1「计划与阶段绑定」的落点）。"""
        p = TechPlan._clean(phase)
        if not p:
            raise FdeError("覆盖阶段不能为空 —— 计划与阶段绑定（I-1 / BR-02）")
        if p not in PHASES:
            raise FdeError(f"覆盖阶段只能是 {'/'.join(PHASES)} 之一（BR-02）")
        return p

    @staticmethod
    def _maturity(maturity: str) -> str:
        """成熟度：空则取缺省「方法」，非空则须过字典（BR-07，附录 K 图例 A/P/B/U）。"""
        m = TechPlan._clean(maturity) or DEFAULT_MATURITY
        if m not in MATURITIES:
            raise FdeError(f"成熟度只能是 {'/'.join(MATURITIES)} 之一（BR-07）")
        return m

    @staticmethod
    def _check_update_maturity(maturity: str, version_total: int):
        """BR-07：「更新」（update）这一成熟度**以已有基线版本为前提**。

        依据附录 K TABLE K-1 的图例：`A = Approach / B = Baseline / P = Preliminary /
        U = Update` —— U 出现在同一份计划**已经过 P/B 之后**的各个阶段（如 SEMP 在 SDR/MDR
        标 P、PDR 标 B、其后一律 U）。一份**从未获批过任何版本**的计划谈不上"更新"
        （没有"旧"可更），此时它最多是「方法」或「初步」。
        """
        if maturity == "update" and not version_total:
            raise FdeError(
                "成熟度「更新」以已有基线版本为前提 —— 本计划还没有获批过任何版本，"
                "谈不上更新（附录 K 图例：U = Update，BR-07）")

    def _check_phase_unique(self, cur: dict):
        """BR-03（卡片 I-1 的「生效唯一」面）：同一阶段同一类型只允许一份「已批准」。

        两份都批准 ⇒ "该阶段该类的计划是哪一份"没有答案（附录 K TABLE K-1 每格只有一个成熟度）。
        要换计划就**修订那一份**（版本递增），而不是再批一份新的。
        """
        row = self.db.execute(
            "SELECT plan_no, version, name FROM tech_plan WHERE plan_type = ? AND phase = ?"
            " AND status = 'approved' AND plan_no <> ? ORDER BY plan_no",
            (cur["plan_type"], cur["phase"], cur["plan_no"]),
        ).fetchone()
        if row:
            raise FdeError(
                f"计划 {cur['plan_no']} 不能批准：{self._phase_cn(cur['phase'])}的"
                f"「{cur['plan_type']}」类计划已有已批准的 {row['plan_no']}"
                f"（{row['name']} · 第 {row['version']} 版）—— "
                "同一阶段同一类型只允许一份生效（I-1 / BR-03），"
                "要换计划请修订那一份（版本递增）")

    @staticmethod
    def _phase_cn(phase: str) -> str:
        return _PHASE_CN.get(phase, phase or "—")

    @staticmethod
    def _counts(versions: list):
        """由版本台账推导 3 个派生字段 —— `get` 与 `list` **共用同一算法**（口径不漂移）。

        `latest_approved_ver` / `latest_approver` 取**版本号最高**的那一行
        （版本号只增不减，故它就是最近批准的那一版）。
        """
        latest = None
        for v in versions:
            if latest is None or int(v["version"]) >= int(latest["version"]):
                latest = v
        return {"version_total": len(versions),
                "latest_approved_ver": int(latest["version"]) if latest else None,
                "latest_approver": latest["approver"] if latest else None}

    def _counts_by_no(self, plan_no: str):
        rows = [dict(r) for r in self.db.execute(
            "SELECT version, approver FROM plan_version WHERE plan_no = ? ORDER BY seq",
            (plan_no,)).fetchall()]
        return self._counts(rows)

    def _coverage_cell(self, phase: str, plan_type: str) -> dict:
        """覆盖矩阵的一格：先看"此刻已批准"，再看"版本台账里曾获批"，都没有就是缺口。"""
        cnt = self.db.execute(
            "SELECT COUNT(*) AS n FROM tech_plan WHERE plan_type = ? AND phase = ?",
            (plan_type, phase),
        ).fetchone()
        cell = {"phase": phase, "plan_type": plan_type, "covered": 0, "covered_by": "",
                "plan_count": int(cnt["n"] or 0), "approved_no": None,
                "approved_ver": None, "approved_maturity": None}

        cur = self.db.execute(
            "SELECT plan_no, version, maturity FROM tech_plan"
            " WHERE plan_type = ? AND phase = ? AND status = 'approved'"
            " ORDER BY plan_no LIMIT 1", (plan_type, phase),
        ).fetchone()
        if cur:
            cell.update({"covered": 1, "covered_by": "current", "approved_no": cur["plan_no"],
                         "approved_ver": int(cur["version"]),
                         "approved_maturity": cur["maturity"]})
            return cell

        hist = self.db.execute(
            "SELECT v.plan_no, v.version, v.maturity FROM plan_version v"
            " JOIN tech_plan p ON p.plan_no = v.plan_no"
            " WHERE p.plan_type = ? AND v.phase = ?"
            " ORDER BY v.version DESC, v.plan_no LIMIT 1", (plan_type, phase),
        ).fetchone()
        if hist:
            cell.update({"covered": 1, "covered_by": "history", "approved_no": hist["plan_no"],
                         "approved_ver": int(hist["version"]),
                         "approved_maturity": hist["maturity"]})
        return cell

    @staticmethod
    def _check_editable(cur: dict):
        """BR-05：内容锁定的两个状态各有自己的解锁入口 —— 报错文案**直接点名那个入口**。"""
        if cur["status"] == "in_review":
            raise FdeError(
                f"计划 {cur['plan_no']} 正在审批中，内容已锁定 —— 审的就是这一版；"
                "要改请先 withdraw 撤回（BR-05）")
        if cur["status"] == "approved":
            raise FdeError(
                f"计划 {cur['plan_no']} 已批准（第 {cur['version']} 版），内容不可直接修改 —— "
                "要改请「修订」（revise）出下一版（BR-04 / BR-05）")

    def _need(self, plan_no: str):
        plan_no = self._clean(plan_no)
        if not plan_no:
            raise FdeError("计划编号不能为空")
        cur = self.get(plan_no)
        if not cur:
            raise FdeError(f"计划 {plan_no} 不存在")
        return cur

    def _next_no(self) -> str:
        """生成下一个计划编号：PLAN-<三位序号>（BR-01：编号唯一且不可变）。"""
        rows = self.db.execute("SELECT plan_no FROM tech_plan").fetchall()
        mx = 0
        for r in rows:
            m = re.match(r"^PLAN-(\d+)$", str(r["plan_no"]))
            if m:
                mx = max(mx, int(m.group(1)))
        return f"PLAN-{mx + 1:03d}"

    def _next_seq(self, plan_no: str) -> int:
        """聚合内子表的序号：本计划内递增（`(plan_no, seq)` 是复合主键，无全局标识）。"""
        rows = self.db.execute("SELECT seq FROM plan_version WHERE plan_no = ?",
                               (plan_no,)).fetchall()
        mx = 0
        for r in rows:
            mx = max(mx, int(r["seq"]))
        return mx + 1
