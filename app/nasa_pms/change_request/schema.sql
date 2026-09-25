CREATE TABLE IF NOT EXISTS change_request (
    cr_no           TEXT PRIMARY KEY,                 -- 变更请求编号，落库后不可变（BR-03）
    title           TEXT NOT NULL,                    -- 变更请求标题（这次要改什么）
    requester       TEXT NOT NULL,                    -- 申请方（材料 FIGURE 6.5-4 的 Originator）
    ci_nos          TEXT,                             -- 影响的配置项编号，逗号分隔（BR-01：ci/req 至少一个）
    req_nos         TEXT,                             -- 影响的需求编号，逗号分隔（BR-01）
    description     TEXT,                             -- 变更说明（为什么改、改成什么）
    impact_analysis TEXT,                             -- 影响分析（analyze 登记，BR-02 的审批前置）
    decision_note   TEXT,                             -- 审批意见（BR-02：审批时必填，与状态同事务落库）
    approver        TEXT,                             -- 审批人 / CCB 代表（材料 FIGURE 6.5-4 的 CCB）
    implement_note  TEXT,                             -- 实施说明（implement 登记）
    status          TEXT NOT NULL DEFAULT 'submitted',-- submitted / analyzing / reviewing / approved / rejected / implemented
    project_no      TEXT                              -- 所属项目
);

CREATE INDEX IF NOT EXISTS idx_cr_status ON change_request (status);
CREATE INDEX IF NOT EXISTS idx_cr_requester ON change_request (requester);
CREATE INDEX IF NOT EXISTS idx_cr_project ON change_request (project_no);
