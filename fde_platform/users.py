"""FDE v2 平台 — 用户与角色管理（管理面，可插拔）。

授权模型（RBAC）：**授权单位是"应用下的开放服务"**（`应用.服务`，如 user.create）。
- **角色**（roles 表）= 岗位模板：自带一组服务授权（role_grants），`is_admin` 标志的角色
  绕过授权检查（全通）。内置 `admin`（管理员）/ `user`（普通用户）两个角色，可自建。
- **用户**绑定一个角色；另可加**个人特授**（service_grants），与角色授权取**并集**生效。
- 能否**调用**某服务 = 角色授权 ∪ 个人特授是否含它（is_admin 角色例外，全通）；
- 能否**看到/进入**某应用 = 并集中该应用下是否有≥1 个服务。
- **前端页面授权**（role_page_grants，角色级）：角色可获授前端页面（page_id 形如
  `crm:customer` / `_platform:agent`，清单由 view_registry 扫描 view/ 动态生成）。
  两个效力：① 视图菜单按页面授权渲染（admin 全量）；② **隐式服务放行**——页面源码
  扫描出的 svc() 调用（页→服务派生边）随页面授权一并放行，无需再逐个授服务。
  隐式放行仅对携带 `X-Fde-Page` 请求头（lib/api.js 自动注入）的调用生效；无头
  请求（MCP/Agent/CLI）仍按显式授权判定。服务台（console）仅 admin 可见、不可授权。

职责：
- 用户/角色/授权库 `config/auth.db`（users / roles / service_grants / role_grants 四张表）
- 用户 CRUD / 重置密码 / 换角色 / 个人特授整体替换；角色 CRUD / 角色授权整体替换
- 供鉴权与各调用入口使用的只读 helper（含会话感知的可见性过滤、登录态→ctx 映射）
- `/auth/*` 管理页面与操作（Blueprint）

可插拔（依赖方向单向、无环）：本模块**不 import auth.py**；连同 auth.py、login.html、
users.html 一起删除，平台自动回落无认证模式。自带 CLI：`python -m fde_platform.users --help`。
"""
import argparse
import re
import sqlite3
from pathlib import Path

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

# ── 常量 ────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "config" / "auth.db"

MIN_PASSWORD_LEN = 4

_USERNAME_RE = re.compile(r"^[^\s/\\]{1,32}$")
_ROLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")  # 与应用名同风格：小写蛇形
_PAGE_ID_RE = re.compile(r"^[a-z0-9_]+:[a-z0-9_]+$")   # '模块:页key'（_platform:agent 合法）

# 内置默认角色（新库播种；admin 的 is_admin=1 承接旧版"admin 全通"语义）
_DEFAULT_ROLES = (("admin", "管理员", 1), ("user", "用户", 0))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS roles (
    name       TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    is_admin   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user' REFERENCES roles(name),
    user_no       TEXT,
    department_no TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_user_no
    ON users(user_no) WHERE user_no IS NOT NULL;

CREATE TABLE IF NOT EXISTS service_grants (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    app_name   TEXT NOT NULL,
    service    TEXT NOT NULL,
    granted_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (user_id, app_name, service)
);

CREATE TABLE IF NOT EXISTS role_grants (
    role_name  TEXT NOT NULL REFERENCES roles(name) ON DELETE CASCADE,
    app_name   TEXT NOT NULL,
    service    TEXT NOT NULL,
    granted_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (role_name, app_name, service)
);

CREATE TABLE IF NOT EXISTS role_page_grants (
    role_name  TEXT NOT NULL REFERENCES roles(name) ON DELETE CASCADE,
    page_id    TEXT NOT NULL,              -- '模块:页key'，如 crm:customer / _platform:agent
    granted_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (role_name, page_id)
);
"""

# users 行统一投影：LEFT JOIN roles 带出 is_admin / role_label（角色被删等异常时兜底）
_USER_SELECT = (
    "u.id, u.username, u.password_hash, u.role, u.user_no, u.department_no, u.created_at,"
    " COALESCE(r.is_admin, 0) AS is_admin, COALESCE(r.label, u.role) AS role_label"
)


# ── DB 层 ───────────────────────────────────────────────


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    fresh = not DB_PATH.exists() or DB_PATH.stat().st_size == 0
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)   # 幂等建表（新库 / 旧库补表两相宜）
    _migrate_legacy_users(conn)   # 旧库：users.role 上的硬编码 CHECK 约束需重建表去除
    _seed_roles(conn)             # 保证默认角色存在（并补全旧库里的自定义角色值）
    if fresh:
        # OR IGNORE：多进程并发首启（如 MCP 子进程与父进程同时播种）时保证幂等，
        # 先到者落库、后到者静默跳过，而不是抛 UNIQUE 冲突。
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role)"
            " VALUES (?, ?, 'admin')",
            ("admin", generate_password_hash("admin")),
        )
        print("[用户管理] 用户库缺失或为空：已重建并播种 admin/admin（内置角色 admin/user）")
    conn.commit()
    return conn


def _migrate_legacy_users(conn) -> None:
    """旧版 auth.db 升级：users.role 带 `CHECK (role IN ('admin','user'))` 硬编码约束，
    自定义角色插不进去。SQLite 无 ALTER DROP CONSTRAINT，按官方惯例重建表（数据原样搬迁）。
    旧用户的 role 值（admin/user）与默认播种角色同名，迁移后自然落位。"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if not row or "CHECK" not in (row["sql"] or ""):
        return  # 新库或已迁移
    conn.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE users_new (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'user' REFERENCES roles(name),
            user_no       TEXT,
            department_no TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
        INSERT INTO users_new (id, username, password_hash, role, user_no,
                               department_no, created_at)
            SELECT id, username, password_hash, role, user_no,
                   department_no, created_at FROM users;
        DROP TABLE users;
        ALTER TABLE users_new RENAME TO users;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_user_no
            ON users(user_no) WHERE user_no IS NOT NULL;
        PRAGMA foreign_keys=ON;
        """
    )


def _seed_roles(conn) -> None:
    """保证默认角色在库；旧库里 users.role 出现过的其他值也补成角色（标签同名）。"""
    for name, label, is_admin in _DEFAULT_ROLES:
        conn.execute(
            "INSERT OR IGNORE INTO roles (name, label, is_admin) VALUES (?, ?, ?)",
            (name, label, is_admin),
        )
    try:
        rows = conn.execute("SELECT DISTINCT role FROM users").fetchall()
    except sqlite3.OperationalError:
        rows = []
    for r in rows:
        conn.execute(
            "INSERT OR IGNORE INTO roles (name, label) VALUES (?, ?)", (r["role"], r["role"])
        )


def init_schema() -> None:
    conn = get_conn()
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def seed_admin() -> bool:
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count > 0:
        conn.close()
        return False
    conn.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, role)"
        " VALUES (?, ?, 'admin')",
        ("admin", generate_password_hash("admin")),
    )
    conn.commit()
    conn.close()
    return True


# ── 只读 helper：用户 ───────────────────────────────────


def get_user_by_name(username: str):
    conn = get_conn()
    row = conn.execute(
        f"SELECT {_USER_SELECT} FROM users u"
        " LEFT JOIN roles r ON r.name = u.role WHERE u.username = ?",
        (username,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def verify_password(user: dict, password: str) -> bool:
    return check_password_hash(user["password_hash"], password)


def list_users() -> list:
    """列出全部用户（含角色标志、个人特授与角色授权计数，供管理页列表展示）。"""
    conn = get_conn()
    rows = conn.execute(
        f"SELECT {_USER_SELECT} FROM users u"
        " LEFT JOIN roles r ON r.name = u.role ORDER BY u.id"
    ).fetchall()
    result = []
    for r in rows:
        u = dict(r)
        u["grants"] = get_grant_keys(u["id"])          # 个人特授
        u["role_grants"] = get_role_grant_keys(u["id"])  # 角色带来的授权
        u["effective_count"] = len(set(u["grants"]) | set(u["role_grants"]))
        result.append(u)
    conn.close()
    return result


def count_admins() -> int:
    """绑定了 is_admin 角色的用户数（末位管理员保护用它）。"""
    conn = get_conn()
    n = conn.execute(
        "SELECT COUNT(*) AS c FROM users u JOIN roles r ON r.name = u.role"
        " WHERE r.is_admin = 1"
    ).fetchone()["c"]
    conn.close()
    return n


# ── 只读 helper：角色 ───────────────────────────────────


def list_roles() -> list:
    """全部角色（含角色授权数与绑定用户数）。is_admin 角色排前。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT r.name, r.label, r.is_admin, r.created_at,"
        " (SELECT COUNT(*) FROM role_grants g WHERE g.role_name = r.name) AS grant_count,"
        " (SELECT COUNT(*) FROM users u WHERE u.role = r.name) AS user_count"
        " FROM roles r ORDER BY r.is_admin DESC, r.name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_role(name: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT name, label, is_admin, created_at FROM roles WHERE name = ?", (name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def role_label(name: str) -> str:
    r = get_role(name)
    return r["label"] if r else name


def count_admin_roles() -> int:
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) AS c FROM roles WHERE is_admin = 1").fetchone()["c"]
    conn.close()
    return n


# ── 只读 helper：服务授权（角色授权 ∪ 个人特授）───────────


def get_grant_keys(user_id: int) -> list:
    """该用户的**个人特授**（不含角色自带授权），形如 ['user.create']。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT app_name, service FROM service_grants WHERE user_id = ?"
        " ORDER BY app_name, service",
        (user_id,),
    ).fetchall()
    conn.close()
    return [f"{r['app_name']}.{r['service']}" for r in rows]


def get_role_grant_keys(user_id: int) -> list:
    """该用户**角色**带来的全部授权键。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT g.app_name, g.service FROM role_grants g"
        " JOIN users u ON u.role = g.role_name WHERE u.id = ?"
        " ORDER BY g.app_name, g.service",
        (user_id,),
    ).fetchall()
    conn.close()
    return [f"{r['app_name']}.{r['service']}" for r in rows]


def role_grant_keys(role_name: str) -> list:
    """某角色自身的授权键列表（角色管理页勾选回显用）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT app_name, service FROM role_grants WHERE role_name = ?"
        " ORDER BY app_name, service",
        (role_name,),
    ).fetchall()
    conn.close()
    return [f"{r['app_name']}.{r['service']}" for r in rows]


def effective_grant_keys(user_id: int) -> list:
    """有效授权 = 角色授权 ∪ 个人特授。"""
    return sorted(set(get_grant_keys(user_id)) | set(get_role_grant_keys(user_id)))


def granted_apps(user_id: int) -> list:
    """该用户有≥1 有效授权的应用名列表（决定可见哪些应用）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT app_name FROM ("
        " SELECT app_name FROM service_grants WHERE user_id = ?"
        " UNION"
        " SELECT g.app_name FROM role_grants g JOIN users u ON u.role = g.role_name"
        " WHERE u.id = ?) ORDER BY app_name",
        (user_id, user_id),
    ).fetchall()
    conn.close()
    return [r["app_name"] for r in rows]


def granted_services(user_id: int, app_name: str) -> list:
    """该用户在某应用内被有效授权的服务名列表。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT service FROM ("
        " SELECT service FROM service_grants WHERE user_id = ? AND app_name = ?"
        " UNION"
        " SELECT g.service FROM role_grants g JOIN users u ON u.role = g.role_name"
        " WHERE u.id = ? AND g.app_name = ?) ORDER BY service",
        (user_id, app_name, user_id, app_name),
    ).fetchall()
    conn.close()
    return [r["service"] for r in rows]


def is_service_granted(user_id: int, app_name: str, service: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 WHERE EXISTS ("
        " SELECT 1 FROM service_grants WHERE user_id = ? AND app_name = ? AND service = ?)"
        " OR EXISTS ("
        " SELECT 1 FROM role_grants g JOIN users u ON u.role = g.role_name"
        " WHERE u.id = ? AND g.app_name = ? AND g.service = ?)",
        (user_id, app_name, service, user_id, app_name, service),
    ).fetchone()
    conn.close()
    return row is not None


def has_app_access(user_id: int, app_name: str) -> bool:
    """该应用下是否有≥1 有效授权服务（决定能否进入该应用）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 WHERE EXISTS ("
        " SELECT 1 FROM service_grants WHERE user_id = ? AND app_name = ?)"
        " OR EXISTS ("
        " SELECT 1 FROM role_grants g JOIN users u ON u.role = g.role_name"
        " WHERE u.id = ? AND g.app_name = ?)",
        (user_id, app_name, user_id, app_name),
    ).fetchone()
    conn.close()
    return row is not None


def migrate_grant_app_names(platform) -> None:
    """把历史授权里的短名 app_name 升级为组限定名 qualname（§1 跨组可重名后必需）。

    短名→qualname 按平台注册表解析；跨组重名时取排序首个（crm<demo，保留既有 crm 授权）并打印告警。
    幂等：已含 '/' 的 qualname 跳过；应用已不存在的授权保留原值（自然失效）。平台加载后调用。"""
    short2qn, ambig = {}, {}
    for qn in platform.app_names():
        short = qn.rsplit("/", 1)[-1]
        if short in short2qn:
            ambig.setdefault(short, [short2qn[short]]).append(qn)
        else:
            short2qn[short] = qn
    conn = get_conn()
    moved = 0
    for table in ("service_grants", "role_grants"):
        rows = conn.execute(
            f"SELECT DISTINCT app_name FROM {table} WHERE app_name NOT LIKE '%/%'").fetchall()
        for r in rows:
            short = r["app_name"]
            qn = short2qn.get(short)
            if not qn:
                continue
            if short in ambig:
                print(f"[鉴权] 授权迁移：短名 {short} 跨组重名 {sorted(ambig[short])}，"
                      f"按 {qn} 升级（如需其它组请重新授权）")
            conn.execute(f"UPDATE {table} SET app_name = ? WHERE app_name = ?", (qn, short))
            moved += 1
    if moved:
        conn.commit()
        print(f"[鉴权] 已将 {moved} 项历史授权的短名升级为组限定名 qualname")
    conn.close()


# ── 只读 helper：前端页面授权（角色级）───────────────────


def get_role_page_grants(role_name: str) -> list:
    """某角色的前端页面授权（page_id 列表，如 ['crm:customer', '_platform:agent']）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT page_id FROM role_page_grants WHERE role_name = ? ORDER BY page_id",
        (role_name,),
    ).fetchall()
    conn.close()
    return [r["page_id"] for r in rows]


def get_user_page_grants(user_id: int) -> list:
    """用户经角色获得的前端页面授权（个人维度不设页面授权）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT g.page_id FROM role_page_grants g"
        " JOIN users u ON u.role = g.role_name WHERE u.id = ? ORDER BY g.page_id",
        (user_id,),
    ).fetchall()
    conn.close()
    return [r["page_id"] for r in rows]


def is_page_granted(user_id: int, page_id: str) -> bool:
    """该用户角色是否获授该前端页面（admin 判定不在此处——调用方按 is_admin 先行全通）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 WHERE EXISTS ("
        " SELECT 1 FROM role_page_grants g JOIN users u ON u.role = g.role_name"
        " WHERE u.id = ? AND g.page_id = ?)",
        (user_id, page_id),
    ).fetchone()
    conn.close()
    return row is not None


# ── 会话感知的可见性（web 渲染过滤用）────────────────────


def session_user():
    """取当前会话用户；无请求上下文 / 未登录返回 None。"""
    try:
        from flask import session as _session

        username = _session.get("username")
    except RuntimeError:
        return None
    if not username:
        return None
    return get_user_by_name(username)


def _is_admin_user(user) -> bool:
    """admin 判定唯一口径：角色带 is_admin 标志；未登录（无鉴权模式）视为全通。"""
    return user is None or bool(user.get("is_admin"))


def visible_app_names(all_names) -> list:
    """当前会话用户可见的应用：admin / 未登录 → 全部；否则取有授权的应用。"""
    u = session_user()
    if _is_admin_user(u):
        return list(all_names)
    ga = set(granted_apps(u["id"]))
    return [n for n in all_names if n in ga]


def visible_service_names(app_name: str, all_service_names) -> list:
    """当前会话用户在某应用可见的服务：admin / 未登录 → 全部；否则取被授权服务。"""
    u = session_user()
    if _is_admin_user(u):
        return list(all_service_names)
    gs = set(granted_services(u["id"], app_name))
    return [s for s in all_service_names if s in gs]


# ── 登录态 → ctx（约定 §4.1）────────────────────────────


def ctx_for_user(u: dict) -> dict:
    """把用户行映射为约定 §4.1 的身份上下文 {userno, departmentno, role}。

    role 取**角色名**（如 admin / user / 自建角色），供应用侧做业务分支（可选）。
    """
    return {
        "userno": u["user_no"] or u["username"],
        "departmentno": u["department_no"] or "",
        "role": u["role"],
    }


def current_caller_ctx():
    """把当前登录态映射为 ctx；无会话 / 未登录返回 None（调用方回落平台默认身份）。"""
    u = session_user()
    return ctx_for_user(u) if u else None


# ── 写操作：用户 ────────────────────────────────────────


def _split_grant_key(key: str):
    """解析授权键 'app.service' → (app, service)；非法返回 None。"""
    key = (key or "").strip()
    if "." not in key:
        return None
    app, service = key.split(".", 1)
    app, service = app.strip(), service.strip()
    if not app or not service:
        return None
    return app, service


def create_user(username, password, role, grants, user_no="", department_no="") -> tuple:
    """创建用户。role 须为已存在的角色；grants：个人特授键列表（'app.service'）。"""
    username = (username or "").strip()
    user_no = (user_no or "").strip() or None
    department_no = (department_no or "").strip() or None
    if not _USERNAME_RE.match(username):
        return False, "用户名非法：不可含空白或路径分隔符，长度 1~32"
    if len(password or "") < MIN_PASSWORD_LEN:
        return False, f"密码至少 {MIN_PASSWORD_LEN} 位"
    if get_role(role) is None:
        return False, f"角色不存在：{role}（请先在「角色管理」创建）"

    conn = get_conn()
    if user_no and conn.execute(
        "SELECT 1 FROM users WHERE user_no = ?", (user_no,)
    ).fetchone():
        conn.close()
        return False, f"用户编号已存在：{user_no}"
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, user_no, department_no)"
            " VALUES (?, ?, ?, ?, ?)",
            (username, generate_password_hash(password), role, user_no, department_no),
        )
        user_id = cur.lastrowid
        _write_grants(conn, user_id, grants)
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False, f"用户名已存在：{username}"
    conn.close()
    return True, f"已创建用户 {username}（{role_label(role)}）"


def _write_grants(conn, user_id: int, grants) -> None:
    """写入个人特授（去重保序）；grants 为 'app.service' 键列表。"""
    seen = set()
    for key in grants or []:
        parsed = _split_grant_key(key)
        if not parsed or parsed in seen:
            continue
        seen.add(parsed)
        conn.execute(
            "INSERT OR IGNORE INTO service_grants (user_id, app_name, service) VALUES (?, ?, ?)",
            (user_id, parsed[0], parsed[1]),
        )


def _write_role_grants(conn, role_name: str, grants) -> None:
    """写入角色授权（去重保序）；grants 为 'app.service' 键列表。"""
    seen = set()
    for key in grants or []:
        parsed = _split_grant_key(key)
        if not parsed or parsed in seen:
            continue
        seen.add(parsed)
        conn.execute(
            "INSERT OR IGNORE INTO role_grants (role_name, app_name, service) VALUES (?, ?, ?)",
            (role_name, parsed[0], parsed[1]),
        )


def delete_user(username: str) -> tuple:
    user = get_user_by_name(username)
    if not user:
        return False, f"用户不存在：{username}"
    if user["is_admin"] and count_admins() <= 1:
        return False, "不能删除最后一个管理员"
    conn = get_conn()
    conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))  # 级联清除个人特授
    conn.commit()
    conn.close()
    return True, f"已删除用户 {username}"


def reset_password(username: str, new_password: str) -> tuple:
    user = get_user_by_name(username)
    if not user:
        return False, f"用户不存在：{username}"
    if len(new_password or "") < MIN_PASSWORD_LEN:
        return False, f"密码至少 {MIN_PASSWORD_LEN} 位"
    conn = get_conn()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user["id"]),
    )
    conn.commit()
    conn.close()
    return True, f"已重置 {username} 的密码"


def set_role(username: str, new_role: str) -> tuple:
    user = get_user_by_name(username)
    if not user:
        return False, f"用户不存在：{username}"
    target = get_role(new_role)
    if target is None:
        return False, f"角色不存在：{new_role}"
    # 末位管理员保护：从 is_admin 角色换到非 is_admin 角色，且管理员只剩这一个
    if user["is_admin"] and not target["is_admin"] and count_admins() <= 1:
        return False, "不能降权最后一个管理员"
    conn = get_conn()
    conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user["id"]))
    conn.commit()
    conn.close()
    return True, f"已将 {username} 设为{target['label']}"


def set_service_grants(username: str, grants: list) -> tuple:
    """整体替换用户的**个人特授**（grants 为 'app.service' 键列表；不影响角色授权）。"""
    user = get_user_by_name(username)
    if not user:
        return False, f"用户不存在：{username}"
    conn = get_conn()
    conn.execute("DELETE FROM service_grants WHERE user_id = ?", (user["id"],))
    _write_grants(conn, user["id"], grants)
    conn.commit()
    conn.close()
    return True, f"已更新 {username} 的个人特授"


# ── 写操作：角色 ────────────────────────────────────────


def create_role(name, label, is_admin=False, grants=None) -> tuple:
    name = (name or "").strip()
    label = (label or "").strip() or name
    if not _ROLE_NAME_RE.match(name):
        return False, "角色名须以小写字母开头，仅含小写字母/数字/下划线，长度 ≤32"
    if get_role(name) is not None:
        return False, f"角色已存在：{name}"
    conn = get_conn()
    conn.execute(
        "INSERT INTO roles (name, label, is_admin) VALUES (?, ?, ?)",
        (name, label, 1 if is_admin else 0),
    )
    _write_role_grants(conn, name, grants)
    conn.commit()
    conn.close()
    return True, f"已创建角色 {name}（{label}）"


def set_role_grants(name: str, grants: list) -> tuple:
    """整体替换角色授权（grants 为 'app.service' 键列表）。"""
    if get_role(name) is None:
        return False, f"角色不存在：{name}"
    conn = get_conn()
    conn.execute("DELETE FROM role_grants WHERE role_name = ?", (name,))
    _write_role_grants(conn, name, grants)
    conn.commit()
    conn.close()
    return True, f"已更新角色 {name} 的授权"


def set_role_page_grants(name: str, page_ids: list) -> tuple:
    """整体替换角色的**前端页面授权**（page_ids 形如 ['crm:customer']；非法 id 静默丢弃）。"""
    if get_role(name) is None:
        return False, f"角色不存在：{name}"
    conn = get_conn()
    conn.execute("DELETE FROM role_page_grants WHERE role_name = ?", (name,))
    seen = set()
    for pid in page_ids or []:
        pid = (pid or "").strip()
        if not _PAGE_ID_RE.match(pid) or pid in seen:
            continue
        seen.add(pid)
        conn.execute(
            "INSERT OR IGNORE INTO role_page_grants (role_name, page_id) VALUES (?, ?)",
            (name, pid),
        )
    conn.commit()
    conn.close()
    return True, f"已更新角色 {name} 的前端页面授权（{len(seen)} 页）"


def set_role_admin_flag(name: str, is_admin: bool) -> tuple:
    """设置/取消角色的 is_admin（全通）标志；须至少保留一个 is_admin 角色。"""
    role = get_role(name)
    if role is None:
        return False, f"角色不存在：{name}"
    if role["is_admin"] and not is_admin and count_admin_roles() <= 1:
        return False, "至少保留一个管理员角色"
    conn = get_conn()
    conn.execute("UPDATE roles SET is_admin = ? WHERE name = ?", (1 if is_admin else 0, name))
    conn.commit()
    conn.close()
    return True, f"已将角色 {name} 的管理员标志设为 {is_admin}"


def delete_role(name: str) -> tuple:
    role = get_role(name)
    if role is None:
        return False, f"角色不存在：{name}"
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role = ?", (name,)).fetchone()["c"]
    if n > 0:
        conn.close()
        return False, f"角色 {name} 下还有 {n} 个用户，请先为他们更换角色"
    if role["is_admin"] and count_admin_roles() <= 1:
        conn.close()
        return False, "至少保留一个管理员角色"
    conn.execute("DELETE FROM roles WHERE name = ?", (name,))  # 级联清除角色授权
    conn.commit()
    conn.close()
    return True, f"已删除角色 {name}"


# ── 路由（Blueprint，由鉴权闸门的 /auth/ 规则保护，仅 admin）──


def _apps_services_map() -> dict:
    """{应用名: [服务名...]}，供授权勾选。惰性导入避免 users→web 顶层耦合。"""
    from fde_platform.web import platform

    return {name: [s["name"] for s in platform.services(name)] for name in platform.app_names()}


bp = Blueprint("users_mgmt", __name__, url_prefix="/auth")


@bp.route("/users")
def users_page():
    from fde_platform import view_registry  # 惰性导入：扫描 view/ 的动态页面注册表

    roles = list_roles()
    for r in roles:
        r["grants"] = role_grant_keys(r["name"])      # 服务授权勾选回显
        r["pages"] = get_role_page_grants(r["name"])  # 页面授权勾选回显
    return render_template(
        "users.html",
        users_list=list_users(),
        roles=roles,
        apps_services=_apps_services_map(),
        view_registry=view_registry.registry(),
        me=session.get("username", ""),
    )


@bp.route("/users", methods=["POST"])
def users_create():
    ok, msg = create_user(
        request.form.get("username", ""),
        request.form.get("password", ""),
        request.form.get("role", "user"),
        request.form.getlist("grants"),
        request.form.get("user_no", ""),
        request.form.get("department_no", ""),
    )
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("users_mgmt.users_page"))


@bp.route("/users/<username>/reset", methods=["POST"])
def users_reset(username):
    ok, msg = reset_password(username, request.form.get("password", ""))
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("users_mgmt.users_page"))


@bp.route("/users/<username>/role", methods=["POST"])
def users_role(username):
    ok, msg = set_role(username, request.form.get("role", ""))
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("users_mgmt.users_page"))


@bp.route("/users/<username>/grants", methods=["POST"])
def users_grants(username):
    ok, msg = set_service_grants(username, request.form.getlist("grants"))
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("users_mgmt.users_page"))


@bp.route("/users/<username>/delete", methods=["POST"])
def users_delete(username):
    ok, msg = delete_user(username)
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("users_mgmt.users_page"))


# ── 角色管理路由 ────────────────────────────────────────


@bp.route("/roles", methods=["POST"])
def roles_create():
    ok, msg = create_role(
        request.form.get("name", ""),
        request.form.get("label", ""),
        request.form.get("is_admin") == "on",
        request.form.getlist("grants"),
    )
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("users_mgmt.users_page"))


@bp.route("/roles/<name>/grants", methods=["POST"])
def roles_grants(name):
    ok, msg = set_role_grants(name, request.form.getlist("grants"))
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("users_mgmt.users_page"))


@bp.route("/roles/<name>/pages", methods=["POST"])
def roles_pages(name):
    ok, msg = set_role_page_grants(name, request.form.getlist("pages"))
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("users_mgmt.users_page"))


@bp.route("/roles/<name>/admin", methods=["POST"])
def roles_admin(name):
    ok, msg = set_role_admin_flag(name, request.form.get("is_admin") == "on")
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("users_mgmt.users_page"))


@bp.route("/roles/<name>/delete", methods=["POST"])
def roles_delete(name):
    ok, msg = delete_role(name)
    flash(msg, "ok" if ok else "error")
    return redirect(url_for("users_mgmt.users_page"))


# ── CLI ─────────────────────────────────────────────────


def _cli():
    parser = argparse.ArgumentParser(description="FDE v2 平台用户/角色管理 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="建表并播种 admin/admin")
    sub.add_parser("list", help="列出用户与授权")
    sub.add_parser("roles", help="列出角色")

    p = sub.add_parser("add", help="创建用户")
    p.add_argument("username")
    p.add_argument("password")
    p.add_argument("--role", default="user", help="角色名（须已存在，默认 user）")
    p.add_argument("--grants", nargs="*", default=[], help="个人特授，形如 user.create user.list")
    p.add_argument("--user-no", default="")
    p.add_argument("--department-no", default="")

    p = sub.add_parser("rm", help="删除用户"); p.add_argument("username")
    p = sub.add_parser("reset", help="重置密码"); p.add_argument("username"); p.add_argument("password")
    p = sub.add_parser("role", help="更换角色"); p.add_argument("username"); p.add_argument("new_role")
    p = sub.add_parser("grant", help="整体替换个人特授"); p.add_argument("username")
    p.add_argument("--grants", nargs="*", default=[], help="形如 user.create department.list")

    p = sub.add_parser("role-add", help="创建角色"); p.add_argument("name")
    p.add_argument("--label", default="", help="显示名（默认同名）")
    p.add_argument("--admin", action="store_true", help="is_admin：该角色绕过授权检查（全通）")
    p.add_argument("--grants", nargs="*", default=[], help="角色授权，形如 user.create")
    p = sub.add_parser("role-rm", help="删除角色"); p.add_argument("name")
    p = sub.add_parser("role-grant", help="整体替换角色授权"); p.add_argument("name")
    p.add_argument("--grants", nargs="*", default=[], help="形如 user.create department.list")

    args = parser.parse_args()
    init_schema()

    if args.cmd == "init":
        print("admin/admin 已播种（首次）" if seed_admin() else "用户表非空，未播种")
    elif args.cmd == "list":
        for u in list_users():
            grants = "全部（管理员角色）" if u["is_admin"] else (", ".join(u["grants"]) or "—")
            print(
                f"{u['username']}\t{u['role']}（{u['role_label']}）\t编号:{u['user_no'] or '—'}"
                f"\t部门:{u['department_no'] or '—'}\t{u['created_at']}\t个人特授: {grants}"
            )
    elif args.cmd == "roles":
        for r in list_roles():
            print(
                f"{r['name']}\t{r['label']}\t{'管理员' if r['is_admin'] else '普通'}"
                f"\t角色授权 {r['grant_count']} 项\t绑定用户 {r['user_count']} 人"
            )
    elif args.cmd == "add":
        print(create_user(args.username, args.password, args.role,
                          args.grants, args.user_no, args.department_no)[1])
    elif args.cmd == "rm":
        print(delete_user(args.username)[1])
    elif args.cmd == "reset":
        print(reset_password(args.username, args.password)[1])
    elif args.cmd == "role":
        print(set_role(args.username, args.new_role)[1])
    elif args.cmd == "grant":
        print(set_service_grants(args.username, args.grants)[1])
    elif args.cmd == "role-add":
        print(create_role(args.name, args.label, args.admin, args.grants)[1])
    elif args.cmd == "role-rm":
        print(delete_role(args.name)[1])
    elif args.cmd == "role-grant":
        print(set_role_grants(args.name, args.grants)[1])


if __name__ == "__main__":
    _cli()
