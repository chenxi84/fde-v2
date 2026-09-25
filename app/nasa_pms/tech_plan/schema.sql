-- 技术计划聚合（tech_plan）—— 主档 + 一张**聚合内子表**（版本台账 plan_version）。
--
-- ⚠ 两张表同库同事务：`architecture.md` 聚合根卡 10 的 **I-2**「计划随阶段推进更新版本，
--    历史版本保留」要求版本历史**随本聚合同事务维护** ——
--    版本台账不是另一个聚合，它是「这一版被批了」这件事的记录，无独立标识
--    （`(plan_no, seq)` 复合主键，seq 只在计划内唯一），由 `approve` 在**同一次调用**里
--    连同状态变更一起落库（同一连接，平台保证一次服务调用一个事务）。
--    **I-1**「每个阶段至少有一份已批准的该类计划（计划与阶段绑定）」分两面落地：
--      · 「计划与阶段绑定」= `phase` 必填且过阶段字典（BR-02）；
--      · 「生效唯一」= 同一 (plan_type, phase) 下只允许一份「已批准」，`approve` 同事务校验（BR-03）；
--      · 「至少一份」= **集合层面**的事实（缺计划的阶段没有任何写入动作可以被拦截）——
--        落在 `coverage` 这个**查询视图**上，即下面两张表组合出来的覆盖矩阵
--        （材料附录 K TABLE K-1 就是这张矩阵）。

CREATE TABLE IF NOT EXISTS tech_plan (
    plan_no     TEXT PRIMARY KEY,                -- 计划编号 PLAN-<三位序号>，落库不可变（BR-01）
    name        TEXT NOT NULL,                   -- 计划名称（列表与详情的第一识别项）
    plan_type   TEXT NOT NULL,                   -- 计划类型：semp / verification / integration / …（BR-02 字典，I-1「该类计划」的「类」）
    phase       TEXT NOT NULL,                   -- 覆盖阶段：pre_a / a / b / c / d / e（BR-02 字典；I-1「计划与阶段绑定」）
    maturity    TEXT NOT NULL DEFAULT 'approach',-- 成熟度：approach / preliminary / baseline / update（BR-07，附录 K 图例 A/P/B/U）
    version     INTEGER NOT NULL DEFAULT 1,      -- 当前版本号（V1 起，revise 递增 —— I-2「更新版本」）
    status      TEXT NOT NULL DEFAULT 'draft',   -- draft / in_review / approved / revised
    scope       TEXT,                            -- 计划范围说明（这份计划管什么）
    revise_note TEXT,                            -- 最近一次修订说明（revise 写入 —— 由哪一版走到这一版的来由）
    owner       TEXT,                            -- 计划责任人
    project_no  TEXT                             -- 所属项目
);

-- 版本台账（**曾获批的版本**留痕 —— 卡片 I-2「历史版本保留」的落点）。
-- 每次 `approve` 落一行：这一版批了、批时覆盖哪个阶段、什么成熟度、谁批的。
-- ⚠ 非主档字段的**快照**：计划随后修订到新阶段时，本表里那一行**不改**（口径不回溯改写）。
CREATE TABLE IF NOT EXISTS plan_version (
    plan_no   TEXT NOT NULL,                     -- 所属计划（聚合内子表，无独立标识）
    seq       INTEGER NOT NULL,                  -- 台账序号，本计划内唯一（落账次序，不随版本号回填）
    version   INTEGER NOT NULL,                  -- 版本号（与批准当刻主档的 version 一致；只增不减）
    phase     TEXT NOT NULL,                     -- 该版本批准时覆盖的阶段（I-1 覆盖矩阵按它统计）
    maturity  TEXT NOT NULL,                     -- 该版本批准时的成熟度（快照）
    approver  TEXT NOT NULL,                     -- 批准人（BR-08：批准要记名留痕）
    note      TEXT,                              -- 审批意见（选填）
    PRIMARY KEY (plan_no, seq)
);

CREATE INDEX IF NOT EXISTS idx_plan_type ON tech_plan (plan_type);
CREATE INDEX IF NOT EXISTS idx_plan_phase ON tech_plan (phase);
CREATE INDEX IF NOT EXISTS idx_plan_status ON tech_plan (status);
CREATE INDEX IF NOT EXISTS idx_plan_owner ON tech_plan (owner);
CREATE INDEX IF NOT EXISTS idx_planver_phase ON plan_version (phase);
CREATE INDEX IF NOT EXISTS idx_planver_version ON plan_version (plan_no, version);
