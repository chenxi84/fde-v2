# member 使用要点

**管什么**：成员主数据——成员创建、按编号查询、列表查询；它也是任务指派对象的基础数据来源。

## 标准工作流（按此顺序）

1. `list` — 查重：用拟创建的 `member_no` 或 `email` 作 `keyword`；同时也用于按姓名/邮箱片段找人、按 `role` 筛指派候选人
2. `create` — 确认无重复后再创建
3. `get` — 按 `member_no` 查详情，确认创建成功

用户只给了姓名或邮箱片段时：先 `list(keyword=...)` 拿到 `member_no`，再 `get`。

## 前置条件与禁忌

- `create` 的 `member_no` / `name` / `email` / `role` **全部必填**；`role` 只能是 `admin` 或 `member`。
- **`member_no` 与 `email` 均全局唯一**，重复即失败。创建前先用 `list` 核对，不要撞了再改。
- 邮箱必须**有且仅有一个 `@`**，`@` 两侧都不能为空（如 `zhangsan@example.com`）。
- **本应用没有修改 / 删除 / 停用成员的服务**——不要试图调更新或删除工具。信息错了，当前设计下只能新建成员，或转人工处理。
- `list` 无匹配返回空列表（不报错）；`keyword` 同时模糊匹配 `member_no`/`name`/`email`，与 `role` 取交集。
- 任务指派场景：`task` 创建时会调 `member.get` 校验指派成员，**先确保成员存在，再建任务**。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="e2e/member", doc="README")` 读完整操作指南再处置。
