# part_level_adj -- 零件级处理

## 一、应用简介
零件级处理聚合根。通用件合并/替换件合并/断点处理，产出 delta 作用回初步毛需求。主键 = adj_no（自动生成，格式 PAD-{fcst_version}-{序号}）。数据存同名 SQLite 库。无跨应用调用（纯自包含）。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__part_level_adj__create_generic_merge` | fcst_version*(str), period*(str), part_no*(str), adj_qty*(float), basis*(str) | 通用件合并调整：同零件多客户合并供应的调整量 |
| `forecast__part_level_adj__create_replace_merge` | fcst_version*(str), period*(str), part_no*(str), adj_qty*(float), basis*(str) | 替换件合并调整：新旧件替换关系下的合并调整量 |
| `forecast__part_level_adj__create_breakpoint_adj` | fcst_version*(str), period*(str), old_part*(str), new_part*(str), old_adj*(float), new_adj*(float), ecn_no*(str) | 断点成对调整：旧件截断负量 + 新件启动正量，自动生成 pair_no |
| `forecast__part_level_adj__get` | adj_no*(str) | 取单条处理单 |
| `forecast__part_level_adj__list` | fcst_version(str), func_type(str), part_no(str), period(str), page(int), page_size(int) | 列表查询，返回 {total, items} |
| `forecast__part_level_adj__summarize` | fcst_version*(str) | 按物料x期间聚合全部 delta（SUM adj_qty GROUP BY part_no, period, func_type） |

## 三、标准工作流
1. 通用件合并：`create_generic_merge(fcst_version, period, part_no, adj_qty, basis)` 创建单条调整
2. 替换件合并：`create_replace_merge(fcst_version, period, part_no, adj_qty, basis)` 创建单条调整
3. 断点处理：`create_breakpoint_adj(...)` 成对生成旧件截断+新件启动两条记录
4. 查看汇总：`summarize(fcst_version)` 按物料x期间查看全部 delta 汇总

## 四、前置条件与注意事项
- 每条调整的 adj_no 自动生成，格式 PAD-{fcst_version}-{序号}，确保唯一
- 断点处理成对生成两条记录，共享同一个 pair_no（格式 BP-{fcst_version}-{序号}）
- 断点处理中 ECN 号必填（断点依据）
- func_type 枚举：通用件合并/替换件合并/断点处理
- adj_qty 正数表示增量，负数表示减量（如断点旧件截断用负数）
- 无删除操作，调整以记录形式留存审计轨迹

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "版本号、期间、零件号均必填" | create_generic_merge / create_replace_merge 缺参数 | 补全三个参数 |
| "原因/依据必填" | basis 为空 | 请用户填写调整原因或依据 |
| "版本号和期间必填" | create_breakpoint_adj 缺版本或期间 | 补全参数 |
| "ECN号必填（断点依据）" | create_breakpoint_adj 缺 ecn_no | 请用户提供 ECN 编号 |
| "处理单号必填" | get 缺 adj_no | 补全处理单号 |
| "零件级处理 ... 不存在" | adj_no 查无记录 | 先 list 核对已存在的处理单号 |
| "功能类型只能为 通用件合并/替换件合并/断点处理" | func_type 筛选不合法 | 修正筛选值 |
| "版本号必填" | summarize 缺 fcst_version | 补全版本号 |
| "数值参数非法" | adj_qty 等无法转 float | 传入合法数值 |
| "分页参数非法" | page/page_size 无法转 int | 传入合法整数值 |
