CREATE TABLE IF NOT EXISTS md_part_replace (
                rel_no          TEXT PRIMARY KEY NOT NULL,
                old_material_no TEXT NOT NULL,
                new_material_no TEXT NOT NULL,
                ecn_no          TEXT,
                status          TEXT NOT NULL DEFAULT '生效',
                UNIQUE (old_material_no, new_material_no)
            );

CREATE INDEX IF NOT EXISTS idx_md_part_replace_status ON md_part_replace (status);

CREATE INDEX IF NOT EXISTS idx_md_part_replace_old_material_no ON md_part_replace (old_material_no);

CREATE INDEX IF NOT EXISTS idx_md_part_replace_new_material_no ON md_part_replace (new_material_no);
