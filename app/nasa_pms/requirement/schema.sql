CREATE TABLE IF NOT EXISTS requirement (
    req_no         TEXT PRIMARY KEY,              -- 需求编号，落库后不可变（BR-03）
    title          TEXT NOT NULL,                 -- 需求标题
    statement      TEXT,                          -- 需求正文（应可验证）
    req_type       TEXT NOT NULL,                 -- system / technical / interface / derived（BR-05）
    verify_method  TEXT,                          -- inspection / analysis / demonstration / test（BR-01）
    source_req_no  TEXT,                          -- 派生需求的上游需求（BR-02，弱引用可悬空）
    status         TEXT NOT NULL DEFAULT 'draft', -- draft / pending_review / baselined / obsolete
    owner          TEXT,                          -- 责任人
    project_no     TEXT,                          -- 所属项目（编号是**全局**唯一，不按项目分段，见 BR-03）
    baseline_ver   TEXT,                          -- 所属基线版本（未基线为 NULL）
    change_no      TEXT,                          -- 最近一次变更请求号（BR-04，可为空）
    void_reason    TEXT                           -- 作废理由（`obsolete(reason=…)` 落库，2026-09-25 起留痕）
);

CREATE INDEX IF NOT EXISTS idx_requirement_status ON requirement (status);
CREATE INDEX IF NOT EXISTS idx_requirement_type ON requirement (req_type);
CREATE INDEX IF NOT EXISTS idx_requirement_source ON requirement (source_req_no);
CREATE INDEX IF NOT EXISTS idx_requirement_baseline ON requirement (baseline_ver);
