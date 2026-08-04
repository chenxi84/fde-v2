# task 应用 README（Agent 操作指南）

## 一、应用简介

- **应用组**：`e2e`
- **应用名**：`task`
- **聚合根**：`Task`
- **主键**：`task_no`
- **同名库**：`task.db`
- **是否跨应用**：是。`task__create` 在创建任务时会跨应用调用 `member` 应用的 `get` 服务，校验 `assignee_member_no` 对应的成员是否存在。
- **引用关系**：`task.assignee_member_no` 是对 `member.member_no` 的**弱引用**，不建物理外键，不做级联更新/删除。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `task__create` | `title`：str，必填，无默认<br>`description`：str \| None，必填，无默认（可传 `null` 或空字符串表示无描述）<br>`assignee_member_no`：str，必填，无默认<br>`priority`：str，必填，无默认 | 创建任务。初始状态固定为 `待办`，返回任务对象。 |
| `task__get` | `task_no`：str，必填，无默认 | 按任务编号查询任务详情，返回任务对象。 |
| `task__list` | `status`：str \| None，可选，默认 `None`<br>`assignee_member_no`：str \| None，可选，默认 `None`<br>`priority`：str \| None，可选，默认 `None` | 按状态、指派成员、优先级组合筛选任务列表，返回任务对象列表。无匹配数据时返回空列表，不抛错。 |
| `task__start` | `task_no`：str，必填，无默认 | 将任务从 `待办` 推进到 `进行中`，返回任务对象。 |
| `task__complete` | `task_no`：str，必填，无默认 | 将任务从 `进行中` 推进到 `已完成`，返回任务对象。 |
| `task__reopen` | `task_no`：str，必填，无默认 | 将任务从 `进行中` 退回到 `待办`，返回任务对象。 |

---

## 三、标准工作流

### 1. 创建任务

1. 先确认 `assignee_member_no` 是有效的成员编号。
2. 调用 `task__create`，传入：
   - `title`
   - `description`
   - `assignee_member_no`
   - `priority`
3. 创建成功后，从返回值中取得 `task_no`。
4. 如需确认任务详情，再调用 `task__get`。

### 2. 查询任务列表并处理任务

1. 先调用 `task__list`，按需要传入筛选条件：
   - `status="待办"`
   - `assignee_member_no="成员编号"`
   - `priority="high"` 或 `"low"`
2. 从返回列表中取得目标任务的 `task_no`。
3. 调用 `task__get` 确认任务当前状态。
4. 根据当前状态选择下一步：
   - 若状态为 `待办`：先调 `task__start`
   - 若状态为 `进行中`：可调 `task__complete` 或 `task__reopen`
   - 若状态为 `已完成`：不能再流转

### 3. 标准任务闭环

1. 先调 `task__create` 创建任务。
2. 再调 `task__get` 确认状态为 `待办`。
3. 再调 `task__start` 将任务推进到 `进行中`。
4. 再调 `task__get` 确认状态为 `进行中`。
5. 最后调 `task__complete` 将任务推进到 `已完成`。

### 4. 退回任务

1. 先调 `task__get` 确认任务状态为 `进行中`。
2. 调用 `task__reopen`。
3. 再调 `task__get` 确认状态已回到 `待办`。

---

## 四、前置条件与注意事项

1. **创建任务前必须先确认成员存在**
   - `task__create` 会调用 `member.get` 校验 `assignee_member_no`。
   - 若成员不存在，任务不会创建。

2. **字段约束**
   - `title` 必填，不能为空白，长度不能超过 200。
   - `description` 可为 `null` 或空字符串，但非空时长度不能超过 2000。
   - `assignee_member_no` 必填，不能为空白。
   - `priority` 只能为 `low` 或 `high`。

3. **任务编号由系统生成**
   - `task_no` 由 `task` 应用自动生成。
   - Agent 不能指定 `task_no`。
   - 后续查询、启动、完成、退回都必须使用已存在的 `task_no`。

4. **状态机约束**
   - `待办` 只能 `start`。
   - `进行中` 可以 `complete` 或 `reopen`。
   - `已完成` 不能再执行 `start`、`complete`、`reopen`。

5. **列表筛选约束**
   - `task__list` 的 `status` 如果传入，只能是：
     - `待办`
     - `进行中`
     - `已完成`
   - `task__list` 的 `priority` 如果传入，只能是：
     - `low`
     - `high`
   - `assignee_member_no` 可为 `null`，表示不按成员筛选。

6. **弱引用成员主数据**
   - `task` 只在 `task__create` 时校验成员是否存在。
   - 任务创建后，`assignee_member_no` 仅作为业务编号保存。
   - 成员后续变更或删除，不会自动级联更新任务。

7. **没有任务修改/删除服务**
   - 本应用不提供修改标题、描述、指派人、优先级的服务。
   - 本应用不提供删除任务服务。

8. **权限由平台控制**
   - Agent 能否调用这些工具，由平台授权决定。
   - 应用本身不做鉴权。

---

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `任务标题不能为空` | `task__create` 传入的 `title` 为空或全是空白字符。 | 向用户索要有效标题，去除首尾空白后重新调用 `task__create`。 |
| `任务标题长度不能超过200` | `title` 超过 200 个字符。 | 缩短标题至 200 字符以内后重试。 |
| `任务描述长度不能超过2000` | `description` 非空但超过 2000 个字符。 | 缩短描述，或传 `null` / 空字符串后重试。 |
| `指派成员编号不能为空` | `assignee_member_no` 为空或全是空白字符。 | 向用户索要成员编号，或先查询成员列表取得有效编号。 |
| `优先级只能为 low 或 high` | `priority` 不是 `low` 或 `high`。 | 将 `priority` 改为 `low` 或 `high` 后重试。 |
| `指派成员 <成员编号> 不存在` | `task__create` 时调用 `member.get` 未找到该成员，实际错误消息中会包含具体成员编号。 | 先核对 `assignee_member_no`；必要时调用 `member` 应用工具查询或创建成员；确认成员存在后重新调用 `task__create`。 |
| `任务编号生成失败，请重试` | 系统生成 `task_no` 时连续冲突，极少发生。 | 直接重试 `task__create`；若多次失败，提示人工介入或联系维护。 |
| `任务编号不能为空` | `task__get` / `task__start` / `task__complete` / `task__reopen` 传入的 `task_no` 为空或空白。 | 提供非空 `task_no`；如果不知道编号，先调用 `task__list` 查询。 |
| `任务不存在` | 传入的 `task_no` 查不到任务，或状态更新时任务已不存在。 | 先调用 `task__list` 或 `task__get` 核对任务编号；确认任务存在后再执行对应操作。 |
| `状态筛选不合法` | `task__list` 传入的 `status` 不是 `待办`、`进行中`、`已完成`。 | 只使用合法状态筛选，或省略 `status` 参数后重试。 |
| `优先级筛选不合法` | `task__list` 传入的 `priority` 不是 `low` 或 `high`。 | 只使用 `low` 或 `high` 筛选，或省略 `priority` 参数后重试。 |
| `进行中任务不能再次启动` | 对状态为 `进行中` 的任务调用了 `task__start`。 | 不需要再启动；若要继续推进，调用 `task__complete`；若要退回，调用 `task__reopen`。 |
| `已完成任务不能启动` | 对状态为 `已完成` 的任务调用了 `task__start`。 | 终止该任务的状态流转；如仍需工作，调用 `task__create` 新建任务。 |
| `仅待办任务可以启动` | `task__start` 只允许从 `待办` 状态启动。 | 先调用 `task__get` 查看当前状态；只有 `待办` 才调用 `task__start`。 |
| `待办任务不能直接完成` | 对状态为 `待办` 的任务调用了 `task__complete`。 | 先调用 `task__start`，再调用 `task__complete`。 |
| `已完成任务不能重复完成` | 对状态为 `已完成` 的任务调用了 `task__complete`。 | 无需重复完成；可调用 `task__get` 确认当前状态。 |
| `仅进行中任务可以完成` | `task__complete` 只允许从 `进行中` 状态完成。 | 先调用 `task__get` 查看状态；若为 `待办`，先 `task__start`；若为 `已完成`，停止操作。 |
| `待办任务不能退回` | 对状态为 `待办` 的任务调用了 `task__reopen`。 | 无需退回；若要开始执行，调用 `task__start`。 |
| `已完成任务不能退回` | 对状态为 `已完成` 的任务调用了 `task__reopen`。 | 已完成任务不能退回；如需继续处理，调用 `task__create` 新建任务。 |
| `仅进行中任务可以退回` | `task__reopen` 只允许从 `进行中` 状态退回。 | 先调用 `task__get` 查看状态；只有 `进行中` 才调用 `task__reopen`。 |
| `任务状态不合法` | 内部状态流转时出现非法状态值；正常 Agent 调用通常不应触发。 | 不要尝试直接修改状态；先调用 `task__get` 重新确认任务状态；若持续出现，提示人工介入或联系维护。 |