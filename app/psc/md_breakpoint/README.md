# md_breakpoint 应用 README（Agent 操作指南）

## 一、应用简介

- **应用名**：`md_breakpoint`
- **所属应用组**：`psc`
- **聚合根**：`MdBreakpoint`
- **系统主键**：`bp_id`（整数自增）
- **业务唯一键**：`customer_no + old_material_no + new_material_no + switch_time`
- **同名库**：`md_breakpoint.db`
- **是否跨应用调用**：
  - 本应用在 `create` / `update` 时主动调用 `md_material.get`（按名调用，传 `material_no`），校验原/新物料号是否存在。
  - 本应用会被 `sales_forecast`（销售预测）在基线计算前调用 `trace(new_material_no)` 做断点追溯，也会被 `demand`（毛/净需求）调用 `list` 做断点处理。

本应用维护「客户 × 原/新物料号 × 切换时间」的新旧件断点切换关系台账。断点关系是事实记录：一旦创建不可物理删除，仅能通过 `disable` 软失效；已停用记录不再参与 `trace` 追溯与 `list` 默认展示。

---

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|---|---|---|
| `psc__md_breakpoint__create` | `customer_no: str`，必填<br>`old_material_no: str`，必填<br>`new_material_no: str`，必填<br>`switch_time: str`，必填<br>`ecn_no: str`，可选，默认 `None` | 新建断点记录。校验原≠新物料、切换时间非空、原/新物料存在（`md_material.get`）、组合唯一。成功返回新记录（含 `bp_id`）。 |
| `psc__md_breakpoint__get` | `bp_id: int`，必填 | 按 `bp_id` 查询单条断点记录（含已停用记录）。不存在时抛出业务错误。 |
| `psc__md_breakpoint__list` | `customer_no: str`，可选，默认 `None`<br>`old_material_no: str`，可选，默认 `None`<br>`new_material_no: str`，可选，默认 `None`<br>`page: int`，可选，默认 `None`<br>`size: int`，可选，默认 `None` | 按客户/原物料/新物料（精确匹配）筛选分页列表，默认不含已停用记录，按切换时间降序。返回 `{"items": [...], "total": n}`；`page`/`size` 均为 `None` 时返回全部。 |
| `psc__md_breakpoint__update` | `bp_id: int`，必填<br>`customer_no: str`，可选，默认 `None`<br>`old_material_no: str`，可选，默认 `None`<br>`new_material_no: str`，可选，默认 `None`<br>`switch_time: str`，可选，默认 `None`<br>`ecn_no: str`，可选，默认 `None` | 更新断点的切换时间/变更单号等字段（`None` 表示保留原值）。重新校验物料引用、原≠新、组合唯一。成功返回更新后记录。 |
| `psc__md_breakpoint__disable` | `bp_id: int`，必填 | 停用断点记录（软失效，不物理删除）。已停用记录再停用会报错。停用后不参与 `trace` 与列表默认展示。 |
| `psc__md_breakpoint__trace` | `new_material_no: str`，必填 | 沿断点向上追溯原物料号链，返回从最上游原物料号到给定新物料号的序列；无断点时返回 `[物料号自身]`。 |

---

## 三、标准工作流

### 1. 新建断点基础数据

先核对物料号与组合，再创建。

推荐顺序：

1. 先调 `psc__md_breakpoint__list(old_material_no="...", new_material_no="...")` 或 `psc__md_breakpoint__list(customer_no="...")` 查看是否已有相同组合。
2. 确认无相同「客户+原物料+新物料+切换时间」组合后，调 `psc__md_breakpoint__create` 创建。
3. 创建成功后，可再调 `psc__md_breakpoint__get(bp_id=...)` 确认记录已入库。

示例顺序：

```text
psc__md_breakpoint__list(customer_no="CUS001")
psc__md_breakpoint__create(customer_no="CUS001", old_material_no="OLD001", new_material_no="NEW001", switch_time="2026-08-01", ecn_no="ECN-001")
psc__md_breakpoint__get(bp_id=1)
```

### 2. 查询断点列表与详情

如果用户已给 `bp_id`，直接调 `get`；只有筛选条件则调 `list`。

推荐顺序：

1. 调 `psc__md_breakpoint__list(...)` 按客户/物料筛选，从结果中取目标 `bp_id`。
2. 调 `psc__md_breakpoint__get(bp_id=...)` 获取单条完整记录。

示例顺序：

```text
psc__md_breakpoint__list(new_material_no="NEW001")
psc__md_breakpoint__get(bp_id=1)
```

### 3. 更新断点记录

先 `get` 定位并回填当前值，再 `update` 只传需要修改的字段。

推荐顺序：

1. 调 `psc__md_breakpoint__get(bp_id=...)` 取当前记录。
2. 调 `psc__md_breakpoint__update(bp_id=..., switch_time="...", ecn_no="...")`，只传要改的字段，其余省略（`None` 保留原值）。
3. 更新后调 `psc__md_breakpoint__get` 确认生效。

示例顺序：

```text
psc__md_breakpoint__get(bp_id=1)
psc__md_breakpoint__update(bp_id=1, ecn_no="ECN-002")
```

### 4. 停用断点记录

对已失效/录入错误的断点执行停用。

推荐顺序：

1. 调 `psc__md_breakpoint__get(bp_id=...)` 确认记录存在且未停用。
2. 调 `psc__md_breakpoint__disable(bp_id=...)` 停用。

示例顺序：

```text
psc__md_breakpoint__get(bp_id=1)
psc__md_breakpoint__disable(bp_id=1)
```

### 5. 断点追溯（供销售预测调用）

对某新物料号调用 `trace`，得到连续的原物料号链。

推荐顺序：

1. 直接调 `psc__md_breakpoint__trace(new_material_no="NEW001")`。
2. 将返回链（如 `["OLD001", "MID001", "NEW001"]`）作为【原件历史】+【新件历史】按切换时间拼接的连续序列，量比固定 1.0。

示例顺序：

```text
psc__md_breakpoint__trace(new_material_no="NEW001")
```

---

## 四、前置条件与注意事项

1. **必填字段**
   - `create`：`customer_no`、`old_material_no`、`new_material_no`、`switch_time` 均必填。
   - `get` / `disable`：`bp_id` 必填。
   - `trace`：`new_material_no` 必填。
   - 空字符串或 `None` 会被清洗为空值处理；必填字段为空会报错。

2. **业务唯一性（BR-01）**
   - 同一「客户 + 原物料号 + 新物料号 + 切换时间」组合全局唯一。
   - 创建/更新均校验；重复组合会失败，提示“该断点组合已存在”。
   - 更新时可传 `customer_no` / `old_material_no` / `new_material_no` / `switch_time` 覆盖原值，重新校验组合唯一。

3. **原物料号不得等于新物料号（BR-02）**
   - `old_material_no` 与 `new_material_no` 必须不同，二者相同时拒绝。

4. **切换时间必填（BR-03）**
   - `switch_time` 不可为空；创建与更新（若修改）均校验。

5. **物料引用校验（BR-05）**
   - `old_material_no` / `new_material_no` 必须已存在于 `md_material`，创建/更新时后端经 `md_material.get` 校验。
   - 若 `md_material` 中无该物料号，会提示“物料不存在”，应先在 `md_material` 中创建该物料。

6. **断点关系不可物理删除（BR-06）**
   - 本应用不提供删除服务；需要作废时用 `psc__md_breakpoint__disable` 软失效。
   - 已停用记录不参与 `trace` 追溯与 `list` 默认展示，但 `get` 仍可查询到。

7. **列表查询行为**
   - `list` 三个筛选条件（`customer_no` / `old_material_no` / `new_material_no`）均为精确匹配、AND 关系，全部可选。
   - 默认按 `switch_time` 降序、`bp_id` 降序排列。
   - 无匹配结果时返回空列表（`total=0`），不抛错。

8. **跨应用依赖**
   - `md_material`：`create` / `update` 依赖其 `get` 服务校验物料存在；`md_material` 缺失会导致“物料校验失败”。
   - 本应用被 `sales_forecast`（`trace`）、`demand`（`list`）调用，是其断点追溯/断点处理的数据来源。

9. **多客户维度的追溯口径**
   - 同一新物料号若在多个客户下存在多条断点记录，`trace` 当前按切换时间最早的记录向上追溯（未按客户上下文匹配），返回单条链。多客户精确匹配口径待实施设计确认。

---

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步动作 |
|---|---|---|
| `客户不能为空` | `create`（或 `update` 传了空 `customer_no`）未提供有效客户编码。 | 向用户索要客户编码（来源 `md_customer`）；确认非空后重新调用。 |
| `原物料号不能为空` | 未提供有效原物料号。 | 向用户索要原物料号（来源 `md_material`）；确认非空后重新调用。 |
| `新物料号不能为空` | 未提供有效新物料号。 | 向用户索要新物料号（来源 `md_material`）；确认非空后重新调用。 |
| `切换时间不能为空` | 未提供切换时间。 | 向用户索要切换时间（新旧件切换生效时点，如 `2026-08-01`）；确认非空后重新调用。 |
| `原物料号与新物料号不能相同` | `old_material_no` 与 `new_material_no` 填为同一物料号。 | 请用户核对原/新物料号，二者必须不同；修正后重新调用。 |
| `物料不存在` | `old_material_no` 或 `new_material_no` 在 `md_material` 中不存在。 | 先到 `md_material` 核对物料号（`md_material.get` / `list`）；若确实不存在，先在 `md_material` 创建该物料，再回来创建/更新断点。 |
| `物料校验失败` | 跨应用调用 `md_material.get` 出现异常（如应用未加载）。 | 检查 `md_material` 应用是否正常加载；确认后重试。 |
| `该断点组合已存在` | 相同「客户+原物料+新物料+切换时间」组合已存在。 | 先 `list` 查看已有组合；若是同一断点则无需重复创建；若需修改，改用 `update` 定位已有 `bp_id`。 |
| `变更单号长度不能超过50` | `ecn_no` 超过 50 字符。 | 请用户提供 50 字符以内的变更单号；修正后重新调用。 |
| `断点记录不存在` | `get` / `update` / `disable` 指定的 `bp_id` 未查询到记录。 | 先 `list` 核对 `bp_id` 是否错误；若确无此记录，引导用户提供正确 `bp_id` 或先创建。 |
| `断点标识不能为空` | `get` / `update` / `disable` 未提供 `bp_id`。 | 向用户索要 `bp_id`；确认非空后重新调用。 |
| `该断点已停用` | `disable` 的目标记录已处于停用状态。 | 无需重复停用；如需重新启用请确认业务规则（当前无启用服务）。 |
| `物料号不能为空` | `trace` 未提供 `new_material_no`。 | 向用户索要新物料号；确认非空后重新调用 `trace`。 |
| `分页参数不合法` | `list` 的 `page` / `size` 不是整数。 | 将 `page` / `size` 改为整数；分页可不传（返回全部）。 |
| `页码必须大于等于1` | `list` 的 `page` 小于 1。 | 将 `page` 改为 ≥1 的整数。 |
| `每页条数必须大于等于1` | `list` 的 `size` 小于 1。 | 将 `size` 改为 ≥1 的整数。 |
