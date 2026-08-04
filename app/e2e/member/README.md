# member 应用 README（Agent 操作指南）

## 一、应用简介

- **应用名**：`member`
- **所属应用组**：`e2e`
- **聚合根**：`Member`
- **业务主键**：`member_no`
- **同名库**：`member.db`
- **是否跨应用调用**：  
  - 本应用**不主动调用**其他应用服务。  
  - 本应用会被 `task` 应用在创建任务时调用 `member.get`，用于校验任务指派成员是否存在。

本应用用于维护成员主数据，提供成员创建、按成员编号查询、成员列表查询能力。成员主数据是任务指派对象的基础数据来源。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `member__create` | `member_no: str`，必填，无默认<br>`name: str`，必填，无默认<br>`email: str`，必填，无默认<br>`role: str`，必填，无默认 | 创建成员主数据。`member_no` 全局唯一，`email` 全局唯一，`role` 只能为 `admin` 或 `member`。创建成功返回成员基础信息。 |
| `member__get` | `member_no: str`，必填，无默认 | 按成员编号查询成员详情。查询成功返回成员基础信息；成员不存在时抛出业务错误。 |
| `member__list` | `keyword: str`，可选，默认 `None`<br>`role: str`，可选，默认 `None` | 查询成员列表。`keyword` 模糊匹配 `member_no`、`name`、`email`；`role` 只能为 `admin` 或 `member`。`keyword` 或 `role` 为空字符串或 `None` 时表示不过滤。无匹配结果返回空列表。 |

---

## 三、标准工作流

### 1. 创建成员

先调 `member__list` 查重，再调 `member__create`。

推荐顺序：

1. 先调 `member__list`，使用拟创建的 `member_no` 或 `email` 作为 `keyword` 查询是否已存在。
2. 若未查到重复成员，再调 `member__create` 创建成员。
3. 创建成功后，可再调 `member__get` 确认成员已存在。

示例顺序：

```text
member__list(keyword="M001")
member__create(member_no="M001", name="张三", email="zhangsan@example.com", role="member")
member__get(member_no="M001")
```

---

### 2. 按成员编号查询成员详情

如果用户已经提供 `member_no`，直接调 `member__get`。

推荐顺序：

1. 先调 `member__get(member_no="...")`。
2. 如果返回“成员不存在”，再调 `member__list` 核对成员编号是否拼写错误或尚未创建。

示例顺序：

```text
member__get(member_no="M001")
member__list(keyword="M001")
```

---

### 3. 按姓名、邮箱或模糊信息查询成员

如果用户只给了姓名、邮箱片段或模糊关键词，先调 `member__list`，再调 `member__get`。

推荐顺序：

1. 先调 `member__list(keyword="...")` 查询候选成员。
2. 从返回列表中确认目标成员的 `member_no`。
3. 再调 `member__get(member_no="...")` 获取该成员详情。

示例顺序：

```text
member__list(keyword="张三")
member__get(member_no="M001")
```

---

### 4. 为任务指派选择成员

推荐顺序：

1. 先调 `member__list` 筛选成员。
2. 如需只看管理员或普通成员，传入 `role="admin"` 或 `role="member"`。
3. 从结果中选择目标 `member_no`。
4. 再调 `member__get` 确认该成员存在且信息正确。

示例顺序：

```text
member__list(role="member", keyword="张三")
member__get(member_no="M001")
```

---

## 四、前置条件与注意事项

1. **必填字段**
   - 调用 `member__create` 时，`member_no`、`name`、`email`、`role` 均必填。
   - 调用 `member__get` 时，`member_no` 必填。
   - 空字符串或 `None` 会被应用清洗为空值处理；必填字段为空会报错。

2. **成员编号唯一**
   - `member_no` 是成员主数据的全局唯一标识。
   - 重复创建相同 `member_no` 会失败。
   - 创建前建议先用 `member__list` 或 `member__get` 核对。

3. **邮箱唯一**
   - `email` 全局唯一。
   - 不同成员不能使用相同邮箱。
   - 若提示邮箱已存在，应先用 `member__list(keyword="邮箱")` 查询已有成员。

4. **邮箱格式要求**
   - 邮箱必须包含且仅包含一个 `@`。
   - `@` 前后的本地部分和域名部分均不能为空。
   - 例如 `zhangsan@example.com` 合法，`zhangsan.example.com` 非法。

5. **角色取值限制**
   - `role` 只能为 `admin` 或 `member`。
   - `member__create` 的 `role` 必填且必须合法。
   - `member__list` 的 `role` 可选，但一旦传入非空值，也必须为 `admin` 或 `member`。

6. **列表查询行为**
   - `member__list` 无匹配结果时返回空列表，不抛错。
   - `keyword` 会同时模糊匹配 `member_no`、`name`、`email`。
   - `keyword` 与 `role` 同时传入时，取交集。

7. **成员主数据默认不可变更**
   - 本应用未提供修改、删除、停用成员的服务。
   - Agent 不应尝试调用不存在的更新或删除工具。
   - 如成员信息错误，当前业务设计下应重新创建新的成员主数据，或由平台/人工在受控方式下处理。

8. **跨应用依赖**
   - 本应用不主动调用其他应用。
   - `task` 应用创建任务时会依赖 `member.get` 校验指派成员是否存在。
   - 如果 `member__get` 返回“成员不存在”，任务创建侧应终止后续任务创建。

9. **弱引用风险**
   - `task` 等应用可能通过 `member_no` 引用成员。
   - 本应用不提供删除能力，因此正常业务路径下不会出现因删除成员导致的引用悬空。
   - 若绕过应用直接修改 `member.db`，可能导致其他应用校验成员失败。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `member_no 必填，不能为空` | 调用 `member__create` 或 `member__get` 时未提供有效 `member_no`。 | 向用户索要成员编号；确认非空后重新调用对应工具。 |
| `成员编号已存在` | 调用 `member__create` 时传入的 `member_no` 已被占用。 | 先调 `member__get(member_no="...")` 或 `member__list(keyword="...")` 查看已有成员；若是同一成员则无需重复创建；若要创建新成员，请更换新的 `member_no`。 |
| `name 必填，不能为空` | 调用 `member__create` 时未提供有效成员姓名。 | 向用户索要成员姓名；确认非空后重新调用 `member__create`。 |
| `email 必填，不能为空` | 调用 `member__create` 时未提供有效邮箱。 | 向用户索要邮箱；确认非空后重新调用 `member__create`。 |
| `邮箱格式非法` | 邮箱不符合基本格式要求：必须有且仅有一个 `@`，且 `@` 前后均不能为空。 | 请用户提供合法邮箱，例如 `zhangsan@example.com`；修正后重新调用 `member__create`。 |
| `邮箱已存在` | 调用 `member__create` 时传入的 `email` 已被其他成员使用。 | 先调 `member__list(keyword="邮箱")` 查找占用该邮箱的成员；若是同一成员则改用已有成员；若是新成员，请更换邮箱。 |
| `role 必填，不能为空` | 调用 `member__create` 时未提供角色。 | 向用户确认角色；只能选择 `admin` 或 `member`，然后重新调用 `member__create`。 |
| `角色只能为 admin 或 member` | `member__create` 或 `member__list` 传入了非法 `role`。 | 将 `role` 改为 `admin` 或 `member`；若调用 `member__list` 且不需要按角色过滤，可省略 `role` 参数或传 `None`。 |
| `成员不存在` | 调用 `member__get` 时指定的 `member_no` 未查询到成员。 | 先调 `member__list(keyword="...")` 核对成员编号是否错误；若成员确实不存在，可引导用户提供完整信息后调 `member__create` 创建；若用于任务指派校验，则终止后续任务创建并提示用户先创建成员。 |