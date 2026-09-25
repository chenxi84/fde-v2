# decision 使用要点

**管什么**：一次**技术决策**（选哪个方案）：评价准则 + 备选方案 + 打分 + 结论。
打分用的**度量**在『技术度量』、依据的**评审**在『评审』。

## 标准工作流（按此顺序）

1. `create` — 登记议题（`topic` 必填 + `eval_method`，缺省 `weighted_matrix`），落「提出」态
2. `add_criterion` ×N — **先**定义评价准则（+ 权重，正整数、默认 1）
3. `add_option` ×N — **再**登记备选方案（可反复增补到出结论）
4. `start` — 启动权衡：「提出」→「权衡中」
5. `score_option` ×N — 逐方案打分（0~100 整数，可反复改分）
6. `conclude` — 作决策：`chosen_seq`（选中方案序号）+ 依据 → 「已决策」
7. `implement` — 实施 → 「已实施」（**硬终态**）

核对用：`list`（按评价方法 / 状态 / 责任人筛）→ `get`（主档 + 准则 `criteria` + 方案 `options` + `top_seq` / `top_score`）。

## 前置条件与禁忌

- **顺序闸**：`start` 要求准则清单非空（报「还没有评价准则，不能开始权衡」）；提出态不能 `score_option` / `conclude`（报「须先启动权衡」）；`implement` 只认「已决策」。
- **`conclude` 三条硬闸**（报错话术取决于它）：① 备选方案**少于两个**不许结论（"什么都不做"也应登记成一个方案）；② 选中的方案**必须有评价得分**（`0` 是有效的分，与「未打分」不同）；③ 选中的**不是最高分**方案时 `rationale` **必填**（报「必须给出依据」）。最高分口径：得分高者优先、**同分取序号小者**。
- **守卫顺序**：硬终态 → 已决策冻结 → 重复态 → 正常分支；`conclude` 内为 序号存在 → 方案数 ≥ 2 → 选中方案有得分 → 非最高分须依据。
- **已决策后内容冻结**（结论是快照）：`update` / `add_criterion` / `add_option` / `score_option` / 再 `conclude` / `start` 全拒；「已实施」再加 `implement` 也拒。**没有"从已决策回退"的服务**——要改只能新建一个议题。
- 字典：`eval_method` ∈ `weighted_matrix` / `trade_study` / `cost_benefit` / `decision_tree` / `influence_diagram` / `ahp` / `borda` / `utility` / `simulation` / `testing` / `review_meeting`（加权决策矩阵 / 权衡研究 / 成本收益分析 / 决策树 / 影响图 / 层次分析法 / 波达计数 / 效用分析 / 仿真 / 测试验证 / 评审会商）。
- 编号形如 `DC-001`；得分 0~100 整数、权重正整数；准则**只能新增**（没有改 / 删准则的服务）。
- `measure_no` 是弱引用文本，本应用**不校验**该度量是否存在。

## 出错时

上面的要点没覆盖的细节（完整参数表、错误码含义），用
`platform_read_app_doc(app="nasa_pms/decision", doc="应用详设")` 读完整设计再处置。
