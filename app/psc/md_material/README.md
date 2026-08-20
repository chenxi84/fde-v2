# 物料主数据 md_material

## 一、应用简介

- **聚合根**：物料主数据 `MdMaterial`，主键为 `material_no`（物料号，全局唯一）。
- **数据存库**：同名库 `md_material.db`（平台管理连接，无需应用手写 `sqlite3.connect`）。
- **业务定位**：`material_no` 是全链 11 个业务聚合（销售预测 / 库存策略 / 需求 / 主计划 / 库存推移 / 需求池 / 策略拟合 / 达成率 / 物料断点等）的核心键。本应用是物料号的权威来源，承载：
  1. **物料基础信息**：`material_no` / `material_name` / `status`（正常/EOP/停用）。
  2. **预测方法参数**：`base_method`（移动平均/指数平滑/阶跃检测/借用参考）+ `base_params`（JSON 文本）。
  3. **库存策略参数**：`unit_value` / `value_class` / `change_cost` / `prod_days` / `logistics_days` / `change_risk` / `service_level` / `batch_window`。
- **跨应用调用**：本应用**不调用**其他聚合（无出向 `self.fde.call`）；但**提供** `set_fit_params` 服务，被 `strategy_fitting.approve` 跨应用调用回填拟合参数。
- **状态机**：`status` 由外部主数据接口（ERP/PLM）维护，本系统**只读**，不联动 EOP。
- **两张表**：主表 `md_material` + 参数版本快照表 `md_material_param_version`（供拟合参数回滚追溯）。

## 二、对外服务（工具）

| 工具名 | 参数（类型 / 必填 / 默认） | 说明 |
|---|---|---|
| `psc__md_material__create` | material_no: str 必填；material_name: str 必填；status: str 默认"正常"；unit_value/value_class/change_cost/prod_days/logistics_days/change_risk/service_level/batch_window/base_method/base_params 均选填 | 新建物料，material_no 唯一 |
| `psc__md_material__get` | material_no: str 必填 | 查单个物料完整字段 |
| `psc__md_material__list` | material_no: str 选填（模糊）；material_name: str 选填（模糊）；status: str 选填（精确，正常/EOP/停用）；page: int 选填；size: int 选填 | 分页列表，返回 `{"items", "total"}` |
| `psc__md_material__update` | material_no: str 必填（定位键）；material_name/unit_value/value_class/change_cost/prod_days/logistics_days/change_risk/service_level/batch_window/base_method/base_params 选填；status 选填但只读 | 更新名称与参数，主键/状态不可改 |
| `psc__md_material__import_batch` | rows: list 必填（行对象数组） | 批量导入/更新（upsert），返回成功/失败/错误明细 |
| `psc__md_material__set_fit_params` | material_no: str 必填；base_method: str 必填；base_params: str 必填；batch_window: float 必填；service_level: float 必填；fit_version: str 必填 | 拟合参数回填（含版本记录） |

> `base_params` 为 JSON 字符串（如 `{"window": 6}`、`{"alpha": 0.3, "trend": false}`）。

## 三、标准工作流

1. **初始化建账 / 日常同步**：先 `psc__md_material__import_batch`（rows 为从 ERP/PLM 冗余同步或 Excel 解析出的行对象数组）批量导入；已有主键行自动更新，失败行返回 `errors`。
2. **本地补录**：对缺失的单个物料，调 `psc__md_material__create`（material_no + material_name 必填，status 默认"正常"）。
3. **查询/浏览**：调 `psc__md_material__list`（可按 status=正常 取预测范围物料，按 material_no/material_name 模糊定位）；对目标物料调 `psc__md_material__get` 看完整参数。
4. **维护参数**：调 `psc__md_material__update`（仅传要改的字段；material_no 只作定位、status 不可改）。
5. **拟合回填**（由 strategy_fitting 发起，非前端角色）：strategy_fitting 人工复核通过后调 `psc__md_material__set_fit_params` 回填最优方法与参数，系统记录 `fit_version` + 生效时间并保留版本快照供回滚。

## 四、前置条件与注意事项

- **material_no 全局唯一**，且为定位键、不可修改；`update`/`get`/`set_fit_params` 均以它定位，不存在则报"物料记录不存在"。
- **status 只读**：本系统不提供状态流转；`update` 不接受改 status（改报"状态由外部维护，本系统只读"）；`import_batch` 例外——它是 ERP/PLM 冗余同步，status 随同步更新。
- **枚举约束**：status ∈ {正常,EOP,停用}；value_class ∈ {高,低}；change_risk ∈ {高,低}；base_method ∈ {移动平均,指数平滑,阶跃检测,借用参考}。
- **数值约束**：unit_value/change_cost/prod_days/logistics_days ≥ 0；service_level ∈ [0,1]；batch_window > 0。
- **base_params 与 base_method 匹配**（缺必需键即"基线参数与基线方法不匹配"）：
  - 移动平均：必需 `window`（整数 3~12）；
  - 指数平滑：必需 `alpha`（0~1），可选 `trend/beta/seasonal/gamma/period`；
  - 阶跃检测：必需 `threshold`（0~1），可选 `confirm_periods`(1~3)/`lookback`(3~12)；
  - 借用参考：必需 `ref_material`（须为本应用已存在的物料号），可选 `scale`(>0)/`mode`(trend|season|lifecycle)/`offset`。
- **base_params 为空**时按对应方法默认值处理（移动平均 `{"window":6}`、指数平滑 `{"alpha":0.3,"trend":false}` 等）。
- **不提供删除**：物料被全链引用，V1 只增改不删。
- **删除不级联**：本应用不删除、不级联；其他聚合只按 material_no 弱引用，引用方自担一致性。

## 五、错误处理（Agent 应对策略）

| FdeError 信息 | 含义 | Agent 下一步 |
|---|---|---|
| 该物料号已存在 | create 主键冲突 | 改用 `update` 或 `import_batch`，或换 material_no |
| 物料号不能为空 | material_no 缺失 | 向用户索要物料号 |
| 物料名称不能为空 | material_name 缺失 | 向用户索要物料名称 |
| 物料记录不存在 | get/update/set_fit_params 定位失败 | 先 `list` 核对编号，或先 `create`/`import_batch` 建物料 |
| 状态仅支持正常/EOP/停用 | status 非法 | 修正为"正常/EOP/停用" |
| 状态由外部维护，本系统只读 | update 试图改 status | 告知状态由外部维护，走 ERP/PLM 同步 |
| 价值分类仅支持高/低 | value_class 非法 | 修正为"高/低" |
| 变更风险等级仅支持高/低 | change_risk 非法 | 修正为"高/低" |
| 单位货值不能为负 / 切线成本不能为负 / 生产时间不能为负 / 物流时间不能为负 | 数值字段为负 | 修正为 ≥0 数字 |
| 满足率目标须在 0~1 之间 | service_level 越界 | 修正为 0~1 小数（如 0.95） |
| 组批窗口须大于 0 | batch_window ≤0 | 修正为正数（天） |
| 基线方法仅支持移动平均/指数平滑/阶跃检测/借用参考 | base_method 非法 | 修正为四种方法之一 |
| 基线参数须为合法 JSON 字符串 | base_params 非 JSON 对象 | 改为合法 JSON（如 `{"alpha":0.3}`） |
| 基线参数与基线方法不匹配 | 缺该方法必需键 | 补齐必需键（移动平均 window / 指数平滑 alpha / 阶跃检测 threshold / 借用参考 ref_material） |
| 移动平均 window 须为 3~12 的整数 | MA window 越界或非整数 | 修正 window ∈ [3,12] |
| 指数平滑 alpha 须在 0~1 之间 | ES alpha 越界 | 修正 alpha ∈ [0,1] |
| 阶跃检测 threshold 须在 0~1 之间 | Step threshold 越界 | 修正 threshold ∈ [0,1] |
| 借用参考 ref_material 必填 / 不存在 | Reference 缺参考物料或物料不存在 | 提供已存在的参考物料号（先 `list` 核对） |
| 拟合版本不能为空 | set_fit_params 缺 fit_version | 补传 YYYYMM 版本号（如 202608） |
| 分页参数非法 | list 的 page/size 非整数 | 传整数页码/条数或省略用默认 |
| 导入数据须为行列表 / 行数据须为对象 | import_batch 入参格式错误 | 传行对象数组（每行 dict） |
