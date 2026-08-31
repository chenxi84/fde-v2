CREATE TABLE IF NOT EXISTS md_project_part (
                project_no  TEXT NOT NULL,
                material_no TEXT NOT NULL,
                usage       INTEGER NOT NULL CHECK (usage > 0),
                PRIMARY KEY (project_no, material_no)
            );

CREATE INDEX IF NOT EXISTS idx_md_project_part_material ON md_project_part (material_no);
