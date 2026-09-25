from __future__ import annotations

import re

from fde import FdeError

TYPES = ("system", "technical", "interface", "derived")
METHODS = ("inspection", "analysis", "demonstration", "test")
# 未基线即为这些状态之一；baselined 才受 BR-04 保护
_UNBASELINED = ("draft", "pending_review")
# 状态中文名（错误话术用；与前端 `view.js` 的 STATUS 字典同口径）
_STATUS_CN = {"draft": "草稿", "pending_review": "待评审", "baselined": "已基线",
              "obsolete": "已废弃"}


class Requirement:
    """需求聚合根。一条待满足的技术要求，含派生链与验证方法。数据来源类型：独立创建。

    一致性边界（见 `architecture.md` 聚合根卡 1）：
      · 需求与其派生链同事务维护（改上游要能看到下游）—— 故派生关系存本聚合内；
      · 「纳入基线」是整批操作：**全或无**，任一条缺验证方法则整批拒绝（BR-01）；
      · 验证的执行与结果**不在本聚合**（属 `verification` 应用），本应用只维护验证方法。

    业务规则落点：BR-01 必须有验证方法 / BR-02 派生须有上游 / BR-03 编号不可变 /
                 BR-04 已基线不得直接改写 / BR-05 类型受字典约束。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, title: str, statement: str, req_type: str,
               verify_method: str, source_req_no: str = None,
               owner: str = None, project_no: str = None):
        """新建一条需求，落库为草稿状态。"""
        title = self._clean(title)
        statement = self._clean(statement)
        req_type = self._clean(req_type)
        verify_method = self._clean(verify_method)
        if not title:
            raise FdeError("需求标题不能为空")
        if not statement:
            # 正文是需求的实质（材料附录 C：需求必须是可验证的陈述）—— 只有标题的需求不是需求
            raise FdeError("需求正文不能为空")
        self._check_type(req_type)
        self._check_method(verify_method)                       # BR-01
        source_req_no = self._clean(source_req_no)
        self._check_source(req_type, source_req_no)             # BR-02

        req_no = self._next_no(project_no)
        self.db.execute(
            "INSERT INTO requirement (req_no, title, statement, req_type, verify_method,"
            " source_req_no, status, owner, project_no)"
            " VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
            (req_no, title, statement, req_type, verify_method,
             source_req_no, self._clean(owner), self._clean(project_no)),
        )
        return self.get(req_no)

    def submit_review(self, req_no: str):
        """把草稿提交评审：`draft` → `pending_review`（2026-09-25 补）。

        为什么必须补：§3.4 状态机里 `pending_review` 是**纳入基线前的门**（材料 §4.2 的
        "requirements review/approval"），而此前**没有任何服务能进入这个状态** —— 状态机画着、
        前端筛选项列着，实际永远筛出空，属"声明了但走不到"。

        守卫顺序（负例期望按此对齐）：存在性 → 终态(已废弃) → **状态（只有草稿可提交）**。
        """
        cur = self.get(req_no)
        if not cur:
            raise FdeError(f"需求 {req_no} 不存在")
        if cur["status"] == "obsolete":
            raise FdeError(f"需求 {req_no} 已废弃，不能提交评审")
        if cur["status"] != "draft":
            raise FdeError(
                f"需求 {req_no} 当前为「{_STATUS_CN.get(cur['status'], cur['status'])}」，"
                "只有草稿可以提交评审"
            )
        self.db.execute("UPDATE requirement SET status = 'pending_review' WHERE req_no = ?", (req_no,))
        return self.get(req_no)

    def derive(self, source_req_no: str, title: str, statement: str,
               verify_method: str, owner: str = None):
        """从上游需求派生一条新需求（派生的便捷入口，等价于 create 且类型为 derived）。"""
        source_req_no = self._clean(source_req_no)
        if not source_req_no or not self.get(source_req_no):
            raise FdeError(f"上游需求 {source_req_no} 不存在，不能派生")
        return self.create(title, statement, "derived", verify_method,
                           source_req_no=source_req_no, owner=owner)

    def update(self, req_no: str, title: str = None, statement: str = None,
               verify_method: str = None, owner: str = None,
               change_no: str = None):
        """修改需求内容。

        已基线（`baselined`）的需求**不得直接改写**，必须携带已批准的变更号（BR-04）——
        本应用只能校验「是否带了变更号」，**变更是否已批准由 `change_request` 应用保证**
        （该应用建成后应改为跨应用校验，见详设 §6.3）。
        """
        cur = self.get(req_no)
        if not cur:
            raise FdeError(f"需求 {req_no} 不存在")
        if cur["status"] not in _UNBASELINED:
            if not self._clean(change_no):
                raise FdeError("已基线的需求不能直接修改，请先提交变更请求（BR-04）")
            self.db.execute("UPDATE requirement SET change_no = ? WHERE req_no = ?",
                            (self._clean(change_no), req_no))

        sets, args = [], []
        if title is not None:
            title = self._clean(title)
            if not title:
                raise FdeError("需求标题不能为空")
            sets.append("title = ?")
            args.append(title)
        if statement is not None:
            sets.append("statement = ?")
            args.append(statement)
        if verify_method is not None:
            verify_method = self._clean(verify_method)
            self._check_method(verify_method)                   # BR-01
            sets.append("verify_method = ?")
            args.append(verify_method)
        if owner is not None:
            sets.append("owner = ?")
            args.append(self._clean(owner))
        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(req_no)
        self.db.execute("UPDATE requirement SET " + ", ".join(sets) + " WHERE req_no = ?", tuple(args))
        return self.get(req_no)

    def baseline(self, req_nos, baseline_ver: str):
        """把一批需求冻结为一个基线版本 —— **全或无**：任一条不满足 BR-01 则整批拒绝。"""
        baseline_ver = self._clean(baseline_ver)
        if not baseline_ver:
            raise FdeError("基线版本号不能为空")
        req_nos = [self._clean(x) for x in (req_nos or []) if self._clean(x)]
        if not req_nos:
            raise FdeError("请至少选择一条需求纳入基线")

        rows = []
        for no in req_nos:
            cur = self.get(no)
            if not cur:
                raise FdeError(f"需求 {no} 不存在，整批未纳入基线")
            # BR-01 在基线这一刻被强制：无验证方法的需求不能进基线
            if not cur["verify_method"]:
                raise FdeError(f"需求 {no} 没有验证方法，不能纳入基线（BR-01）")
            if cur["status"] == "obsolete":
                raise FdeError(f"需求 {no} 已废弃，不能纳入基线")
            # **评审门**（§3.4：pending_review → baseline）：草稿不能直接进基线 ——
            # 否则 `pending_review` 又变成一个装饰状态（2026-09-25 补 `submit_review` 时一并收紧）
            if cur["status"] != "pending_review":
                raise FdeError(
                    f"需求 {no} 当前为「{_STATUS_CN.get(cur['status'], cur['status'])}」，"
                    "须先提交评审（`submit_review`）才能纳入基线"
                )
            rows.append(cur)

        for cur in rows:                                        # 校验全通过后才落库
            self.db.execute(
                "UPDATE requirement SET status = 'baselined', baseline_ver = ? WHERE req_no = ?",
                (baseline_ver, cur["req_no"]),
            )
        return {"baseline_ver": baseline_ver, "count": len(rows),
                "req_nos": [r["req_no"] for r in rows]}

    def obsolete(self, req_no: str, reason: str = None):
        """作废一条需求（状态机允许任意状态转 obsolete）。

        作废后**不删除**：派生它的下游需求仍要能看到它的编号与状态（BR-02 的不悬空要求）。
        `reason` **落库**到 `void_reason`（2026-09-25 起留痕）：作废是要交代理由的动作，
        与同组 `risk.close` / `review.close` 的 `close_note` 同口径。
        """
        cur = self.get(req_no)
        if not cur:
            raise FdeError(f"需求 {req_no} 不存在")
        if cur["status"] == "obsolete":
            raise FdeError(f"需求 {req_no} 已经是废弃状态")
        self.db.execute("UPDATE requirement SET status = 'obsolete', void_reason = ? WHERE req_no = ?",
                        (self._clean(reason) or None, req_no))
        return self.get(req_no)

    def get(self, req_no: str):
        """按需求编号查询；未命中返回 None，不抛异常。"""
        req_no = self._clean(req_no)
        if not req_no:
            return None
        row = self.db.execute(
            "SELECT req_no, title, statement, req_type, verify_method, source_req_no,"
            " status, owner, project_no, baseline_ver, change_no, void_reason"
            " FROM requirement WHERE req_no = ?", (req_no,),
        ).fetchone()
        return dict(row) if row else None

    def list(self, req_type: str = None, status: str = None, source_req_no: str = None,
             page: int = None, size: int = None):
        """按类型 / 状态 / 上游需求筛选，**分页返回 `{items, total}`**，默认按编号升序。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（见 VIEW_CONVENTION）——
        少了它们，前端拿到的 `items` 恒为空、页面显示空态而**不报错**（实测踩过：
        后端返回裸数组时，页面静默显示「暂无数据」）。
        """
        where, args = [], []
        for col, val in (("req_type", req_type), ("status", status),
                         ("source_req_no", source_req_no)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        # ⚠ 列出**与 get 同口径的全字段**（CONVENTION §7/§13）：只 SELECT 子集会让
        # "从列表直接渲染字段"的页面拿不到 statement/baseline_ver/change_no 而显示空白。
        sql = ("SELECT req_no, title, statement, req_type, verify_method, source_req_no,"
               " status, owner, project_no, baseline_ver, change_no, void_reason"
               " FROM requirement")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY req_no"
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

    def _check_type(self, req_type: str):
        if req_type not in TYPES:
            raise FdeError(f"需求类型只能是 {'/'.join(TYPES)} 之一（BR-05）")

    @staticmethod
    def _check_method(verify_method: str):
        if not verify_method:
            raise FdeError("需求必须有验证方法（BR-01）")
        if verify_method not in METHODS:
            raise FdeError(f"验证方法只能是 {'/'.join(METHODS)} 之一")

    def _check_source(self, req_type: str, source_req_no: str):
        if req_type == "derived" and not source_req_no:
            raise FdeError("派生需求必须填写上游需求（BR-02）")

    def _next_no(self, project_no: str) -> str:
        """生成下一个需求编号：`REQ-<三位序号>`，**全局**取当前最大号 +1（BR-03）。

        ⚠ 入参 `project_no` **不参与**编号生成：口径是"全局唯一"，比"同一项目内唯一"更强
        （2026-09-25 把 BR-03 的措辞与实现对齐，见应用详设 §3.2.3）。
        """
        rows = self.db.execute("SELECT req_no FROM requirement").fetchall()
        mx = 0
        for r in rows:
            m = re.match(r"^REQ-(\d+)$", str(r["req_no"]))
            if m:
                mx = max(mx, int(m.group(1)))
        return f"REQ-{mx + 1:03d}"
