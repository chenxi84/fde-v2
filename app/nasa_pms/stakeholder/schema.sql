-- 利益相关者聚合（stakeholder）—— 主档 + 一张**聚合内子表**（利益相关者期望）。
--
-- ⚠ 两张表同库同事务：`architecture.md` 聚合根卡 11 的 **I-1**「期望必须挂在本聚合内
--    （期望随相关方维护，无独立标识）」—— 期望不是另一个聚合，它没有独立业务编号，
--    只有 `(sh_no, seq)` 复合主键，随所属相关方一起被读写（`get` 一次带回）；
--    跨相关方的「期望汇总」连查询视图都不给（卡片 11 无「并入说明」类要求，见应用详设 §1.3.2）。
--
-- 数据来源：**外部同步（机构与人员）**，本系统只读引用、不维护源数据 ——
--    故本应用**没有 create / 没有 delete**，唯一写主档的入口是 `upsert`（幂等：存在即更新）。
--    主数据**没有状态机**（卡片 11：「状态机：无」）—— 表里也就没有 status 列，
--    不为了"与同组其它页一致"硬造状态。

CREATE TABLE IF NOT EXISTS stakeholder (
    sh_no      TEXT PRIMARY KEY,        -- 利益相关者编号（**由外部来源系统给定**，本系统不生成、落库不可变）
    name       TEXT NOT NULL,           -- 名称（机构名或人员名）
    sh_type    TEXT NOT NULL,           -- 类型：customer / contractor / internal_org（字典，见 BR-03）
    duty       TEXT,                    -- 职责（在项目里承担什么）
    org        TEXT,                    -- 所属机构（来源为「机构与人员」两处 —— 人员相关方靠它归口）
    contact    TEXT,                    -- 联系方式（材料 §4.1.1.2.2 的 elicit 手段要求"找得到人"）
    project_no TEXT                     -- 所属项目
);

-- 利益相关者期望（材料 §4.1.1.2.5「Define Stakeholder Expectations in Acceptable Statements」）
-- 聚合内子表：无独立标识（(sh_no, seq) 复合主键），随相关方一起被读写（卡片 11 的 I-1）
CREATE TABLE IF NOT EXISTS stakeholder_expectation (
    sh_no     TEXT NOT NULL,            -- 所属相关方（聚合内子表，无独立标识）
    seq       INTEGER NOT NULL,         -- 期望序号，本相关方内唯一
    statement TEXT NOT NULL,            -- 期望陈述（§4.1.1.2.5 的 "acceptable statements"）
    kind      TEXT NOT NULL,            -- 期望类别：need / goal / objective / moe / constraint（字典，见 BR-05）
    source    TEXT NOT NULL,            -- 期望来源（§4.1.1.2.7「should also capture the source of the expectation」）
    moe       TEXT,                     -- 度量口径（§4.1.1.2.6 Measures of Effectiveness；kind=moe 时必填，见 BR-06）
    committed INTEGER NOT NULL DEFAULT 0, -- 是否已获相关方承诺（§4.1.1.2.8 Obtain Stakeholder Commitments；0/1）
    note      TEXT,                     -- 备注（不受承诺冻结影响 —— 留痕用，见 BR-07）
    PRIMARY KEY (sh_no, seq)
);

CREATE INDEX IF NOT EXISTS idx_sh_type ON stakeholder (sh_type);
CREATE INDEX IF NOT EXISTS idx_sh_project ON stakeholder (project_no);
CREATE INDEX IF NOT EXISTS idx_sh_org ON stakeholder (org);
CREATE INDEX IF NOT EXISTS idx_sh_exp_kind ON stakeholder_expectation (kind);
CREATE INDEX IF NOT EXISTS idx_sh_exp_committed ON stakeholder_expectation (committed);
