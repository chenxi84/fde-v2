"""FDE v2 平台运行时 —— 加载器 + 跨应用网关（CONVENTION §10 的平台职责落地）。

职责：
1. **发现与加载**：扫描 `app/` 下的应用文件夹（支持**应用组**：`app/<组>/<名>/` 分组放置
   与 `app/<名>/` 直接放置，见 `discover_apps`），按**唯一模块名** `fde_app_<名>` 加载
   主文件 `<名>.py`（避免 v1 的 `sys.modules` 撞名竞争），**加载一次并缓存**；
2. **加载时建表**：读应用**必选**的 `schema.sql`，经 ddl 引擎解析建表（缺则加载失败，§6）；
3. **每次调用造新实例**：注入权威 `ctx` / 全新 `db` 连接 / 绑定 ctx 的网关 `fde`；
   方法正常返回 → `commit`，抛异常 → `rollback`（事务归平台，§4.2）。每调用独立连接，线程安全；
4. **跨应用路由**：`self.fde.call` 按名运行期解析，`ctx` 自动透传且**不可伪造**（§4.1/§5）。
"""
import importlib.util
import sqlite3
import time
from fde_platform import db, ddl
import sys
from dataclasses import dataclass
from pathlib import Path

from fde import FdeError
from fde_platform import builtin_tools, introspect

ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = ROOT / "app"

# 无鉴权时期的默认平台身份（§10.3 的认证/鉴权留待下期）
DEFAULT_CTX = {"userno": "demo", "departmentno": "", "role": "admin"}

_BUSY_TIMEOUT_MS = 5000


def _snake_to_pascal(name: str) -> str:
    """user → User；sales_order → SalesOrder。"""
    return "".join(part[:1].upper() + part[1:] for part in name.split("_") if part)


def qualname(group, name: str) -> str:
    """应用的组限定名：组内应用 → '组/名'；未分组应用 → '名'。注册表与跨应用路由的键。"""
    return f"{group}/{name}" if group else name


def split_qualname(qn: str):
    """'crm/customer' → ('crm','customer')；'todo'（未分组）→ (None,'todo')。"""
    if "/" in qn:
        g, n = qn.split("/", 1)
        return g, n
    return None, qn


def tool_prefix(qn: str) -> str:
    """MCP/内置工具名的应用前缀（工具名只允许 [A-Za-z0-9_-]，'/' 换 '__'）：
    'crm/customer' → 'crm__customer'；'todo' → 'todo'。"""
    return qn.replace("/", "__")


def _open_db(db_path: Path) -> sqlite3.Connection:
    """打开应用同名库连接，设平台默认（WAL / busy_timeout / 外键 / 行工厂）。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _find_aggregate_class(module, module_name: str, app_name: str):
    """在模块里找聚合根类：优先与文件夹同名的 PascalCase，其次唯一公共类。"""
    expected = _snake_to_pascal(app_name)
    candidates = {
        n: obj
        for n, obj in vars(module).items()
        if isinstance(obj, type) and obj.__module__ == module_name and not n.startswith("_")
    }
    if expected in candidates:
        return candidates[expected]
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    if not candidates:
        raise FdeError(f"应用 {app_name} 未定义聚合根类（期望 class {expected}）")
    raise FdeError(
        f"应用 {app_name} 存在多个公共类 {sorted(candidates)}，无法判定聚合根；"
        f"请将主类命名为 {expected}"
    )


def discover_apps(apps_dir: Path) -> list[dict]:
    """扫描应用目录，返回全部应用的落位（纯文件系统判定，不加载模块）。

    两种放置方式，可混用（CONVENTION §1）：
    - 直接放置：`<apps_dir>/<名>/<名>.py`           → 不分组（group=None）
    - 分组放置：`<apps_dir>/<组>/<名>/<名>.py`       → group="<组>"

    一级目录含同名主文件 `<名>.py` 即视为**应用目录**；否则视为**组目录**，
    向下识别一层含主文件的应用目录（分组只支持一级）。不含任何应用的目录忽略。
    **应用名须组内唯一**；跨组允许重名（如 crm/customer 与 demo/customer 可并存），
    跨应用调用按调用方所在组解析（§5）。注册表键为组限定名 qualname（'组/名' 或 '名'）。

    Returns: [{"name", "qualname", "folder", "group"}]，按 qualname 排序。
    """
    apps_dir = Path(apps_dir)
    found: dict[str, dict] = {}

    def _add(name: str, folder: Path, group):
        qn = qualname(group, name)
        if qn in found:
            raise FdeError(
                f"应用冲突：{qn} 同时存在于 {found[qn]['folder']} 与 {folder}"
                f"（同一组内应用名不可重复）"
            )
        found[qn] = {"name": name, "qualname": qn, "folder": folder, "group": group}

    if not apps_dir.exists():
        return []
    for entry in sorted(apps_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "__")):
            continue
        if (entry / f"{entry.name}.py").is_file():
            _add(entry.name, entry, None)  # 直接放置的应用
            continue
        # 组目录：组名 = 目录名；只认含主文件的应用子目录
        for folder in sorted(entry.iterdir()):
            if (
                folder.is_dir()
                and not folder.name.startswith((".", "__"))
                and (folder / f"{folder.name}.py").is_file()
            ):
                _add(folder.name, folder, entry.name)
    return sorted(found.values(), key=lambda a: a["qualname"])


@dataclass
class AppHandle:
    """一个已加载应用的句柄：类只加载一次并缓存于此（§10.1）。"""

    name: str
    folder: Path
    module: object
    cls: type
    db_path: Path
    group: str | None = None  # 所属应用组（一级目录名）；None=未分组
    qualname: str = ""        # 组限定名（'组/名' 或 '名'）；注册表与路由的键


class BoundFde:
    """应用拿到的 `self.fde` —— **绑定当前 ctx 与调用方所在组** 的网关。

    `call()` 签名里**没有 ctx 参数**：调用方无从伪造或覆盖身份，
    只能把当前 `ctx` 原样透传给被调应用（§4.1「不可篡改/不可伪造」）。
    目标应用短名先按**调用方所在组**解析（§5 组内优先），组内没有再按全局唯一回退。
    """

    def __init__(self, platform: "FdePlatform", ctx: dict, caller_group: str | None = None):
        self._platform = platform
        self._ctx = ctx
        self._caller_group = caller_group

    def call(self, app: str, service: str, **params):
        """跨应用调用：按名、运行期绑定（CONVENTION §4.3 / §5）。"""
        return self._platform.call(app, service, ctx=self._ctx,
                                   caller_group=self._caller_group, **params)


class FdePlatform:
    """平台核心：应用注册表 + 跨应用网关。"""

    def __init__(self, apps_dir: Path = APPS_DIR, default_ctx: dict = None):
        self.apps_dir = Path(apps_dir)
        self.default_ctx = dict(default_ctx or DEFAULT_CTX)
        self._apps: dict[str, AppHandle] = {}
        # 应用文件里的 `from fde import FdeError` 需要仓库根在 sys.path
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))

    # ── 发现与加载 ──────────────────────────────────────────
    def load_all(self) -> None:
        """扫描并加载全部应用（分组/不分组两种放置，见 discover_apps）。

        任一应用加载失败即抛出（启动期暴露问题）。
        """
        for info in discover_apps(self.apps_dir):
            self._load(info["name"], info["folder"], info["group"])

    def _load(self, name: str, folder: Path = None, group: str | None = None) -> AppHandle:
        qn = qualname(group, name)
        if qn in self._apps:
            return self._apps[qn]
        folder = Path(folder) if folder is not None else self.apps_dir / name
        main_file = folder / f"{name}.py"
        if not main_file.exists():
            raise FdeError(f"应用 {qn} 缺少主文件 {name}/{name}.py")

        module_name = f"fde_app_{qn.replace('/', '__')}"  # 唯一模块名（含组），避免撞名（§10.1）
        spec = importlib.util.spec_from_file_location(module_name, str(main_file))
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            sys.modules.pop(module_name, None)
            raise FdeError(f"加载应用 {qn} 失败：{type(e).__name__}: {e}")

        cls = _find_aggregate_class(module, module_name, name)

        # 必选的 schema.sql：缺失即加载失败
        schema_path = folder / "schema.sql"
        if not schema_path.exists():
            raise FdeError(f"应用 {qn} 缺少必选的 schema.sql")

        db_path = folder / f"{name}.db"
        handle = AppHandle(
            name=name, folder=folder, module=module, cls=cls, db_path=db_path,
            group=group, qualname=qn,
        )

        # 平台自动创建约定资源目录（import-file / export-file，见 builtin_tools）
        builtin_tools.ensure_resource_dirs(folder)

        # 加载时建表：读 schema.sql → ddl 引擎解析建表（SQLite/PG 双兼容）。
        # 仅加载时执行一次，不计入单次服务调用开销。
        schema_sql = schema_path.read_text(encoding="utf-8")
        dialect = "postgres" if db.using_postgresql() else "sqlite"
        conn = db.get_connection(qn, db_path)
        conn._fde_ctx = dict(self.default_ctx)
        try:
            ddl.execute_schema(conn, schema_sql, dialect)
            conn.commit()
        finally:
            conn.close()

        self._apps[qn] = handle
        return handle

    # ── 查询 ────────────────────────────────────────────────
    def app_names(self) -> list[str]:
        """全部应用的组限定名（qualname：'组/名'，未分组为 '名'），排序。"""
        return sorted(self._apps)

    def short_names(self) -> list[str]:
        """全部应用的短名（跨组可能重复），排序去重。"""
        return sorted({h.name for h in self._apps.values()})

    def group_of(self, name: str) -> str | None:
        """应用所属组（一级目录名）；直接放在 app/ 下的返回 None。"""
        return self.handle(name).group

    def groups(self) -> list[str]:
        """全部组名（排序；不含未分组桶）。"""
        return sorted({h.group for h in self._apps.values() if h.group})

    def apps_in_group(self, group: str | None) -> list[str]:
        """某组下的应用 qualname（排序）；group=None → 未分组的应用。"""
        return sorted(n for n, h in self._apps.items() if h.group == group)

    def _resolve_app(self, app: str, caller_group: str | None = None) -> AppHandle:
        """按名解析应用句柄（§5 组内优先）：
        ① 完整 qualname 或未分组短名精确命中；② 调用方同组 `组/名`；
        ③ 全局唯一短名回退；④ 多组重名且非本组 → 报错要求用 组/名 明确指定。"""
        h = self._apps.get(app)
        if h is not None:
            return h
        if caller_group is not None:
            h = self._apps.get(qualname(caller_group, app))
            if h is not None:
                return h
        matches = [q for q in self._apps if q.rsplit("/", 1)[-1] == app]
        if len(matches) == 1:
            return self._apps[matches[0]]
        if len(matches) > 1:
            raise FdeError(
                f"应用名 {app} 在多个组中存在 {sorted(matches)}，请用 组/应用 明确指定")
        raise FdeError(f"应用不存在：{app}")

    def handle(self, name: str) -> AppHandle:
        """取应用句柄：接受 qualname（精确）或短名（按 §5 解析）。"""
        h = self._apps.get(name)
        return h if h is not None else self._resolve_app(name)

    def services(self, name: str) -> list[dict]:
        """某应用对外暴露的服务清单（含入参契约）。"""
        return introspect.list_services(self.handle(name).cls)

    def readme(self, name: str) -> str:
        """读取应用文件夹内的 README.md（CONVENTION §11）；缺失返回空串。"""
        try:
            h = self.handle(name)
        except FdeError:
            return ""
        try:
            path = h.folder / "README.md"
            return path.read_text(encoding="utf-8") if path.exists() else ""
        except Exception:
            return ""

    def all_mcp_tools(self) -> list[dict]:
        """全部应用的公共服务 → MCP/LLM tool 定义。
        工具名按组限定（'组__名__服务'）保证跨组唯一；_meta.app 为 qualname（路由用）。"""
        tools = []
        for qn in self.app_names():
            handle = self._apps[qn]
            prefix = tool_prefix(qn)
            for svc in self.services(qn):
                tools.append(introspect.to_mcp_tool(
                    prefix, svc, qualname=qn, group=handle.group, app_name=handle.name))
            tools.extend(builtin_tools.builtin_tool_defs(
                prefix, qualname=qn, group=handle.group, app_name=handle.name))
        return tools

    # ── 调用（顶层入口 + 跨应用路由共用）──────────────────────
    def call(self, app: str, service: str, ctx: dict = None,
             caller_group: str | None = None, **params):
        """调用 `app` 的 `service`。app 可为 qualname（精确）或短名（按 §5 组内优先解析）。

        ctx=None 时用平台默认身份（顶层手工/Agent/MCP 调用）；
        跨应用调用经 BoundFde 携带调用方 ctx 与所在组进入，自动透传（§4.1）并按组解析目标。
        """
        handle = self._resolve_app(app, caller_group)  # 不存在/歧义 → FdeError（§5 运行期校验）
        if service.startswith("_"):
            raise FdeError(f"应用 {handle.qualname} 无此服务：{service}（内部方法不对外，§3）")
        method = getattr(handle.cls, service, None)
        if not callable(method):
            raise FdeError(f"应用 {handle.qualname} 无此服务：{service}")

        ctx = dict(ctx or self.default_ctx)
        conn = db.get_connection(handle.qualname, handle.db_path)
        conn._fde_ctx = ctx
        inst = handle.cls()
        inst.ctx = ctx
        inst.db = conn
        inst.fde = BoundFde(self, ctx, handle.group)
        try:
            # SQLite 自愈：库文件被外部删除/清空时用 schema.sql 重建
            if not db.using_postgresql():
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1"
                ).fetchone() is None:
                    schema_sql = (handle.folder / "schema.sql").read_text(encoding="utf-8")
                    ddl.execute_schema(conn, schema_sql, "sqlite")
            t0 = time.time()
            result = method(inst, **params)
            dur_ms = int((time.time() - t0) * 1000)
            conn.commit()
            _log_integration_call(handle, service, caller_group, params, "success", dur_ms)
            return result
        except FdeError as e:
            dur_ms = int((time.time() - t0) * 1000) if 't0' in dir() else 0
            conn.rollback()
            _log_integration_call(handle, service, caller_group, params, "error", dur_ms, str(e))
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _log_integration_call(handle, service, caller_group, params, status, dur_ms, error=""):
    """记录集成调用日志（外部适配器 + 跨组调用 + Web/MCP 顶层调用）。"""
    try:
        from fde_platform import integration
        target_group = handle.group or "-"
        req = str({k: str(v)[:50] for k, v in (params or {}).items()})[:200]
        # 判定类型：外部适配器 / 网关应用 → external；跨组 → cross_group
        is_gw, gw_target = integration._is_gateway_app(handle.cls, handle.qualname)
        if integration._is_external_adapter(service):
            target_sys = service[1:].split("_")[0].upper()
            integration.log_call(handle.qualname, service, target_sys, req, status, dur_ms,
                                 error_msg=error[:200])
        elif is_gw and not service.startswith("_"):
            integration.log_call(handle.qualname, service, gw_target, req, status, dur_ms,
                                 error_msg=error[:200])
        elif caller_group and target_group and caller_group != target_group:
            target = f"{target_group}/{service}"
            integration.log_call(handle.qualname, service, target, req, status, dur_ms,
                                 error_msg=error[:200])
    except Exception:
        pass  # 日志记录失败不影响主流程
