# stakeholder 使用要点

**管什么**：相关方主数据（机构 / 人员）及其**期望清单**。编号由外部系统给定，本应用**没有 `create` / 没有 `delete` / 没有状态机**。

## 标准工作流（按此顺序）

1. `upsert(sh_no, name, sh_type, duty=None, org=None, contact=None, project_no=None)` — **唯一**写主档的入口：编号已存在即更新、不存在才新增（幂等）
2. `add_expectation(sh_no, statement, kind, source, moe=None, committed=None, note=None)` — 在该相关方名下登记期望，`seq` 本相关方内自增（从 1），`committed` 缺省 0
3. `update_expectation(sh_no, seq, statement=None, kind=None, source=None, moe=None, committed=None, note=None)` — 改期望（含给出承诺 / 撤回承诺）

查询用 `list`（`sh_type` / `project_no` 精确，`keyword` 跨 编号 / 名称 / 所属机构 / 职责 模糊，分页 `{items, total}`）→ `get`（主档 + `expectations` + `expectation_total` / `committed_total`）。

## 前置条件与禁忌

- **`upsert` 的部分更新语义（最容易踩）**：`duty` / `org` / `contact` / `project_no` 传 `None`（不传）= **不改**，传**空串 = 清空**。做增量同步时别为了"补全"把没拿到的字段传空串，那会抹掉已有内容。`sh_no` / `name` / `sh_type` 三项必填，校验顺序：编号 → 名称 → 类型。
- **没有删除**：相关方与期望都删不掉；要"停用"只能改内容或写 `note`。
- **`update_expectation` 守卫顺序**（报错取决于它）：相关方存在 → `seq` 正整数 → `seq` 命中（否则「利益相关者 X 没有序号为 N 的期望」）→ **承诺冻结** → 逐字段校验 → **合并后**的 MOE 校验 → 无字段可改则拒。
- **承诺冻结（BR-07）**：`committed=1` 的期望，`statement` / `kind` / `source` / `moe` 不可改（报「已获相关方承诺…要改请先撤回承诺（committed=0，BR-07）」），**只改 `note` 会被放行**。**撤回与改写可在同一次调用完成**（`committed=0` + 新陈述）。
- **MOE 判的是合并后的口径**：把类别改成 `moe` 而库里该条口径为空 → 拒（「必须填写度量口径（BR-06）」），同一次调用补齐即可。
- 字典：`sh_type` ∈ customer / contractor / internal_org；`kind` ∈ need / goal / objective / moe / constraint（必填）；`statement` / `source` 必填。`committed` 归一：true / 1 / yes / y / 是 → 1，false / 0 / no / n / 否 / 空串 → 0，**其余一律拒绝**。
- `seq` 是**聚合内序号、不是业务编号**——跨应用引用一条期望必须同时给 `sh_no` 与 `seq`；期望明细**只在 `get`**（`list` 只给两个计数）。
