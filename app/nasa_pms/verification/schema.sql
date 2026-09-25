CREATE TABLE IF NOT EXISTS verification (
    ver_no     TEXT PRIMARY KEY,                -- 验证项编号，落库后不可变（BR-04）
    req_no     TEXT NOT NULL,                   -- 对应需求：强关联，必须挂在一条需求上（BR-01）
    method     TEXT NOT NULL,                   -- inspection / analysis / demonstration / test（BR-05）
    phase      TEXT NOT NULL,                   -- 验证阶段：材料附录 D TABLE D-1 的 8 个阶段（BR-05）
    status     TEXT NOT NULL DEFAULT 'planned', -- planned / executing / passed / failed / closed
    result     TEXT,                            -- 判定结果：pass / fail（未判定为 NULL）
    evidence   TEXT,                            -- 证据：材料 TABLE D-1「Results Indicator」（BR-02）
    follow_up  TEXT,                            -- 后续处置：判定「不通过」时必填（BR-02）
    criteria   TEXT,                            -- 成功判据：材料 TABLE D-1「Verification Success Criteria」
    owner      TEXT,                            -- 承担验证的责任人 / 执行方
    project_no TEXT,                            -- 所属项目
    close_note TEXT                             -- 关闭说明（`close(note=…)` 落库，2026-09-25 起留痕）
);

CREATE INDEX IF NOT EXISTS idx_ver_status ON verification (status);
CREATE INDEX IF NOT EXISTS idx_ver_req ON verification (req_no);
CREATE INDEX IF NOT EXISTS idx_ver_method ON verification (method);
