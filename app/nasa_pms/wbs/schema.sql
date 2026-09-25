CREATE TABLE IF NOT EXISTS wbs_element (
    wbs_no            TEXT PRIMARY KEY,                 -- 层级十进制码，落库后不可变（BR-07，§3.4.2）
    title             TEXT NOT NULL,                    -- 元素名称：必须产品导向（BR-04，§3.5.2）
    parent_no         TEXT,                             -- 父元素编号（顶层为 NULL，§3.4.4d）
    level             INTEGER NOT NULL,                 -- 层级：由编号段数派生（BR-01，§3.4.2）
    kind              TEXT NOT NULL DEFAULT 'product',  -- product/enabling/ca/wp/pp（§3.3.4）
    description       TEXT,                             -- 内容描述：数量、相关工作、合同终项（§3.4.4c）
    scope_ref         TEXT,                             -- 范围定义出处（§3.4.4e）；**基线必填**（BR-03）
    spec_no           TEXT,                             -- 关联规范号（§3.4.4f）
    spec_title        TEXT,                             -- 关联规范名（§3.4.4f）
    charge_code       TEXT,                             -- 预算与报告号（§3.4.4h）
    owner             TEXT,                             -- 责任方（含控制账户经理，§3.2 / §3.3.4）
    req_nos           TEXT,                             -- 关联需求编号，逗号分隔（§3.3.3 交叉引用矩阵）
    rev_no            INTEGER NOT NULL DEFAULT 0,       -- 版次：每次落实变更 +1（§3.4.4g）
    rev_authorization TEXT,                             -- 修订授权：落实变更时记该变更号（§3.4.4g）
    change_no         TEXT,                             -- 当前挂着的变更号（§3.3.6）
    status            TEXT NOT NULL DEFAULT 'draft',    -- draft/baselined/in_change/closed
    close_note        TEXT                              -- 关闭说明（`close(note=…)` 落库）
);

CREATE INDEX IF NOT EXISTS idx_wbs_parent ON wbs_element (parent_no);
CREATE INDEX IF NOT EXISTS idx_wbs_status ON wbs_element (status);
CREATE INDEX IF NOT EXISTS idx_wbs_kind ON wbs_element (kind);
