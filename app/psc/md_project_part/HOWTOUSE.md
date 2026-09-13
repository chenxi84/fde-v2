# md_project_part 使用要点

**管什么**：项目 × 零件的用量映射——单车用量（`usage`）与供应份额（`share`），一个「项目+物料」一条量纲。

## 标准工作流（按此顺序）

1. `list` — 按 `project_no` / `material_no` / `veh_model` 模糊浏览，先确认要动的组合是否存在
2. `create` — 新建映射，`project_no` / `material_no` / `veh_model` / `usage` / `share` **全必填**
3. `get` — 按复合主键（`project_no` + `material_no`）回读单条
4. `update` — 改量纲：先 `get` 回填，只传要改的字段（主键不可改）
5. `list_by_material` — 按物料取它在**所有**项目中的映射（不分页，供量纲折算 / 预测分摊）
6. `import_batch` — 批量导入 / PLM 同步，读 `errors` 修正后重导

## 前置条件与禁忌

- **引用完整性由后端强制校验**：`project_no` 必须已在 `md_project` 存在、`material_no` 必须已在 `md_material` 存在，`create` / `update` / `import_batch` 都会实际去查。报「项目不存在」/「物料不存在」时，先到对应主数据应用建好，别在这里硬建。
- **不要凭空编造项目号 / 物料号**。选号先用 `md_project.list` / `md_material.list` 让用户挑，再回来建映射。
- **复合主键 `project_no + material_no` 全局唯一且不可修改**，重复创建报「该项目-物料映射已存在」——改用 `update` 更新已有那条，或换组合。
- 量纲范围：`usage`（单车用量）必须 **> 0**；`share`（供应份额）必须在 **[0, 1]** 区间（含 0 和 1）。
- **没有删除服务**，V1 只增改不删。
- `list` 返回 `{"items", "total"}`，`page` / `size` 都省略时返回全部。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="psc/md_project_part", doc="README")` 读完整操作指南再处置。
