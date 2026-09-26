CREATE TABLE IF NOT EXISTS activity (
    act_no            TEXT PRIMARY KEY,                 -- 活动编号（ACT-001 起，系统生成，落库不可变）
    name              TEXT NOT NULL,                    -- 名称：**全组唯一**（BR-06，§5.5.5）
    kind              TEXT NOT NULL DEFAULT 'activity', -- summary / activity / milestone（§5.5.5）
    phase             TEXT,                             -- 边界标记：start / finish（只有它能单向，BR-01）
    wbs_no            TEXT NOT NULL,                    -- 挂靠的 WBS **叶子**元素（跨应用弱引用，BR-05）
    duration_days     INTEGER NOT NULL DEFAULT 0,       -- 工期（口径由日历的 unit 决定）；里程碑恒 0（BR-04）
    -- 逻辑链：结构化字符串 `PRED[:关系类型[:滞后[:理由]]]`，逗号分隔。
    --   例：`ACT-001`（= FS+0）· `ACT-002:SS:2` · `ACT-003:FF:0:与总装并行`
    --   ⚠ 关系类型是四值枚举（FS/SS/FF/SF，§5.5.8.2「four relationship models」）；
    --     非 FS 必须给**理由**（材料要求记录非标准依赖的缘由）；滞后可负（= lead）
    predecessors      TEXT,
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

-- 工作日历（§5.5.9.2「Define Calendars」）：P/p 通常有一个**默认日历**定义工作日与非工作日。
-- ⚠ `unit` 是**项目级口径**（材料 §5.5.9.1：要用 edays 还是 days「be consistent throughout
--   the schedule」）—— 所以它挂日历上，不逐条活动设，从建模上保证全表一个口径。
CREATE TABLE IF NOT EXISTS work_calendar (
    cal_no     TEXT PRIMARY KEY,                  -- 日历编号（CAL-001 起）
    name       TEXT NOT NULL,                     -- 日历名（如「项目默认日历」）
    unit       TEXT NOT NULL DEFAULT 'days',      -- days（工作日，跳过周末与假日）/ edays（日历天，忽略非工作时段）
    holidays   TEXT,                              -- 假日：逗号分隔的 YYYY-MM-DD（工作日历下跳过；edays 下忽略）
    is_default INTEGER NOT NULL DEFAULT 0         -- 默认日历（1 只能有一个）
);
