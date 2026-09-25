CREATE TABLE IF NOT EXISTS configuration_item (
    ci_no        TEXT PRIMARY KEY,               -- 配置项编号，落库后不可变（BR-04）
    name         TEXT NOT NULL,                  -- 配置项名称
    ci_type      TEXT NOT NULL,                  -- hardware / software / document / model / data（BR-05）
    version      INTEGER NOT NULL DEFAULT 1,     -- 当前版本，只能递增（BR-01）
    released_ver INTEGER,                        -- 最近一次已发布的版本（NULL = 从未发版；BR-02）
    baseline     TEXT,                           -- 所属基线：functional / allocated / product / as_deployed
    baseline_ver TEXT,                           -- 基线版本标记（如 B1），未纳入基线为 NULL
    status       TEXT NOT NULL DEFAULT 'draft',  -- draft / controlled / released / archived
    owner        TEXT,                           -- 责任人
    change_no    TEXT,                           -- 最近一次变更请求号（BR-03，未约为空）
    project_no   TEXT                            -- 所属项目
);

CREATE INDEX IF NOT EXISTS idx_ci_status ON configuration_item (status);
CREATE INDEX IF NOT EXISTS idx_ci_type ON configuration_item (ci_type);
CREATE INDEX IF NOT EXISTS idx_ci_baseline ON configuration_item (baseline);
