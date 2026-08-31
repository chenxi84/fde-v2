CREATE TABLE IF NOT EXISTS md_monthly_version (
                version_no    TEXT PRIMARY KEY,
                anchor_period TEXT NOT NULL,
                opening_date  TEXT NOT NULL,
                lock_status   TEXT NOT NULL DEFAULT '草稿'
                    CHECK (lock_status IN ('草稿', '发布（锁定）', '冻结'))
            );

CREATE INDEX IF NOT EXISTS idx_mdv_lock_status ON md_monthly_version (lock_status);
