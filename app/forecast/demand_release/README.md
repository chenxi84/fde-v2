# demand_release -- 毛需求发布

## 一、应用简介
毛需求发布聚合根。加工链终点--已发布毛需求（物料x期间），净需求运算的唯一输入。单头主键 = rel_no；明细主键 = rel_no + line_no。数据存同名 SQLite 库。跨应用调用：forecast_processing.get、forecast_snapshot.lock_version、md_fcst_version.set_linked。

## 二、对外服务（工具）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `forecast__demand_release__create_draft` | prc_batch*(str) | 从已锁定加工批次创建发布草稿：按物料x期间汇总 indep_qty -> prelim_qty |
| `forecast__demand_release__apply_part_adj` | rel_no*(str), part_no*(str), period*(str), adj_qty*(float), func_type*(str), basis*(str) | 应用零件级处理量到明细行，累积 part_adj 并重算 rel_qty |
| `forecast__demand_release__publish` | rel_no*(str) | 发布：状态->已发布；联动锁定快照 V 版与月度版本；标记上一版本为已替代 |
| `forecast__demand_release__get` | rel_no*(str) | 取单头+全部明细（含 JSON 解析后的 part_adj / onetime_items / lineage） |
| `forecast__demand_release__get_line` | rel_no*(str), line_no*(int) | 取单行明细 |
| `forecast__demand_release__list` | fcst_version(str), part_no(str), period(str), status(str), page(int), page_size(int) | 列表查询发布单头（按零件筛选时 JOIN 明细），返回 {total, items} |
| `forecast__demand_release__get_diff` | rel_no*(str) | R_n vs R_n-1 差异视图：返回变动的物料x期间及差异量 |
| `forecast__demand_release__add_onetime_item` | rel_no*(str), part_no*(str), period*(str), onetime_adj*(float), reason*(str) | 月中附加一次性调整（仅已发布单可用） |

## 三、标准工作流
1. 加工批次锁定后：`create_draft(prc_batch)` -> 自动汇总 prelim_qty 并生成草稿
2. 应用零件级调整：`apply_part_adj(rel_no, part_no, period, adj_qty, func_type, basis)` 逐条应用
3. 确认无误后：`publish(rel_no)` 发布，自动联动锁定快照和月度版本
4. 查看差异：`get_diff(rel_no)` 对比上一版本变化
5. 发布后月中调整：`add_onetime_item(...)` 附加一次性项

## 四、前置条件与注意事项
- create_draft 的 prc_batch 必须已锁定（forecast_processing 状态=已锁定）
- rel_no 格式 REL-{fcst_version}-{序号}，自动生成
- 发布后状态不可回退；发布时自动锁定 forecast_snapshot 和 md_fcst_version
- publish 时自动将 prev_rel_no 标记为"已替代"
- list 按 part_no 筛选时会 JOIN 明细表（性能注意）
- add_onetime_item 仅"已发布"状态可用
- part_adj / onetime_items / lineage 以 JSON 存储，get/get_line 自动解析

## 五、错误处理（Agent 应对策略）

| 错误信息 | 含义 | Agent 应对 |
|---------|------|-----------|
| "加工批次必填" | create_draft 缺 prc_batch | 请用户提供加工批次号 |
| "加工批次 ... 不存在或取数失败" | 跨应用调 forecast_processing 失败 | 检查 prc_batch 是否存在 |
| "加工批次 ... 未锁定（当前状态：...），无法创建发布" | prc_batch 未锁定 | 先调 forecast_processing.finalize 锁定加工批次 |
| "发布单 ... 已存在" | rel_no 重复 | 检查 fcst_version 下是否已有发布单 |
| "发布单号、零件号、期间均必填" | apply_part_adj 缺参数 | 补全缺失参数 |
| "发布单已发布，不可修改" | apply_part_adj 时单已发布 | 告知用户已发布，使用 add_onetime_item 追加 |
| "发布单 ... 中无物料 ... 期间 ... 的行" | apply_part_adj 目标行不存在 | 先 get 查看发布单明细 |
| "发布单已被替代，无法发布" | 历史版本不可再发 | 使用最新版本的发布单 |
| "发布单号必填" | get/publish 缺 rel_no | 补全发布单号 |
| "发布单 ... 不存在" | rel_no 查无此单 | 先 list 核对发布单号 |
| "发布明细行不存在：..." | get_line 行不存在 | 先 get 查看明细行列表 |
| "仅已发布的发布单可月中附加一次性调整" | add_onetime_item 但状态非已发布 | 先 publish 发布单 |
| "发布单号、零件号、期间、原因均必填" | add_onetime_item 缺参数 | 补全四个参数 |
| "状态筛选不合法" | status 不是 草稿/已发布/已替代 | 修正状态筛选值 |
| "分页参数非法" | page/page_size 无法转 int | 传入合法整数值 |
