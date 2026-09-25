# verification 使用要点

**管什么**：验证矩阵的一行——某条需求的验证方法 / 验证阶段 / 判定与证据；不含验证计划本身（属 `tech_plan`）与需求台账（属 `requirement`）。

## 标准工作流（按此顺序）

1. `create(req_no, method, phase, criteria=None, owner=None, project_no=None)` — 规划一行，编号自动生成（`VER-001` 起），落库为 `planned`；`req_no` 必填且经 `requirement.get` **跨应用**校验存在
2. `start(ver_no, owner=None)` — 开始执行：`planned → executing`
3. `record_result(ver_no, result, evidence, follow_up=None)` — 判定：`executing → passed | failed`。`evidence` 必填；`result="fail"` 时 `follow_up` **必填**（三者同一次调用落库）
4. `close(ver_no, note=None)` — 收尾：`passed / failed → closed`（**终态**）

规划信息补正用 `update(ver_no, method, phase, criteria, owner)`；查询用 `list`（按 `req_no` / `method` / `status` / `phase` 筛，分页 `{items, total}`）→ `get`。

## 前置条件与禁忌

- **状态闸（守卫顺序即报错顺序）**：`start` 只认 `planned`（已在执行报「已在执行中」，其余报「只有规划状态才能开始执行（BR-06）」）；`record_result` 只认 `executing`（`planned` 报「请先开始执行再记录判定（BR-06）」）；`close` 只认已判定（`planned` / `executing` 报「只有已判定的验证项才能关闭（BR-06）」）；`closed` 是**终态**，`update` / `record_result` / `close` 一律拒绝。
- **两条不可逆**：**判定不可重复**（已 `passed` / `failed` 再判 → 「不能重复判定（需重新验证请另建验证项，BR-03）」）；**关闭后记录保留、不可再改**（不删除）。
- **`update` 白名单只有 method / phase / criteria / owner**：`req_no` 不在里面（换需求 = 换矩阵一行，应**另建**验证项），`status` / `result` / `evidence` 也不在（只能走上面三步）。已判定后**不得改写 `method` / `phase`**（判定的事实前提），补 `criteria` / `owner` 仍允许；一个字段都不给则报「没有要修改的内容」。
- **跨应用失败要分清**：需求不存在报「对应需求 REQ-999 不存在，请先在需求台账中录入（BR-01）」；`requirement` 应用不可用报「对应需求 REQ-999 校验失败（requirement 应用不可用）」——后者**不是**"需求不存在"，别据此换编号重试。
- **只校验需求存在、不校验它已基线**：草稿需求也能建验证项；"已基线但无验证项"的缺口读数在视图层，写路径不拦 I-1。一条验证项只对应一条需求。
- 字典：`method` ∈ inspection / analysis / demonstration / test；`phase` ∈ pre_development / box_functional / box_environmental / system_environmental / system_functional / end_to_end / integrated_vehicle / on_orbit；`result` ∈ pass / fail。
- `get` 未命中返回 `None`（不抛异常）；编号 `VER-<三位>` 无改编号入口；`close` 的 `note` **落库**到 `close_note`（2026-09-25 起留痕，详情模态会显示「关闭说明」）。
