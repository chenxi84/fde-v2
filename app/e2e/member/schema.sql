CREATE TABLE IF NOT EXISTS member (
                member_no TEXT NOT NULL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL CHECK (role IN ('admin', 'member'))
            );

CREATE INDEX IF NOT EXISTS idx_member_role ON member (role);

CREATE INDEX IF NOT EXISTS idx_member_name ON member (name);

CREATE INDEX IF NOT EXISTS idx_member_created_at ON member (created_at);
