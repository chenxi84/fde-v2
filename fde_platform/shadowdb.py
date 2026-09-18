"""影子库隔离 —— 把业务库**复制**到临时目录，测试跑在副本上，**真库零字节接触**。

## 与 `dbguard.isolate_dbs()` 的关系：**不是新旧，是两条路**

| | `dbguard`（移库） | 本模块（复制） |
|---|---|---|
| 真库文件 | **被移走**（跑完还回） | **原地不动** |
| 测试起点 | 空库（空位给测试） | 副本（真库的拷贝） |
| 需要停服 | **必须**（文件被占用就移不动） | **不需要**（只读复制，无锁冲突） |
| 中途被强杀 | 真库离开原位（靠下次运行救回） | **真库不受任何影响** |
| 覆盖不了 | 需要真实数据的检查（数据被移走了） | —— |

**能覆盖全部四种场景**，所以它适合做统一底座：

| 场景 | 用法 | 起点 |
|---|---|---|
| 链测试 / 前端 e2e | `shadow_dbs()`（`config=True`）+ 在副本上清表 | 空表 |
| 对账体检（破坏性） | `shadow_dbs()`（不清表） | 真实数据 |
| eval（要真 LLM 配置） | `shadow_dbs()`（不清表、`config=False`） | 真实数据 + 真 `config/` |

> ⚠ `config=True` **只隔离 `config/auth.db`**（也是唯一认 `FDE_CONFIG_ROOT` 的库）；
> `scheduler` / `integration` / `llm` / `flow` / `alerts` / `logs` 仍读写真 `config/` ——
> 别把本模块当成整个 `config/` 的隔离层（详见 `platform_dbs()` 的说明与台账 §7）。

## 两条生效路径（**为什么两条都要**）

- **`env=True`**：设 `FDE_DB_ROOT`，`fde_platform/runtime.py` 据此把业务库解析到副本。
  **子进程能继承环境变量** —— 这是唯一能穿透进程边界的办法：
  `verify_view_*.py` 是 `subprocess.Popen([python, main.py])` 起平台的，
  agent 编排跑在 :4100 另一个进程，**进程内的猴子补丁过不去**。
- **`inprocess=True`**：本进程内把 `db.get_connection` 重定向到副本。
  给同进程直接 `FdePlatform()` 的测试用（链测试、对账体检）。

两者默认都开，互补不冲突。

## 目录布局：**扁平**（`<影子目录>/<库文件名>`）

副本一律平铺在影子目录根下（`demand.db` / `auth.db` …），**与运行期的解析规则逐字一致**：

| 谁去解析 | 规则 |
|---|---|
| `runtime.py`（业务库） | `Path(FDE_DB_ROOT) / f"{name}.db"` |
| `users.py`（平台库） | `Path(FDE_CONFIG_ROOT) / "auth.db"` |
| `verify_psc_oracles.py`（自带 `shadow_sandbox`） | `shutil.copy2(src, shadow / src.name)` |

⚠ **2026-09-18 之前不是这样**：本模块按**仓库树形**落盘（`<影子>/app/<组>/<应用>/<应用>.db`），
而上面三处都按扁平找 ⇒ 找不到副本，SQLite 就在扁平位置**新建空库**顶上。
真库确实零接触（安全承诺成立），但**"跑在副本上"是假的**：想要"读真数据零风险"的用法会**静默拿到空库**。
现在布局与解析规则对齐，且 `shadow_dbs()` **入口自带自检**（`missing_shadows`），不一致就当场抛错；
`scripts/verify_shadow_isolation.py` 独立复核这条（已接进 `run_gates.py` 的 static 层）。

> **前提**：应用名与平台库名**全局唯一**（同一扁平目录里不能重名）。`app/*/*/` 与 `config/*.db` 已核无重名。

## 边界

- **业务库全隔离；`config/` 只隔离 `auth.db`**（`config=True` 时）。理由见 `runtime.py` 里同类注释 ——
  eval 需要**真的 LLM 配置**，把 config/ 也重定向会让它因"没配模型"跑不起来；
  而其余平台模块（scheduler / llm / flow / alerts / logs…）压根不认 `FDE_CONFIG_ROOT`，
  复制副本没有收益、只有代价（整个 `config/` 103 MB，其中 agent 会话库 102.6 MB，
  业务库才 1.4 MB ⇒ 每个 view 脚本白拷 ~103 MB、一轮 2.3 GB，被强杀时还留在 temp 里）。
  > ⚠ **2026-09-18 走过一段弯路**：`config=True` 一度**只复制 `auth.db`** —— 因为当时
  > `FDE_CONFIG_ROOT` 只有 `users.py` 认，其余模块（scheduler / integration / llm / flow / alerts /
  > logging_config / knowledge_graph）全硬编码真 `config/`，复制副本**没有隔离收益**，
  > 而代价是每个 view 脚本白拷 103 MB（其中 Agent 会话库 102.6 MB）。
  > **当天下晚些时候把这些模块都改成认那个变量了**（统一走 `fde_platform/config_paths.py`，
  > **调用时解析**），于是副本集合恢复为「除 `agent_service.db` 外的 config 库」（合计 0.6 MB），
  > 隔离才名副其实。详见 `design-plus/验证门禁.md` §五之三 与 `app/psc/BUGS_psc_2026-09-15.md` §7。
- 副本是**快照**：测试期间的并发行为与真库不完全等价（本仓库的测试都是单进程串行，不涉及）。

## 用法

    from fde_platform.shadowdb import shadow_dbs, shadow_clear

    with shadow_dbs() as shadow:          # 真库零接触
        shadow_clear("psc")               # 按需：在**副本上**清表（链测试要空表起步）
        pf = FdePlatform(); pf.load_all()
        ...

    # 起子进程的测试（view e2e）：
    with shadow_dbs(env=True, inprocess=False) as shadow:
        subprocess.Popen([sys.executable, "main.py"], env={**os.environ, ...})
        #                       ↑ 子进程自动继承 FDE_DB_ROOT，跑在副本上
"""
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def business_dbs() -> list:
    """业务库文件：`app/**/*.db*`（含 WAL/SHM）。"""
    return [p for p in (ROOT / "app").glob("**/*.db*") if p.is_file()]


def platform_dbs() -> list:
    """**被隔离的平台库**：只有 `config/auth.db`（含 wal/shm）。

    ⚠ **默认不影子化** —— 与 `config=True` 的取舍：
      · `config=True` 给 **view e2e**：它要**播种 admin**（写 `config/auth.db`），
        不影子化就会污染真库；
      · `config=False` 给 **eval**：它需要**真的 LLM 配置**（`config/llm.db`），
        影子化会让它因"没配模型"跑不起来。

    **2026-09-18 两次调整**（第二次是当天更晚，配合「各模块都认 `FDE_CONFIG_ROOT`」的改动）：

    1. **先收窄为只复制 `auth.db`**：当时只有 `users.py` 认那个变量，复制别的 config 库**没有隔离收益**；
       而 `config/` 合计 103.2 MB、其中 `agent_service.db` 一个就 **102.6 MB**（Agent 会话库，
       view e2e 完全不碰），业务库总共才 1.4 MB ⇒ 每个 view 脚本白拷 ~103 MB、一轮 2.3 GB。
    2. **现在恢复复制「除大会话库以外的 config 库」**：因为 `scheduler` / `integration` / `llm` /
       `flow` / `alerts` / `logging_config` / `knowledge_graph` 都已改为走
       `config_paths.config_path()` **认这个变量** —— 至此「测试起的平台真发定时任务、
       run 记录落真 scheduler.db」这条才是真的堵上了（见台账 §7）。
       继续排除 `agent_service.db`：它是 **Agent 对话记录**（102.6 MB），由 `agent_service`
       那个独立进程管理、测试不需要它的副本。

    ⚠ **排除项也要说清楚**：不复制 ⇒ 若某模块在测试里真去读它，读到的是**真库**（不是副本）。
    `agent_service.db` 目前只有 :4100 那个 agent_service 进程用，view/chain 测试不碰它。
    """
    skip = ("agent_service.db",)
    return [p for p in (ROOT / "config").glob("*.db*")
            if p.is_file() and not p.name.startswith(skip)]


def _copy_all(shadow: Path, config: bool = False) -> int:
    """把要隔离的库**扁平**复制进影子目录：`<影子>/<库文件名>`（如 `<影子>/demand.db`）。

    ⚠ **布局必须与运行期的解析规则逐字一致**（2026-09-18 修正）：
      · `runtime.py`：`db_path = Path(FDE_DB_ROOT) / f"{name}.db"`
      · `users.py`：`DB_PATH = Path(FDE_CONFIG_ROOT) / "auth.db"`
      · `verify_psc_oracles.py` 自带的 `shadow_sandbox()`：也是扁平的（`shutil.copy2(src, shadow / src.name)`）

    此前本函数按**仓库树形**落盘（`<影子>/app/<组>/<应用>/<应用>.db`）⇒ 运行期按扁平**找不到副本**，
    SQLite 便在 `<影子>/<应用>.db` **新建一个空库**顶上。后果很隐蔽：
    真库确实零字节接触（安全承诺成立），但**"跑在副本上"是假的** ——
    凡是"想读真数据、又不想有任何风险"的用法（对账体检就是）会**静默拿到空库**，
    不报错、不变红，只会得出"数据是空的"这种结论。故改为扁平。

    **前提**：应用名与平台库名**全局唯一**（同一扁平目录里不能重名）。
    `app/*/*/` 与 `config/*.db` 已核无重名；将来若有同名应用，这里要先加组前缀。
    """
    n = 0
    srcs = business_dbs() + (platform_dbs() if config else [])   # 平台库只含 auth.db，见 `platform_dbs`
    for src in srcs:
        dst = shadow / src.name          # 扁平；`x.db-wal` / `x.db-shm` 也跟着落在 `x.db` 旁边
        shutil.copy2(src, dst)
        n += 1
    return n


def missing_shadows(shadow: Path, config: bool = False) -> list:
    """按**运行期的解析规则**算一遍期望路径，返回找不到的那些库名。

    这是本轮加的**自检**：把"副本落盘"与"运行期去找"这两件事在入口处对上一次，
    免得再出现"复制到 A、去找 B、于是静默跑空库"这种谁都不报错的偏差。
    """
    expected = [p.name for p in business_dbs()]
    if config:
        expected += [p.name for p in platform_dbs()]
    return [name for name in expected if not (shadow / name).exists()]


@contextmanager
def shadow_dbs(env: bool = True, inprocess: bool = True, config: bool = False):
    """进入即把业务库复制到临时目录并（按开关）把读写导向副本；退出清理。

    ⚠ **真库在全程不被打开**（复制用的是 `shutil.copy2`，只读）。
    """
    shadow = Path(tempfile.mkdtemp(prefix="fde_shadow_"))
    copied = _copy_all(shadow, config=config)
    # **自检**：按运行期规则找得到副本吗？找不到就当场炸 —— 绝不"静默跑空库"
    # （理由见 `_copy_all` 的注释：这正是本轮修掉的那个偏差）
    _missing = missing_shadows(shadow, config=config)
    if _missing:
        shutil.rmtree(shadow, ignore_errors=True)
        raise RuntimeError(
            f"影子库自检失败：复制了 {copied} 个库，但按运行期解析规则找不到 {_missing[:5]}"
            f"（共缺 {len(_missing)} 个）—— 落盘布局与 `runtime.py`/`users.py` 的解析规则不一致")

    old_env = os.environ.get("FDE_DB_ROOT")
    old_cfg = os.environ.get("FDE_CONFIG_ROOT")
    if env:
        os.environ["FDE_DB_ROOT"] = str(shadow)
    if config:
        os.environ["FDE_CONFIG_ROOT"] = str(shadow)

    _db, _orig = None, None
    if inprocess:
        from fde_platform import db as _db
        _orig = _db.get_connection

        def _patched(app_name, db_path=None):
            if db_path is None:
                return _orig(app_name, db_path)
            p = Path(db_path)
            # 已被 FDE_DB_ROOT 改写过的（已在副本目录下）→ 原样放行
            try:
                p.relative_to(shadow)
                return _orig(app_name, p)
            except ValueError:
                pass
            # 其余一律按**文件名**映射到扁平副本（与 `_copy_all` 的落盘布局一致）；
            # 原先用的是 `p.relative_to(ROOT)`（树形）—— 那是旧布局的产物，会指到不存在的路径。
            return _orig(app_name, shadow / p.name)

        _db.get_connection = _patched

    try:
        yield shadow
    finally:
        if inprocess and _db is not None and _orig is not None:
            _db.get_connection = _orig
        if env:
            if old_env is None:
                os.environ.pop("FDE_DB_ROOT", None)
            else:
                os.environ["FDE_DB_ROOT"] = old_env
        if config:
            if old_cfg is None:
                os.environ.pop("FDE_CONFIG_ROOT", None)
            else:
                os.environ["FDE_CONFIG_ROOT"] = old_cfg
        shutil.rmtree(shadow, ignore_errors=True)


def shadow_clear_prefs(shadow: Path = None) -> int:
    """清掉副本里**每个用户的个人 UI 偏好**（`config/auth.db` 的 `user_prefs`），返回清了多少库。

    为什么非清不可（2026-09-18 实测踩到）：这些偏好是**操作者本机的状态**，而它会改变页面渲染 ——
    真库里有 `cols:psc:sales_forecast = ["基线方法","版本"]`（演示时手动隐藏过两列），
    于是 view e2e 以 admin 登录后**「版本」列根本不渲染**，用例「N+1 行复合键缺列：202608」当场变红。
    测试必须对**任何操作者、任何演示状态**给出同一结果 ⇒ 起点一并清掉个人偏好。

    ⚠ 与页面声明的 `col_default_hidden` 无关：那是**页面默认**（属于应用设计），照常生效；
    这里清的是"某个人后来手动改过的那部分"。**`users` / `roles` 不动** —— 用例自己建自己需要的
    角色与用户（如 `limited_role`），起点留着操作者的真实账号不影响它们（实测真库里也没有同名冲突）。
    """
    base = Path(shadow) if shadow else Path(os.environ.get("FDE_CONFIG_ROOT", ""))
    if not base:
        raise RuntimeError("shadow_clear_prefs 需要 shadow 目录（或已设 FDE_CONFIG_ROOT）")
    db = base / "auth.db"
    if not db.exists():
        return 0
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("DELETE FROM user_prefs").rowcount if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_prefs'"
        ).fetchone() else 0
        conn.commit()
        return n
    finally:
        conn.close()


def auth_db_path() -> Path:
    """`config/auth.db` 的**实际**路径（受 `FDE_CONFIG_ROOT` 影响）。

    view e2e 要**播种 admin**（`UPDATE users SET password_changed=1`）才能登录 ——
    用本函数取路径，影子库模式下拿到的是**副本**路径，于是播种落在副本上、**真库不受影响**。
    """
    root = os.environ.get("FDE_CONFIG_ROOT", "").strip()
    return (Path(root) / "auth.db") if root else (ROOT / "config" / "auth.db")


def shadow_clear(group: str, shadow: Path = None) -> int:
    """**在副本上**清空某组各应用库的全部表（保留库文件、只清数据）。

    语义与 `design-plus/测试执行.md` 的「清表式初始化」一致 —— 区别只是
    **它清的是副本**，所以真库不受影响。测试要"从空表起步"时调它。

    ⚠ **副本是扁平的**（`<影子>/<应用>.db`，与 `runtime.py` 的解析规则一致）：
    组内有哪些应用，从**仓库**侧枚举（`app/<组>/*/*.db`）拿到库名，再去副本里找同名文件。
    原先按树形 glob 副本 `app/<组>/*/*.db` —— 扁平化后会一个都找不到，
    表现为"清表 0 个库"却照样跑（又一个静默偏差）。
    """
    base = Path(shadow) if shadow else Path(os.environ.get("FDE_DB_ROOT", ""))
    if not base or not base.exists():
        raise RuntimeError("shadow_clear 需要 shadow 目录（或已设 FDE_DB_ROOT）")
    cleared = 0
    for src in sorted((ROOT / "app" / group).glob("*/*.db")):
        db = base / src.name
        if not db.exists():
            continue
        conn = sqlite3.connect(str(db))
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")]
            for t in tables:
                conn.execute(f'DELETE FROM "{t}"')
            # **自增序列也要归零**（2026-09-18 加）：`DELETE FROM` 不动 `sqlite_sequence`
            # （它是 `sqlite_%` 表，上面被排除了）⇒ 自增主键会**接着真库的最大值往下发**。
            # 那意味着"清表后的起点"仍取决于演示数据的状态 —— 同一条用例在别的机器/别的演示环境
            # 上会拿到不同的主键值（`md_breakpoint` 的 view e2e 就是这么被照出来的）。
            # 清表 = 回到空库，空库的自增当然从头开始，这样用例才与演示数据无关。
            # （只有存在 AUTOINCREMENT 表时才有这张表，所以先看一眼再删。）
            has_seq = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
            ).fetchone()
            if has_seq:
                conn.execute("DELETE FROM sqlite_sequence")
            conn.commit()
            cleared += 1
        finally:
            conn.close()
    if cleared == 0:
        raise RuntimeError(
            f"shadow_clear('{group}') 一个库都没清到 —— 副本目录里找不到该组的库"
            f"（{base}）。要么影子库没建好，要么落盘布局与解析规则不一致（别静默继续）。")
    return cleared
