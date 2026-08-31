CREATE TABLE IF NOT EXISTS md_project (
                project_no   TEXT NOT NULL PRIMARY KEY,
                project_name TEXT NOT NULL,
                stage        TEXT NOT NULL DEFAULT '进行中' CHECK (stage IN ('进行中', 'SOP', 'EOP')),
                sop_date     TEXT NOT NULL DEFAULT '',
                eop_date     TEXT NOT NULL DEFAULT '',
                owner        TEXT NOT NULL,
                veh_model    TEXT NOT NULL DEFAULT '',
                share        REAL
            );

CREATE INDEX IF NOT EXISTS idx_md_project_stage ON md_project (stage);
