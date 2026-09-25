-- 决策聚合（decision）—— 主档 + 两张**聚合内子表**（评价准则 / 备选方案）。
--
-- ⚠ 三张表同库同事务：`architecture.md` 聚合根卡 8 把「备选方案」列为该聚合的**内部实体**
--    （无独立标识）：它由 `add_option` 逐条登记、`score_option` 打分、`conclude` 指向其中之一，
--    全程只在本决策的事务里被读写。子表用 `(dec_no, seq)` 复合主键：seq 只在**本决策内**唯一，
--    没有全局业务标识。
--    「评价准则」同理（材料 §6.8.1.2.1 把它列为决策分析的第一个活动，随后才是识别备选方案）。

CREATE TABLE IF NOT EXISTS decision (
    dec_no         TEXT PRIMARY KEY,              -- 决策编号 DC-<三位序号>，落库不可变（BR-05）
    topic          TEXT NOT NULL,                 -- 决策议题（材料 §6.8.1 "understanding the decision needed"）
    issue          TEXT,                          -- 议题说明（材料 TABLE 6.8-1 第 2 节 Problem/Issue Description）
    measure_no     TEXT,                          -- 评价准则来源的技术度量编号（弱引用 technical_measure，该应用待建成）
    eval_method    TEXT NOT NULL DEFAULT 'weighted_matrix',  -- 评价方法（材料 §6.8.1.2.3 / §6.8.2，BR-07）
    status         TEXT NOT NULL DEFAULT 'proposed',         -- proposed / weighing / decided / implemented
    chosen_seq     INTEGER,                       -- 结论指向的备选方案序号（conclude 时写入，唯一入口）
    chosen_name    TEXT,                          -- 选中方案名称快照（报告要逐字引用被选中的方案）
    rationale      TEXT,                          -- 决策依据（选非最高分方案时**必填**，材料 §6.8.1.2.5 / BR-04）
    risk_note      TEXT,                          -- 选中方案的风险与收益（材料 TABLE 6.8-1 第 6 节）
    dissent        TEXT,                          -- 异议记录（材料 TABLE 6.8-1 第 8 节 Dissent）
    implement_note TEXT,                          -- 实施说明（实施时写入）
    owner          TEXT,                           -- 决策责任人（决策者 / 提出方）
    project_no     TEXT                            -- 所属项目
);

-- 评价准则（材料 §6.8.1.2.1 "Define the Criteria for Evaluating Alternative Solutions"：
--   types of criteria / acceptable range and scale / **the rank of each criterion by its importance**）
CREATE TABLE IF NOT EXISTS decision_criterion (
    dec_no    TEXT NOT NULL,                      -- 所属决策（聚合内子表，无独立标识）
    seq       INTEGER NOT NULL,                   -- 准则序号，本决策内唯一
    criterion TEXT NOT NULL,                      -- 准则名（如 成本 / 进度 / 风险 / 任务成功）
    weight    INTEGER NOT NULL DEFAULT 1,         -- 权重（准则的重要性排序，正整数，BR-08）
    PRIMARY KEY (dec_no, seq)
);

-- 备选方案（材料 §6.8.1.2.2 "Identify Alternative Solutions to Address Decision Issues"；
--   打分即 §6.8.1.2.4 的归一化评价结果 —— 决策矩阵按「准则 × 权重」加权后的可比得分）
CREATE TABLE IF NOT EXISTS decision_option (
    dec_no      TEXT NOT NULL,                    -- 所属决策（聚合内子表，无独立标识）
    seq         INTEGER NOT NULL,                 -- 方案序号，本决策内唯一
    name        TEXT NOT NULL,                    -- 方案名称（必填，BR-08）
    description TEXT,                             -- 方案说明（选填）
    score       INTEGER,                          -- 评价得分 0~100（未打分为 NULL，BR-08）；I-1 要求选中方案必须有分
    note        TEXT,                             -- 打分说明（选填）
    PRIMARY KEY (dec_no, seq)
);

CREATE INDEX IF NOT EXISTS idx_decision_status ON decision (status);
CREATE INDEX IF NOT EXISTS idx_decision_method ON decision (eval_method);
CREATE INDEX IF NOT EXISTS idx_decision_owner ON decision (owner);
