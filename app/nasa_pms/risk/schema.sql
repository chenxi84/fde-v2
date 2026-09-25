CREATE TABLE IF NOT EXISTS risk (
    risk_no      TEXT PRIMARY KEY,                   -- 风险编号，落库后不可变（BR-04）
    title        TEXT NOT NULL,                      -- 风险标题
    statement    TEXT,                               -- 风险情景（触发事件 → 不良后果的链条，§6.4 风险三元组第 1 项）
    category     TEXT NOT NULL,                      -- technical / cost / schedule / programmatic / safety（BR-05）
    likelihood   INTEGER,                            -- 可能性 1..5（未评估为 NULL）
    consequence  INTEGER,                            -- 后果严重度 1..5（未评估为 NULL）
    risk_score   INTEGER,                            -- 风险值 = 可能性 × 后果（推导，BR-01）
    risk_level   TEXT,                               -- low / medium / high / critical（推导，BR-01，不可直接写）
    mitigation   TEXT,                               -- 缓解措施（经 mitigate 登记）
    req_no       TEXT,                               -- 受影响的（技术）需求编号，弱引用 requirement（可悬空、可留空）
    owner        TEXT,                               -- 责任人
    status       TEXT NOT NULL DEFAULT 'identified', -- identified / analyzing / mitigating / closed / accepted
    disposition  TEXT,                               -- 处置结论：mitigated / transferred / accepted（BR-02，关闭才写）
    close_note   TEXT,                               -- 处置说明
    project_no   TEXT                                -- 所属项目
);

CREATE INDEX IF NOT EXISTS idx_risk_status ON risk (status);
CREATE INDEX IF NOT EXISTS idx_risk_category ON risk (category);
CREATE INDEX IF NOT EXISTS idx_risk_level ON risk (risk_level);
CREATE INDEX IF NOT EXISTS idx_risk_req ON risk (req_no);
