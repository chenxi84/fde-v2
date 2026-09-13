# md_breakpoint 使用要点

**管什么**：客户 × 原/新物料号 × 切换时间的新旧件断点切换关系，以及向上追溯的原物料号链。

## 标准工作流（按此顺序）

1. `list` — 按 `customer_no` / `old_material_no` / `new_material_no` 查重或浏览现有断点
2. `create` — 新建断点，`customer_no` / `old_material_no` / `new_material_no` / `switch_time` 必填，`ecn_no` 选填
3. `get` — 按 `bp_id` 回读确认
4. `update` — 改切换时间 / 变更单号：先 `get` 回填，只传要改的字段（`None` 保留原值）
5. `disable` — 作废（软失效）
6. `trace` — 向上追溯原物料号链，回答「这个新料的上一代是谁」；无断点时返回 `[物料号自身]`
7. `upcoming` — 查「最近哪些料要切换」：`switch_time` 落在未来 `days` 天内的未停用断点（默认 60 天）

## 前置条件与禁忌

- **没有物理删除**。断点关系是事实记录，作废只能 `disable` 软失效；已停用记录不再参与 `trace`、也不出现在 `list` 默认结果里（`get` 仍能查到）。
- **物料必须已存在于 `md_material`**：`create` / `update` 会实时校验原/新物料号，报「物料不存在」就先去 `md_material` 建号，别在这里硬建。
- **`old_material_no` 与 `new_material_no` 不能相同**；`switch_time` 不可为空；`ecn_no` ≤ 50 字符。
- **唯一键是「客户 + 原物料 + 新物料 + 切换时间」**，重复报「该断点组合已存在」——先 `list` 核对，是同一断点就别重复建，要改就 `update` 对应 `bp_id`。
- `list` 三个筛选条件都是**精确匹配**、AND 关系，默认按切换时间降序；无命中返回空列表，不报错。
- `get_switch_time` 是给 `sales_forecast` 定追溯起点用的，也可直接取某新物料的切换时间（无断点返回 `None`，不抛错）。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/md_breakpoint", doc="README")` 读完整操作指南再处置。
