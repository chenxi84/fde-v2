-- 评审聚合（review）—— 主档 + 两张**聚合内子表**（评审项清单 / 行动项）。
--
-- ⚠ 三张表同库同事务：`architecture.md` 聚合根卡 5 的「并入说明」明确 ——
--    **行动项并入本聚合**（随评审结论同事务产生、无独立标识）；
--    跨评审的「行动项汇总」是**查询视图**（`list_actions`），不是独立聚合。
--    子表用 `(review_no, seq)` 复合主键：seq 只在**本评审内**唯一，没有全局业务标识。

CREATE TABLE IF NOT EXISTS review (
    review_no   TEXT PRIMARY KEY,               -- 评审编号 RV-<三位序号>，落库不可变（BR-04）
    title       TEXT NOT NULL,                  -- 评审标题
    review_type TEXT NOT NULL,                  -- 评审类型：mcr/srr/sdr/pdr/cdr/sir/trr/prr/orr/frr/sar（BR-05）
    phase       TEXT NOT NULL,                  -- 所属阶段：pre_a/a/b/c/d/e（BR-05）
    subject     TEXT NOT NULL,                  -- 评审对象（被评审的产品/文档/设计）
    plan_no     TEXT,                           -- 评审依据的计划编号（弱引用 tech_plan，该应用待建成）
    status      TEXT NOT NULL DEFAULT 'planned',-- planned / in_progress / concluded / tracking / closed
    conclusion  TEXT,                           -- 评审结论：pass / conditional / fail（出结论时写入，唯一入口）
    minutes     TEXT,                           -- 评审纪要（材料 6.7.1.3「Technical Review Reports/Minutes」）
    close_note  TEXT,                           -- 关闭说明（关闭评审时写入）
    owner       TEXT,                           -- 评审主持人 / 责任人
    project_no  TEXT                            -- 所属项目
);

-- 评审项清单（材料 §6.7.1.2.2："establishing each review's purpose, objective, and entry and success criteria"）
CREATE TABLE IF NOT EXISTS review_item (
    review_no   TEXT NOT NULL,                  -- 所属评审（聚合内子表，无独立标识）
    seq         INTEGER NOT NULL,               -- 评审项序号，本评审内唯一
    item        TEXT NOT NULL,                  -- 评审项内容
    criterion   TEXT,                           -- 评审准则 / 判据（选填）
    PRIMARY KEY (review_no, seq)
);

-- 行动项（材料 §6.7.1.2.2："identifying and resolving action items resulting from the review"；
-- 术语对应附录 A 的 RFA——Request for Action）
CREATE TABLE IF NOT EXISTS review_action (
    review_no   TEXT NOT NULL,                  -- 所属评审（聚合内子表，无独立标识）
    seq         INTEGER NOT NULL,               -- 行动项序号，本评审内唯一
    content     TEXT NOT NULL,                  -- 行动项内容
    owner       TEXT NOT NULL,                  -- 责任人（BR-02：必填）
    due_date    TEXT NOT NULL,                  -- 期限 YYYY-MM-DD（BR-02：必填）
    status      TEXT NOT NULL DEFAULT 'open',   -- open / done
    close_note  TEXT,                           -- 完成说明
    PRIMARY KEY (review_no, seq)
);

CREATE INDEX IF NOT EXISTS idx_review_status ON review (status);
CREATE INDEX IF NOT EXISTS idx_review_type ON review (review_type);
CREATE INDEX IF NOT EXISTS idx_review_phase ON review (phase);
CREATE INDEX IF NOT EXISTS idx_review_action_owner ON review_action (owner);
CREATE INDEX IF NOT EXISTS idx_review_action_status ON review_action (status);
