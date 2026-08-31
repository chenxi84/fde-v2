CREATE TABLE IF NOT EXISTS task (
                task_no TEXT PRIMARY KEY NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT,
                assignee_member_no TEXT NOT NULL,
                priority TEXT NOT NULL CHECK (priority IN ('low', 'high')),
                status TEXT NOT NULL DEFAULT '待办' CHECK (status IN ('待办', '进行中', '已完成'))
            );

CREATE INDEX IF NOT EXISTS idx_task_assignee_member_no ON task (assignee_member_no);

CREATE INDEX IF NOT EXISTS idx_task_status ON task (status);

CREATE INDEX IF NOT EXISTS idx_task_priority ON task (priority);

CREATE INDEX IF NOT EXISTS idx_task_status_assignee ON task (status, assignee_member_no);
