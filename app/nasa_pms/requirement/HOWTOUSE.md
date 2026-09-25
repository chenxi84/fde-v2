# requirement 使用要点

**管什么**：需求台账——需求（标题 / 正文 / 类型 / 验证方法）的录入、派生链与基线归属；不含验证执行（属 `verification`）与变更审批（属 `change_request`）。

## 标准工作流（按此顺序）

1. `create(title, statement, req_type, verify_method, source_req_no=None, owner=None, project_no=None)` — 录入，编号自动生成（`REQ-001` 起），落库为 `draft`
2. `derive(source_req_no, title, statement, verify_method, owner=None)` — 从上游派生（先校验上游存在），等价于 `create(req_type="derived")`
3. `submit_review(req_no)` — 提交评审：`draft` → `pending_review`（**纳入基线的前置门**）
4. `baseline(req_nos, baseline_ver)` — 整批纳入基线，状态 → `baselined`
4. `update(req_no, title, statement, verify_method, owner, change_no)` — 改内容；`obsolete(req_no, reason=None)` — 作废（**不删除**，下游仍看得见它）

核对用 `list`（按 `req_type` / `status` / `source_req_no` 筛，分页 `{items, total}`）→ `get`。

## 前置条件与禁忌

- **`baseline` 全或无**：逐条校验，任一条不过**整批拒绝、零副作用**，报错指明是哪一条：「需求 X 不存在，整批未纳入基线」/「需求 X 没有验证方法，不能纳入基线（BR-01）」/「需求 X 已废弃，不能纳入基线」。
- **状态闸与评审门**（2026-09-25 起）：
  · `submit_review` 只认 `draft`（报「只有草稿可以提交评审」）；
  · `baseline` 只认 `pending_review` —— **草稿不能直接进基线**（报「须先提交评审（`submit_review`）才能纳入基线」）；
  · `update` 对未基线态（`draft` / `pending_review`）放行；已 `baselined` 的必须带 `change_no`，否则报
    「已基线的需求不能直接修改，请先提交变更请求（BR-04）」。
  ⚠ 带 `change_no` 只是记下变更号、**状态不变**，也**不校验它是否已批准**（批准与否由 `change_request` 保证）——
  别报告「已进入变更流程」：需求侧**没有**「变更中」这个状态了（变更全流程在 `change_request`）。
- **守卫顺序**（报错取决于它）：标题空 → 正文空 → 类型字典 → 验证方法（空报「需求必须有验证方法（BR-01）」，非字典报「验证方法只能是 inspection/analysis/demonstration/test 之一」）→ `derived` 缺上游（「派生需求必须填写上游需求（BR-02）」）。
- **`create` 只判上游非空、不校验存在**：要校验就用 `derive`（报「上游需求 REQ-999 不存在，不能派生」）。`source_req_no` 是**弱引用**，上游事后作废也不清空。
- 字典 `req_type` ∈ system / technical / interface / derived；编号 `REQ-<三位>` 由系统**全局递增**生成（不按 `project_no` 分段）、**无改编号入口**。
- `update` 传 `statement=""` 会**直接清空正文**（不判空）；`owner` 是**纯文本**、不校验是否存在于 `stakeholder`；`obsolete` 的 `reason` **落库**到 `void_reason`（2026-09-25 起留痕，详情模态会显示「作废理由」）。
