CREATE TABLE IF NOT EXISTS activity (
    act_no            TEXT PRIMARY KEY,                 -- 活动编号（ACT-001 起，系统生成，落库不可变）
    name              TEXT NOT NULL,                    -- 名称：**全组唯一**（BR-06，§5.5.5）
    kind              TEXT NOT NULL DEFAULT 'activity', -- summary / activity / milestone（§5.5.5）
    phase             TEXT,                             -- 边界标记：start / finish（只有它能单向，BR-01）
    wbs_no            TEXT NOT NULL,                    -- 挂靠的 WBS **叶子**元素（跨应用弱引用，BR-05）
    duration_days     INTEGER NOT NULL DEFAULT 0,       -- 工期（**工作日**）；里程碑恒 0（BR-04，§5.5.9）
    predecessors      TEXT,                             -- 前置活动编号，逗号分隔（逻辑链，§5.5.8）
    owner             TEXT,                             -- 责任方（P/S 与 Technical Lead 一起定，§5.5.5）
    status            TEXT NOT NULL DEFAULT 'planned',  -- planned / in_progress / completed
    percent_complete  INTEGER NOT NULL DEFAULT 0,       -- 完成百分比（§7.3）
    actual_start      TEXT,                             -- 实绩：实际开始（record_progress 写）
    actual_finish     TEXT,                             -- 实绩：实际完成（record_progress 写）
    baseline_start    TEXT,                             -- 基线日期：baseline 时由派生日期冻住（§7.3）
    baseline_finish   TEXT,                             -- ⚠ 回填实绩**绝不修改**这两列（BR-08）
    change_no         TEXT,                             -- 基线后修订挂的变更号（BR-07）
    note              TEXT                              -- 备注（材料提到 IMS 的 notes 记来源，§5.5.6）
);

CREATE INDEX IF NOT EXISTS idx_act_wbs ON activity (wbs_no);
CREATE INDEX IF NOT EXISTS idx_act_status ON activity (status);
CREATE INDEX IF NOT EXISTS idx_act_kind ON activity (kind);
CREATE INDEX IF NOT EXISTS idx_act_baseline ON activity (baseline_start);
