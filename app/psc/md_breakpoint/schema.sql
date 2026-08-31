CREATE TABLE IF NOT EXISTS md_breakpoint (
                bp_id           INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_no     TEXT NOT NULL,
                old_material_no TEXT NOT NULL,
                new_material_no TEXT NOT NULL,
                switch_time     TEXT NOT NULL,
                ecn_no          TEXT,
                disabled        INTEGER NOT NULL DEFAULT 0,
                UNIQUE (customer_no, old_material_no, new_material_no, switch_time)
            );

CREATE INDEX IF NOT EXISTS idx_md_breakpoint_customer_no ON md_breakpoint (customer_no);

CREATE INDEX IF NOT EXISTS idx_md_breakpoint_old_material_no ON md_breakpoint (old_material_no);

CREATE INDEX IF NOT EXISTS idx_md_breakpoint_new_material_no ON md_breakpoint (new_material_no);
