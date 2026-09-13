# md_part_replace 使用要点

**管什么**：零件替换关系（原物料 → 替换物料）与 ECN 依据；状态为 生效 / 失效。

## 标准工作流（按此顺序）

1. `list` — 按 `old_material_no` / `new_material_no`（模糊）、`status`（精确）浏览现有关系
2. `create` — 新建替换关系，`old_material_no` / `new_material_no` 必填，`ecn_no` 选填，status 默认「生效」
3. `get` — 用返回的 `rel_no` 回读核对
4. `update` — 维护原/替换物料号与 ECN 依据（会重新校验；`rel_no` 只读）
5. `disable` — 替换完成、原物料退出后置「失效」

## 前置条件与禁忌

- **物料引用铁律**：`old_material_no` / `new_material_no` 必须已存在于 `md_material`，`create` / `update` 会实时校验（报「原物料号不存在」/「替换物料号不存在」）。**不要凭空写物料号**，先用 `md_material.list` / `get` 核对，没有就先去建。
- **`old_material_no` 与 `new_material_no` 不能相同**。
- **组合 `old_material_no + new_material_no` 全局唯一**，**已失效的记录也算占用**。重复报「该原物料+替换物料组合已存在」——先 `list` 核对，改用 `update` 或换组合。
- **改状态只能用 `disable`，不要用 `update`**；`disable` 幂等，已失效再调无副作用。
- **失效是单向终点**：V1 不支持反向激活，要恢复须重新 `create`。
- `rel_no` 自动生成、不可修改；`ecn_no` ≤ 50 字符。
- 本应用被 `demand` 以 `list(status=生效)` 弱引用做替换件合并——失效后自动退出合并。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/md_part_replace", doc="README")` 读完整操作指南再处置。
