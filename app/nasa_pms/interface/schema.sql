-- 接口聚合（interface）—— 主档 + 一张**聚合内子表**（版本变更通知记录）。
--
-- ⚠ 两张表同库同事务：`architecture.md` 聚合根卡 9 的 I-2 明确 ——
--    **接口版本变更必须通知两端（变更记录同事务）**。
--    通知记录用 `(if_no, seq)` 复合主键：seq 只在**本接口内**唯一，没有全局业务标识，
--    因此它不是第二个聚合（跨接口的「变更通知台账」是查询视图 `list_changes`）。
--
-- ⚠ 本应用的「接口」是**系统/分系统之间的接口约定（ICD）**，不是代码里的 API 接口 ——
--    材料 §6.3 Interface Management + 附录 L（Interface Requirements）的产物。
--    两端（提供方 / 使用方）是**必填**：卡片 I-1「接口必须明确两端（提供方与使用方都不能为空）」
--    在库里落成两个 NOT NULL 列（校验由 `interface.py` 的 `_check_ends` 兜底，DDL 只做结构声明）。

CREATE TABLE IF NOT EXISTS interface (
    if_no       TEXT PRIMARY KEY,               -- 接口编号 IF-<三位序号>，落库不可变（BR-06）
    if_name     TEXT NOT NULL,                  -- 接口名称
    if_type     TEXT NOT NULL,                  -- 接口类型：icd / ird / idd / icp（材料 §6.3.1.3 的四类接口文档）
    provider    TEXT NOT NULL,                  -- 提供方（接口的一端，I-1：不能为空）
    consumer    TEXT NOT NULL,                  -- 使用方（接口的另一端，I-1：不能为空）
    icd_content TEXT,                           -- 约定内容（ICD 正文摘要 / 条款，选填）
    version     TEXT,                           -- 当前版本（字母修订版 A/B/C…；未定版时为空，BR-03）
    status      TEXT NOT NULL DEFAULT 'defined',-- defined / released / changing / frozen
    ci_no       TEXT,                           -- 关联配置项编号（弱引用 configuration_item，选填，BR-08）
    freeze_note TEXT,                           -- 冻结说明（freeze 时写入）
    owner       TEXT,                           -- 接口责任人
    project_no  TEXT                            -- 所属项目
);

-- 版本变更通知记录 —— 卡片 I-2 的落点：**每次版本变更恰好两条**（提供方一条、使用方一条）。
-- 材料 §6.3.1.2.4 的 IWG 职责是 "establish communication links between those responsible for
-- interfacing systems"（把变化传到两端是接口管理的本职）；§6.3.1.3 又要求跨方批准
-- （"For interfaces that require approval from all sides, unanimous approval is required"）——
-- 通知与批准的前提都是"两端都在记录里"。
CREATE TABLE IF NOT EXISTS interface_change (
    if_no       TEXT NOT NULL,                  -- 所属接口（聚合内子表，无独立标识）
    seq         INTEGER NOT NULL,               -- 通知序号，本接口内唯一（每次变更占两个：提供方 + 使用方）
    action      TEXT NOT NULL,                  -- 因何通知：release（首次发布定版）/ revise（版本变更）
    old_version TEXT,                           -- 变更前版本（首次发布时为空）
    new_version TEXT NOT NULL,                  -- 变更后版本
    party       TEXT NOT NULL,                  -- 通知到的哪一端：provider / consumer
    party_name  TEXT NOT NULL,                  -- 该端名称快照（通知对象，便于"通知了谁"可追溯）
    reason      TEXT,                           -- 变更原因（材料 §6.3.1.3 的 rationale for interface decisions）
    PRIMARY KEY (if_no, seq)
);

CREATE INDEX IF NOT EXISTS idx_if_status ON interface (status);
CREATE INDEX IF NOT EXISTS idx_if_type ON interface (if_type);
CREATE INDEX IF NOT EXISTS idx_if_provider ON interface (provider);
CREATE INDEX IF NOT EXISTS idx_if_consumer ON interface (consumer);
CREATE INDEX IF NOT EXISTS idx_if_ci ON interface (ci_no);
CREATE INDEX IF NOT EXISTS idx_if_change_party ON interface_change (party);
CREATE INDEX IF NOT EXISTS idx_if_change_action ON interface_change (action);
