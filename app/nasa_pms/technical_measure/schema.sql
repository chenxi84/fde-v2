-- 技术度量聚合（technical_measure）—— 主档 + 两张**聚合内子表**（实测值记录 / 告警记录）。
--
-- ⚠ 三张表同库同事务：`architecture.md` 聚合根卡 7 的 **I-1**「实测值超出阈值必须触发告警记录」
--    明确要求「度量与告警**同事务**」——
--    告警不是另一个聚合，它是「这次实测超阈值」这件事的记录，无独立标识（`(tpm_no, seq)` 复合主键），
--    与产生它的那条实测值**同一次 `record` 调用**落库（同一连接、平台保证一次调用一个事务）。
--    跨度量的「告警汇总」是**查询视图**（`list_alerts`），不是独立聚合。

CREATE TABLE IF NOT EXISTS technical_measure (
    tpm_no          TEXT PRIMARY KEY,               -- 度量编号 TPM-<三位序号>，落库不可变（BR-03）
    name            TEXT NOT NULL,                  -- 度量名称（材料 Appendix J §7.4 的 TPM 清单逐条即一个名称）
    category        TEXT NOT NULL,                  -- 类别：tpm / mop / kpp（BR-04，字典）
    direction       TEXT NOT NULL,                  -- 优化方向：higher / lower（BR-04，字典）——判定口径的一半
    unit            TEXT,                           -- 计量单位（如 % / kg / W；选填，仅用于展示与告警文案）
    target_value    REAL NOT NULL,                  -- 目标值（材料 Appendix J §7.4「derived from the MOEs and MOPs」的目标）
    threshold_value REAL NOT NULL,                  -- 阈值（Appendix B「Threshold Requirements: 最低可接受集」= descope 位置）
    baseline_ver    TEXT,                           -- 基线版本标记（baseline 时写 B1，rebaseline 递增；为空 = 未基线）
    change_no       TEXT,                           -- 最近一次改判定口径所依据的变更请求号（BR-02，rebaseline 写入）
    current_value   REAL,                           -- 当前实测值 = 最近一期实测值（由 record 同步，未测为 NULL）
    current_period  TEXT,                           -- 当前度量期次 = 最近一期的期次（由 record 同步）
    req_no          TEXT,                           -- 度量服务的需求编号，弱引用 requirement（可悬空、可留空）
    owner           TEXT,                           -- 度量责任人
    status          TEXT NOT NULL DEFAULT 'defined',-- defined / measuring / exceeded / corrected / closed
    close_note      TEXT,                           -- 关闭说明（关闭度量时写入）
    project_no      TEXT                            -- 所属项目
);

-- 实测值记录（材料 Appendix B「monitored by comparing the current actual achievement of the parameters
-- with that anticipated at the current time and on future dates」—— 要能看出趋势，就必须留序列）
CREATE TABLE IF NOT EXISTS tpm_reading (
    tpm_no          TEXT NOT NULL,                  -- 所属度量（聚合内子表，无独立标识）
    seq             INTEGER NOT NULL,               -- 期次序号，本度量内唯一
    period          TEXT NOT NULL,                  -- 度量期次（业务键，本度量内唯一 —— BR-07）
    measured_value  REAL NOT NULL,                  -- 实测值
    passed          INTEGER NOT NULL,               -- 1 = 在阈内 / 0 = 超阈值（判定推导值，不手填）
    note            TEXT,                           -- 备注（数据来源 / 测量工况，选填）
    PRIMARY KEY (tpm_no, seq)
);

-- 告警记录（I-1 的落点：实测值超出阈值时，与上表那条实测值**同事务**产生）
CREATE TABLE IF NOT EXISTS tpm_alert (
    tpm_no          TEXT NOT NULL,                  -- 所属度量（聚合内子表，无独立标识）
    seq             INTEGER NOT NULL,               -- 告警序号，本度量内唯一
    period          TEXT NOT NULL,                  -- 触发告警的度量期次（与实测值记录一致）
    measured_value  REAL NOT NULL,                  -- 触发时的实测值（快照）
    deviation       REAL NOT NULL,                  -- 超出量（恒为正：低于阈值或高于阈值的那部分）
    message         TEXT NOT NULL,                  -- 告警信息（人话：谁、哪一期、实测多少、阈值多少、差多少）
    status          TEXT NOT NULL DEFAULT 'open',   -- open / handled（经 correct 了结）
    handle_note     TEXT,                           -- 纠正措施（correct 时写入 —— 告警的处置结论）
    PRIMARY KEY (tpm_no, seq)
);

CREATE INDEX IF NOT EXISTS idx_tpm_status ON technical_measure (status);
CREATE INDEX IF NOT EXISTS idx_tpm_category ON technical_measure (category);
CREATE INDEX IF NOT EXISTS idx_tpm_direction ON technical_measure (direction);
CREATE INDEX IF NOT EXISTS idx_tpm_req ON technical_measure (req_no);
CREATE INDEX IF NOT EXISTS idx_tpm_reading_period ON tpm_reading (tpm_no, period);
CREATE INDEX IF NOT EXISTS idx_tpm_alert_status ON tpm_alert (status);
