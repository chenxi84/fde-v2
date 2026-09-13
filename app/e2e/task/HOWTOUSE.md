# task 使用要点

**管什么**：任务本身——创建、查询，以及 `待办 → 进行中 → 已完成` 的状态流转（进行中可退回）。

## 标准工作流（按此顺序）

1. `create` — 创建任务，初始状态固定为 `待办`；从返回值取 `task_no`
2. `list` — 按 `status` / `assignee_member_no` / `priority` 筛选，定位目标任务
3. `get` — 确认当前状态
4. 按状态推进：`待办` → `start`；`进行中` → `complete` 或 `reopen`；`已完成` 不能再流转

标准闭环：`create` → `get`（待办）→ `start` → `get`（进行中）→ `complete`。
退回：`get` 确认 `进行中` → `reopen` → `get` 确认已回到 `待办`。

## 前置条件与禁忌

- **创建前必须先确认成员存在**：`create` 会跨应用调 `member.get` 校验 `assignee_member_no`，成员不存在则任务不会创建。报「指派成员 X 不存在」→ 先去查/建成员，不要反复重试 `create`。
- **状态机**：`待办` 只能 `start`；`进行中` 可 `complete` / `reopen`；`已完成` 是终态。跳步必被拒（如 `待办` 直接 `complete`）。
- `task_no` 由系统生成，**不能指定**；后续操作必须使用已存在的编号。
- `priority` 只能 `low` 或 `high`；`title` 必填且 ≤ 200 字符；`description` 可空，非空时 ≤ 2000 字符。
- **本应用没有修改（标题/描述/指派人/优先级）与删除任务的服务**——不要试图调不存在的更新/删除工具。
- `list` 的 `status` 筛选只能是 `待办` / `进行中` / `已完成`。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="e2e/task", doc="README")` 读完整操作指南再处置。
