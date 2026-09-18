# 架构设计：成员任务管理（e2e）

## 1. 聚合根清单总表

| # | 应用名 | 类名 | 实体标识 | 是否主数据 | 一句话职责 |
|---|---|---|---|---|---|
| 1 | `member` | `Member` | `member_no` | 是 | 成员主数据，维护成员基础信息与角色 |
| 2 | `task` | `Task` | `task_no` | 否 | 任务事务单据，管理任务创建、指派与状态流转 |

## 2. 聚合根卡

### 2.1 `member` / `Member`

- **业务定义**：成员主数据，作为任务指派的对象。
- **标识（主键）**：`member_no`

#### 关键属性

| 属性 | 类型 | 含义 |
|---|---|---|
| `member_no` | 文本 | 成员编号，唯一标识 |
| `name` | 文本 | 成员姓名 |
| `email` | 文本 | 成员邮箱 |
| `role` | 枚举 | 成员角色，取值 `admin` / `member` |

#### 核心操作（对外服务）

| 操作 | 说明 |
|---|---|
| `create(member_no, name, email, role)` | 创建成员 |
| `get(member_no)` | 按成员编号查询成员 |
| `list(keyword?, role?)` | 按条件查询成员列表 |

#### 不变量（业务规则）

- `member_no` 必填且全局唯一。
- `role` 取值必须为 `admin` 或 `member`。
- 成员创建后是否允许修改/删除：业务未提供，默认不开放。

#### 引用的聚合

- 无。

#### 跨应用调用（`self.fde.call`）

- 无。

#### 状态机

- 无。

---

### 2.2 `task` / `Task`

- **业务定义**：任务事务单据，记录任务内容、指派成员与状态流转。
- **标识（主键）**：`task_no`

#### 关键属性

| 属性 | 类型 | 含义 |
|---|---|---|
| `task_no` | 文本 | 任务编号，唯一标识 |
| `title` | 文本 | 任务标题 |
| `description` | 文本 | 任务描述 |
| `assignee_member_no` | 文本 | 指派成员编号，引用 `member.member_no` |
| `priority` | 枚举 | 优先级，取值 `low` / `high` |
| `status` | 枚举 | 任务状态，取值 `待办` / `进行中` / `已完成` |

#### 核心操作（对外服务）

| 操作 | 说明 |
|---|---|
| `create(title, description, assignee_member_no, priority)` | 创建任务，初始状态为 `待办` |
| `get(task_no)` | 按任务编号查询任务 |
| `list(status?, assignee_member_no?, priority?)` | 按条件查询任务列表 |
| `start(task_no)` | 将任务从 `待办` 推进到 `进行中` |
| `complete(task_no)` | 将任务从 `进行中` 推进到 `已完成` |
| `reopen(task_no)` | 将任务从 `进行中` 退回到 `待办` |

#### 不变量（业务规则）

- `task_no` 必填且全局唯一。
- `title` 必填，为空时抛 `FdeError`。
- `priority` 取值必须为 `low` 或 `high`。
- `status` 取值必须为 `待办`、`进行中`、`已完成`。
- 创建任务时，`assignee_member_no` 对应的成员必须存在；调用 `member.get` 校验，不存在时抛 `FdeError`。
- 状态流转必须合法：
  - `待办` 只能执行 `start`。
  - `进行中` 可以执行 `complete` 或 `reopen`。
  - `已完成` 不可再执行 `start`、`complete`、`reopen`。
- 非法状态流转抛 `FdeError`。

#### 引用的聚合

- `member.member_no`：通过 `assignee_member_no` 弱引用成员主数据。

#### 跨应用调用（`self.fde.call`）

| 本聚合操作 | 调用目标 | 用途 |
|---|---|---|
| `task.create` | `member.get` | 校验指派成员是否存在 |

#### 状态机

```text
待办 --start--> 进行中
进行中 --complete--> 已完成
进行中 --reopen--> 待办
已完成 --禁止操作--> 已完成
```

## 3. 聚合关系图

- `task` 通过 `assignee_member_no` 弱引用 `member.member_no`。
- `task.create` 调用 `member.get`，用于校验成员是否存在。
- `member` 不依赖 `task`。

```text
member <== task

引用：
task.assignee_member_no --> member.member_no

跨应用调用：
task.create --> member.get
```

## 4. 构建批次

### 批次 1：地基主数据

- `member`

说明：成员是任务指派的前置主数据，必须先构建。任务创建时需要调用 `member.get` 校验成员存在性。

### 批次 2：主链事务

- `task`

说明：任务为核心业务单据，依赖成员主数据，承载创建、查询、启动、完成、退回等主流程操作。

### 批次 3：变更 / 逆向

- 无独立应用。

说明：本业务精简版无独立变更单或逆向流程应用；`reopen` 属于 `task` 聚合内部状态流转，不单独拆分应用。

<!-- apps: member,task -->