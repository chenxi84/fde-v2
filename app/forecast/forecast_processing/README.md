# forecast_processing -- 预测加工

## 一、应用简介
预测加工聚合根。基线->各调整->独立需求的加工总账，单头-明细结构。单头主键 = prc_batch；明细主键 = prc_batch + oem_code + plant_code + part_no + period。数据存同名 SQLite 库。跨应用调用：forecast_baseline.list、forecast_snapshot.list。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__forecast_processing__create_batch` | base_batch*(str), fcst_version*(str) | 创建加工批次并自动从基线行集生成明细行 |
| `forecast__forecast_processing__fill_line` | prc_batch*(str), oem_code*(str), plant_code*(str), part_no*(str), period*(str), conf_adj(float), conf_reason(str), trend_adj(float), trend_reason(str), onetime_adj(float), onetime_reason(str), onetime_tag(str) | 填写调整（置信/趋势/一次性），自动重算 indep_qty = base_qty + 三项调整之和 |
| `forecast__forecast_processing__review_line` | prc_batch*(str), oem_code*(str), plant_code*(str), part_no*(str), period*(str), chk_result*(str), chk_comment(str) | 核定/退回单行。chk_result: 通过/退回；退回必须附 chk_comment |
| `forecast__forecast_processing__finalize` | prc_batch*(str) | 全部核定后锁定批次。前置：全部行 chk_result=通过 |
| `forecast__forecast_processing__add_onetime_line` | prc_batch*(str), oem_code*(str), plant_code*(str), part_no*(str), period*(str), onetime_adj*(float), onetime_reason*(str), onetime_tag(str) | 月中附加一次性行（基线值为空，仅一次性调整） |
| `forecast__forecast_processing__get` | prc_batch*(str) | 取单头+全部明细 |
| `forecast__forecast_processing__get_line` | prc_batch*(str), oem_code*(str), plant_code*(str), part_no*(str), period*(str) | 取单行明细 |
| `forecast__forecast_processing__list_batches` | fcst_version(str), status(str), page(int), page_size(int) | 列表查询加工批次单头，返回 {total, items} |
| `forecast__forecast_processing__list_lines` | prc_batch*(str), oem_code(str), plant_code(str), part_no(str), period(str), chk_result(str), page(int), page_size(int) | 列表查询加工明细行，返回 {total, items} |

## 三、标准工作流
1. 基线确认后创建加工批次：`create_batch(base_batch, fcst_version)` -> 自动展开明细行
2. 销售/计划员 `fill_line(...)` 填写三类调整（conf_adj / trend_adj / onetime_adj），indep_qty 自动重算
3. 主管 `review_line(...)` 逐行核定（通过/退回），全部通过后 `finalize(prc_batch)` 锁定
4. 锁定后如需月中附加：`add_onetime_line(...)` 追加一次性行

## 四、前置条件与注意事项
- create_batch 前须确保 baseline 对应 base_batch 有数据
- 加工批次状态机：进行中 -> 全部核定（由 finalize 触发，校验全部通过）-> 已锁定
- 已锁定批次不可 fill_line 和 review_line，但 add_onetime_line 可追加
- onetime_tag 只能为 一次性/大一次性/断点
- chk_result=退回 必须附 chk_comment
- 当行已存在时 add_onetime_line 自动转为 fill_line 追加一次性调整

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "基线批次必填" / "预测版本必填" | 必填参数为空 | 补全缺失参数 |
| "加工批次 ... 已存在" | 同名 prc_batch 已存在 | 使用新批次号或直接 fill_line 现有批次 |
| "取基线批次 ... 数据失败" | 跨应用调 forecast_baseline 失败 | 检查 baseline 批次号和网络 |
| "基线批次 ... 无数据" | baseline 对应批次无行 | 先确认 baseline 已 generate+confirm |
| "加工批次已锁定，不可修改" | 批次已锁定 | 告知用户批次已锁定，仅可 add_onetime_line |
| "加工批次已锁定，不可核定" | 锁定后不可核定 | 告知用户批次已锁定 |
| "加工批次 ... 不存在" | prc_batch 查无此批次 | 先 list_batches 核对批次号 |
| "加工明细行不存在：..." | 指定行不存在 | 先 list_lines 核对行是否存在 |
| "一次...标签只能为 一次性/.../..." | onetime_tag 不在枚举中 | 修正标签为 一次性/大一次性/断点 |
| "核对结论只能为 通过/退回" | chk_result 不在枚举中 | 修正为 通过 或 退回 |
| "退回必须附理由" | chk_result=退回 但无 chk_comment | 请用户填写退回理由 |
| "还有 ... 行未通过核定，无法锁定" | finalize 前置条件不满足 | 告知用户哪些行未通过核定，建议逐行 review_line |
| "一次性调整原因必填" | add_onetime_line 缺少原因 | 请用户提供一次性调整原因 |
| "状态筛选不合法" | status 不是 进行中/全部核定/已锁定 | 修正状态筛选值 |
| "核对结论筛选不合法" | chk_result 不是 通过/退回 | 修正筛选值 |
| "数值参数非法" | 传入的数值无法转 float | 传入合法数值 |
| "分页参数非法" | page/page_size 无法转 int | 传入合法整数值 |
