from __future__ import annotations

import re

from fde import FdeError

# 状态字典（材料 §6.5.1.2.3 Manage Configuration Change Control 与 FIGURE 6.5-4 的
# 「Normal Configuration Change Process」）：提交 → 影响分析 → 审批中 → 已批准 / 已拒绝 → 已实施。
# ⚠ **状态不是入参** —— 六个值全部由状态机服务写入，故没有"状态字典校验"（不需要 STATUSES 元组）；
#    本表的键集即全部合法状态，中文名用于错误信息与前端徽标（前端另有一份同值映射）。
STATUS_CN = {"submitted": "已提交", "analyzing": "影响分析", "reviewing": "审批中",
             "approved": "已批准", "rejected": "已拒绝", "implemented": "已实施"}
# 硬终态：已拒绝（审批不通过）与已实施（变更已落地）——到达后任何动作一律拒绝（BR-04）
_TERMINAL = ("rejected", "implemented")
# 影响范围里不允许出现的对象状态（跨应用校验，BR-07）：
#   配置项「已归档」是终态（configuration_item 的 BR-02）；需求「已废弃」是终态（requirement 的 BR-04）
_CI_FROZEN = "archived"
_REQ_FROZEN = "obsolete"
# get / list 的**同一份**列清单 —— 两处口径必须一致（CONVENTION §7：list 不得只 SELECT 子集）
_COLS = ("cr_no, title, requester, ci_nos, req_nos, description, impact_analysis,"
         " decision_note, approver, implement_note, status, project_no")


class ChangeRequest:
    """变更请求聚合根。对配置项 / 基线的变更申请，含影响分析、审批意见与实施记录。
    数据来源类型：独立创建（提出人登记，无上游自动生成）。

    一致性边界（见 `architecture.md` 聚合根卡 4）：
      · **I-1 变更必须指明影响范围**（配置项或需求至少一个）—— 由本聚合内 `ci_nos` / `req_nos`
        承载；影响范围的**存在性与可用性**跨应用校验（`configuration_item.list` /
        `requirement.list`，只读、非同一事务，见 §6.3）；
      · **I-2 审批与影响分析同事务落库**（不允许"先批后分析"）—— 落地方式是**状态门**：
        审批（`approve` / `reject`）只接受 `reviewing`，而 `reviewing` 只能由 `submit_review`
        到达、`submit_review` 又只接受 `analyzing`（即 `analyze` 已把影响分析写进本聚合）。
        于是"没有影响分析却能审批"在状态机上不可达；审批意见与状态在**同一条 UPDATE** 里落库。
      · **实施（`implement`）不在本聚合改动配置项** —— 材料 FIGURE 6.5-4 第 9 步
        "Execute approved changes" 由配置项侧执行（`configuration_item.bump_version(ci_no, n, cr_no)`），
        本聚合只记录"这次变更已实施"，**不做跨应用写**（跨应用无分布式事务，§8）。

    业务规则落点：BR-01 必须指明影响范围 / BR-02 审批须有影响分析且审批意见必填 /
                 BR-03 编号唯一且不可变 / BR-04 状态机单向、终态不可再动 /
                 BR-05 影响范围的对象必须存在（跨应用）/ BR-06 内容只在「已提交」可改 /
                 BR-07 已归档配置项、已废弃需求不得再作为影响范围（跨应用）。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, title: str, requester: str, ci_nos=None, req_nos=None,
               description: str = None, project_no: str = None):
        """提交一条变更请求（落库为 `submitted`「已提交」）。

        两条不变量在入口就把住：
          · **BR-01 必须指明影响范围** —— 配置项与需求**至少有一个**（材料 §6.5.1.2.3：
            变更须经 "systematic proposal, justification, and evaluation"，影响范围是评估的对象；
            聚合根卡 4 的 I-1）；
          · **BR-05 / BR-07 影响范围必须真实可用** —— 逐个校验配置项 / 需求存在，
            且**不得是终态对象**（已归档配置项、已废弃需求不能再被变更驱动）。

        `ci_nos` / `req_nos` 接受**列表或逗号分隔文本**（全角逗号也认），重复项自动去重。
        """
        title = self._clean(title)
        requester = self._clean(requester)
        if not title:
            raise FdeError("变更请求标题不能为空")
        if not requester:
            raise FdeError("申请方不能为空")
        cis = self._codes(ci_nos)
        reqs = self._codes(req_nos)
        self._check_scope(cis, reqs)                                  # BR-01
        self._assert_scope(cis, reqs)                                 # BR-05 / BR-07（跨应用）

        cr_no = self._next_no()
        self.db.execute(
            "INSERT INTO change_request (cr_no, title, requester, ci_nos, req_nos,"
            " description, status, project_no)"
            " VALUES (?, ?, ?, ?, ?, ?, 'submitted', ?)",
            (cr_no, title, requester, self._join(cis), self._join(reqs),
             self._clean(description), self._clean(project_no)),
        )
        return self.get(cr_no)

    def analyze(self, cr_no: str, impact_analysis: str):
        """登记影响分析：`submitted → analyzing`（提交 → 影响分析）。

        影响分析是审批的**唯一前置**（BR-02）：材料 FIGURE 6.5-4 第 3~4 步要求评审人
        "Review and submit comments"、CM 侧 "Collect, track, and adjudicate comments"，
        没有分析材料的变更请求进不了 CCB。
        """
        cur = self._need(cr_no)
        self._check_terminal(cur)                                     # BR-04（硬终态最先拦）
        if cur["status"] != "submitted":
            raise FdeError(
                f"变更请求 {cr_no} 当前为「{STATUS_CN.get(cur['status'], cur['status'])}」，"
                "只有已提交的变更请求才能登记影响分析")
        impact_analysis = self._clean(impact_analysis)
        if not impact_analysis:
            raise FdeError("影响分析不能为空（BR-02）")
        self.db.execute(
            "UPDATE change_request SET impact_analysis = ?, status = 'analyzing'"
            " WHERE cr_no = ?", (impact_analysis, cr_no))
        return self.get(cr_no)

    def submit_review(self, cr_no: str):
        """提交审批：`analyzing → reviewing`（影响分析 → 审批中）。

        "Schedule CCB and prepare agenda"（材料 FIGURE 6.5-4 第 5 步，CM Function）——
        分析做完后由 CM 把变更送上审批。**这是"审批中"的唯一入口**，
        故 BR-02 的"先批后分析"在状态机上不可达。
        """
        cur = self._need(cr_no)
        self._check_terminal(cur)                                     # BR-04
        if cur["status"] != "analyzing":
            raise FdeError(
                f"变更请求 {cr_no} 当前为「{STATUS_CN.get(cur['status'], cur['status'])}」，"
                "只有已完成影响分析的变更请求才能提交审批（BR-02）")
        if not cur["impact_analysis"]:
            # 状态即契约的兜底断言：analyzing 必然带影响分析，缺了就是数据被绕过写入
            raise FdeError(f"变更请求 {cr_no} 尚未登记影响分析，不能提交审批（BR-02）")
        self.db.execute("UPDATE change_request SET status = 'reviewing' WHERE cr_no = ?",
                        (cr_no,))
        return self.get(cr_no)

    def approve(self, cr_no: str, comment: str, approver: str = None):
        """批准：`reviewing → approved`（审批中 → 已批准）。

        **BR-02 审批与影响分析同事务落库**：本服务只接受 `reviewing`（其唯一入口
        `submit_review` 又只接受 `analyzing`）⇒ 没有影响分析的变更请求**无法到达审批**；
        审批意见、审批人与状态在**同一条 UPDATE** 里写入（平台事务，§8）。
        审批意见必填 —— 没有意见的"批准"在材料 FIGURE 6.5-4 第 7 步
        "Prepare decision package / Disposition change request" 里不成立。
        """
        return self._dispose(cr_no, "approved", comment, approver)

    def reject(self, cr_no: str, comment: str, approver: str = None):
        """拒绝：`reviewing → rejected`（审批中 → 已拒绝，**终态**）。

        与 `approve` 同源（同一私有实现 `_dispose`）：唯一差别是落到哪个状态。
        拒绝即终态 —— 材料要求变更请求留痕（FIGURE 6.5-4 第 8b 步 "Release CCB minutes"），
        记录不删除，但也不能被复用于实施。
        """
        return self._dispose(cr_no, "rejected", comment, approver)

    def implement(self, cr_no: str, note: str = None):
        """实施：`approved → implemented`（已批准 → 已实施，**终态**）。

        材料 FIGURE 6.5-4 第 9 步 "Execute approved changes"：**只有已批准的变更**可以执行
        （已拒绝、审批中、影响分析中的一律拒绝）。执行动作本身落在配置项侧
        （`configuration_item.bump_version(ci_no, n, cr_no)`），本聚合只登记"已实施"。
        """
        cur = self._need(cr_no)
        self._check_terminal(cur)                                     # BR-04
        if cur["status"] != "approved":
            raise FdeError(
                f"变更请求 {cr_no} 当前为「{STATUS_CN.get(cur['status'], cur['status'])}」，"
                "只有已批准的变更请求才能实施（BR-04）")
        self.db.execute(
            "UPDATE change_request SET status = 'implemented', implement_note = ?"
            " WHERE cr_no = ?", (self._clean(note), cr_no))
        return self.get(cr_no)

    def update(self, cr_no: str, title: str = None, requester: str = None, ci_nos=None,
               req_nos=None, description: str = None):
        """修改变更请求内容（标题 / 申请方 / 影响范围 / 变更说明）。

        **BR-06 内容只在「已提交」可改** —— 影响分析一旦登记，分析结论针对的就是当时那份
        影响范围；若审批前还能改范围，"影响分析"与"被分析的对象"就对不上了。
        故进入 `analyzing` 之后（含审批中、已批准）内容一律锁定，改范围须另提一条变更请求。

        **编号不在字段白名单里**（BR-03：`cr_no` 无参数可传，落库不可变）。
        影响范围改后仍要重过 BR-01（改完不能一个都不剩）与 BR-05 / BR-07（存在且非终态）。
        """
        cur = self._need(cr_no)
        self._check_terminal(cur)                                     # BR-04
        if cur["status"] != "submitted":
            raise FdeError(
                f"变更请求 {cr_no} 当前为「{STATUS_CN.get(cur['status'], cur['status'])}」，"
                "只有已提交的变更请求才能修改（影响分析登记后内容即定型，BR-06）")

        sets, args = [], []
        if title is not None:
            title = self._clean(title)
            if not title:
                raise FdeError("变更请求标题不能为空")
            sets.append("title = ?")
            args.append(title)
        if requester is not None:
            requester = self._clean(requester)
            if not requester:
                raise FdeError("申请方不能为空")
            sets.append("requester = ?")
            args.append(requester)
        if description is not None:
            sets.append("description = ?")
            args.append(self._clean(description))
        # 影响范围：只改传了的那一侧，另一侧取当前值 —— 校验的是**改完之后**的整体范围
        if ci_nos is not None or req_nos is not None:
            cis = self._codes(ci_nos) if ci_nos is not None else cur["ci_nos"]
            reqs = self._codes(req_nos) if req_nos is not None else cur["req_nos"]
            self._check_scope(cis, reqs)                              # BR-01
            self._assert_scope(cis, reqs)                             # BR-05 / BR-07
            if ci_nos is not None:
                sets.append("ci_nos = ?")
                args.append(self._join(cis))
            if req_nos is not None:
                sets.append("req_nos = ?")
                args.append(self._join(reqs))
        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(cr_no)
        self.db.execute("UPDATE change_request SET " + ", ".join(sets) + " WHERE cr_no = ?",
                        tuple(args))
        return self.get(cr_no)

    def get(self, cr_no: str):
        """按变更请求编号查询；未命中返回 None，不抛异常。

        `ci_nos` / `req_nos` 落库是逗号分隔文本，**返回时解析成列表**（与 `list` 同口径）。
        """
        cr_no = self._clean(cr_no)
        if not cr_no:
            return None
        row = self.db.execute("SELECT " + _COLS + " FROM change_request WHERE cr_no = ?",
                              (cr_no,)).fetchone()
        return self._to_dict(row) if row else None

    def list(self, status: str = None, requester: str = None, ci_no: str = None,
             req_no: str = None, page: int = None, size: int = None):
        """按状态 / 申请方 / 影响的配置项 / 影响的需求筛选，**分页返回 `{items, total}`**，
        默认按编号升序。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（见 VIEW_CONVENTION）——
        少了它们，前端拿到的 `items` 恒为空、页面静默显示空态而**不报错**（同组实测踩过）。
        返回项与 `get` **同口径（全字段）**；列表只显示关键列是**视图层**的事。

        `ci_no` / `req_no` 是**成员筛选**（"影响范围里包含该编号"）：落库值是逗号分隔文本，
        用 LIKE 判边界易错（`CI-001` 会命中 `CI-0011`），故在取回后按列表成员判定，
        `total` 也按**筛选后**的全量行数计。
        """
        where, args = [], []
        for col, val in (("status", status), ("requester", requester)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = "SELECT " + _COLS + " FROM change_request"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY cr_no"
        rows = [self._to_dict(r) for r in self.db.execute(sql, tuple(args)).fetchall()]

        ci_no, req_no = self._clean(ci_no), self._clean(req_no)
        if ci_no:
            rows = [r for r in rows if ci_no in r["ci_nos"]]
        if req_no:
            rows = [r for r in rows if req_no in r["req_nos"]]

        total = len(rows)
        if size:
            p = max(int(page or 1), 1)
            n = max(int(size), 1)
            rows = rows[(p - 1) * n: p * n]
        return {"items": rows, "total": total}

    # ── 私有（非服务） ────────────────────────────────────

    def _dispose(self, cr_no: str, status: str, comment: str, approver):
        """approve / reject 的同一实现（差别只在落到哪个状态，避免两处守卫漂移）。"""
        cur = self._need(cr_no)
        self._check_terminal(cur)                                     # BR-04（硬终态最先拦）
        if cur["status"] != "reviewing":
            raise FdeError(
                f"变更请求 {cr_no} 当前为「{STATUS_CN.get(cur['status'], cur['status'])}」，"
                "只有审批中的变更请求才能审批（先登记影响分析并提交审批，BR-02）")
        if not cur["impact_analysis"]:
            raise FdeError(f"变更请求 {cr_no} 没有影响分析，不能审批（BR-02）")
        comment = self._clean(comment)
        if not comment:
            raise FdeError("审批意见不能为空（BR-02）")
        self.db.execute(
            "UPDATE change_request SET status = ?, decision_note = ?, approver = ?"
            " WHERE cr_no = ?", (status, comment, self._clean(approver), cr_no))
        return self.get(cr_no)

    @staticmethod
    def _clean(v):
        return str(v).strip() if v is not None else ""

    def _to_dict(self, row):
        """行 → 业务值：影响范围两列由逗号分隔文本解析成列表（get / list 共用，保证同口径）。"""
        d = dict(row)
        d["ci_nos"] = self._codes(d.get("ci_nos"))
        d["req_nos"] = self._codes(d.get("req_nos"))
        return d

    @staticmethod
    def _codes(v):
        """把「列表 / 逗号分隔文本 / 单个编号」统一解析成**去重保序**的编号列表。

        容错点：全角逗号（中文输入法）与空白一律归一；空串/None → 空列表。
        """
        if v is None:
            return []
        if isinstance(v, (list, tuple, set)):
            raw = [str(x) for x in v]
        else:
            raw = str(v).replace("，", ",").split(",")
        out = []
        for x in raw:
            x = x.strip()
            if x and x not in out:
                out.append(x)
        return out

    @staticmethod
    def _join(codes) -> str:
        return ",".join(codes)

    @staticmethod
    def _check_scope(cis, reqs):
        """BR-01：变更必须指明影响范围（配置项与需求至少一个）。"""
        if not cis and not reqs:
            raise FdeError("变更必须指明影响范围：至少选择一个配置项或一条需求（BR-01）")

    def _assert_scope(self, cis, reqs):
        """BR-05 / BR-07：影响范围的对象必须存在，且不得是终态（跨应用只读校验）。"""
        if cis:
            idx = self._ci_index()
            for no in cis:
                row = idx.get(no)
                if not row:
                    raise FdeError(f"影响的配置项 {no} 不存在，请先在配置项台账中登记（BR-05）")
                if row.get("status") == _CI_FROZEN:
                    raise FdeError(
                        f"配置项 {no} 已归档（终态），不能再作为变更的影响范围（BR-07）")
        if reqs:
            idx = self._req_index()
            for no in reqs:
                row = idx.get(no)
                if not row:
                    raise FdeError(f"影响的需求 {no} 不存在，请先在需求台账中录入（BR-05）")
                if row.get("status") == _REQ_FROZEN:
                    raise FdeError(
                        f"需求 {no} 已废弃（终态），不能再作为变更的影响范围（BR-07）")

    def _ci_index(self) -> dict:
        """跨应用读一次 `configuration_item.list` → `{ci_no: 行}`（只读、非同一事务，§8）。

        ⚠ **目标应用名必须是字面量**（`self.fde.call("configuration_item", "list")`）——
        静态扫描器据此校验跨应用契约（CONVENTION §10.8）；写成变量会退化成
        "动态目标，需人工确认"的告警，把契约校验让位给运行期。
        故两个索引各自成法（不抽公共 `_fetch(app, …)` 造成变量名），代价是两处 try/except。
        """
        try:
            res = self.fde.call("configuration_item", "list")
        except FdeError as e:
            raise FdeError(f"影响范围校验失败：配置项台账不可用（{e}）") from None
        except Exception:
            raise FdeError("影响范围校验失败：配置项台账不可用") from None
        return self._index(res, "ci_no")

    def _req_index(self) -> dict:
        """跨应用读一次 `requirement.list` → `{req_no: 行}`（只读、非同一事务，§8）。"""
        try:
            res = self.fde.call("requirement", "list")
        except FdeError as e:
            raise FdeError(f"影响范围校验失败：需求台账不可用（{e}）") from None
        except Exception:
            raise FdeError("影响范围校验失败：需求台账不可用") from None
        return self._index(res, "req_no")

    @staticmethod
    def _index(res, key: str) -> dict:
        """`{items,total}` → `{编号: 行}`（`list` 的契约形状，CONVENTION §7）。"""
        items = (res or {}).get("items") or []
        return {r.get(key): r for r in items if r.get(key)}

    def _need(self, cr_no: str):
        cr_no = self._clean(cr_no)
        if not cr_no:
            raise FdeError("变更请求编号不能为空")
        cur = self.get(cr_no)
        if not cur:
            raise FdeError(f"变更请求 {cr_no} 不存在")
        return cur

    @staticmethod
    def _check_terminal(cur: dict):
        """BR-04：硬终态（已拒绝 / 已实施）——**所有动作的最前置守卫**，先于状态门。"""
        if cur["status"] in _TERMINAL:
            raise FdeError(
                f"变更请求 {cur['cr_no']} 已处于终态「{STATUS_CN.get(cur['status'], cur['status'])}」，"
                "不能再操作（BR-04）")

    def _next_no(self) -> str:
        """生成下一个变更请求编号：CR-<三位序号>（BR-03：编号唯一）。"""
        rows = self.db.execute("SELECT cr_no FROM change_request").fetchall()
        mx = 0
        for r in rows:
            m = re.match(r"^CR-(\d+)$", str(r["cr_no"]))
            if m:
                mx = max(mx, int(m.group(1)))
        return f"CR-{mx + 1:03d}"
