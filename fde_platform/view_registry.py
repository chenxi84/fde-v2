"""FDE v2 平台 — 前端视图注册表（动态扫描，零手工登记）。

视图与后端同构——**约定优于配置、扫描即发现、零登记**，且**前后端同文件夹**：
每个应用页就放在该应用的后端目录里 `app/<组>/<应用>/view.{js,html}`，与 `<应用>.py`、
`README.md`、`resource/` 并列——一个应用 = 一个文件夹，前后端一起生成、一起交付。

页面来源（两类，按组合并）：

1. **应用页** = `app/<组>/<应用>/view.js`（key = 应用目录名，与后端应用名/page_id 对齐；
   经 `/app/<应用>/view.js` 写死端点 serve，绝不暴露同目录的 .py/.db）。
2. **组级页** = `view/<组>/<key>.js`（key = 文件名；经 `/view/<组>/<key>.js` 静态 serve）。
   仅给「无后端应用的组级聚合页」用（如 dashboard）；组名必须是 `app/` 下真实存在的组。

平台公共页 = `view/pages/*.js`（元数据取自 `lib/shell.js` 的 `PLATFORM_PAGES`）。
**console（通用服务台）不进清单**：其服务调用是动态的（不可派生），仅 admin 可见、不可授权。

每页自描述：文件内 `export const PAGE_META = {key,name,ic,title,crumb,order}` 字面量
（应用页的 key 以目录名为准，PAGE_META.key 仅组级页/缺省时用）。服务派生：扫描页面源码
`svc("app","service")` 字面量 → 页 → {(app,service)} 边集（角色获授该页即隐式放行这些服务，
仅限携带 X-Fde-Page 头的调用，见 auth.py 闸门）。

壳启动清单（`boot_manifest`）：某组有序页面（按 PAGE_META.order 升序）+ 约定推导品牌，
经 `/api/view_boot` 下发；壳 `bootShell` 据此动态 `import()` 各页工厂装配菜单。
品牌约定推导（name=`FDE·<组名大写>`，foot=`<组名> 组 · N 页面`），无任何配置文件。

缓存：以全部被扫描文件的 mtime 最大值为令牌，变化即失效；`invalidate()` 供管理页手动刷新。
page_id 形如 `crm:customer` / `crm:dashboard` / `_platform:agent`。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
VIEW_DIR = ROOT / "view"
PLATFORM_MODULE = "_platform"
CONSOLE_KEY = "console"  # 仅 admin 可见，不进授权清单

# shell.js 的 PLATFORM_PAGES 字面量（平台公共页元数据）：key, name, ic
_META_RE = re.compile(
    r'\{\s*key:\s*"([^"]+)"\s*,\s*name:\s*"([^"]+)"\s*,\s*ic:\s*"([^"]*)"')
# 页面自描述块：export const PAGE_META = { ... }（值为字符串/数字，无嵌套大括号）
_PAGE_META_RE = re.compile(r'export\s+const\s+PAGE_META\s*=\s*\{(.*?)\}', re.S)
# 页面源码中的服务调用字面量（动态拼名的调用扫不到——那是服务台的特权）
_SVC_RE = re.compile(r'svc\(\s*"([A-Za-z_][\w]*)"\s*,\s*"([A-Za-z_][\w]*)"')

_cache: dict = {"token": None, "data": None}


def _groups() -> list:
    """app/ 下的一级非隐藏目录 = 组（同 runtime 约定：组名 = 一级目录名）。"""
    if not APP_DIR.exists():
        return []
    return sorted(
        d for d in APP_DIR.iterdir()
        if d.is_dir() and not d.name.startswith((".", "_")))


def _parse_meta(js_path: Path) -> dict:
    """从 shell.js PLATFORM_PAGES 宽松解析 {key: (name, ic)}；失败返回空（回落 key）。"""
    try:
        text = js_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return {m.group(1): (m.group(2), m.group(3)) for m in _META_RE.finditer(text)}


def _parse_page_meta(js_path: Path) -> dict:
    """从页面源码解析 PAGE_META 字面量 → {name,ic,title,crumb,order,key?}（部分可缺）。

    无 PAGE_META 块返回空 dict，调用方按文件名/目录名回落（只影响美观，不坏授权/启动）。"""
    try:
        text = js_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = _PAGE_META_RE.search(text)
    if not m:
        return {}
    body = m.group(1)

    def s(field):
        mm = re.search(rf'{field}\s*:\s*"((?:[^"\\]|\\.)*)"', body)
        return mm.group(1) if mm else None

    def n(field):
        mm = re.search(rf'{field}\s*:\s*(-?\d+)', body)
        return int(mm.group(1)) if mm else None

    out = {}
    for f in ("key", "name", "ic", "title", "crumb", "col_default_hidden"):
        v = s(f)
        if v is not None:
            out[f] = v
    order = n("order")
    if order is not None:
        out["order"] = order
    return out


def _read_services(js_path: Path) -> list:
    try:
        text = js_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return sorted({".".join(m) for m in _SVC_RE.findall(text)})


def _scan() -> dict:
    """全量扫描 → {modules, platform_pages, services, token}。"""
    modules, services = [], {}
    scanned = [VIEW_DIR / "lib" / "shell.js"]

    for g in _groups():
        group = g.name
        pages = []

        # ① 应用页：app/<组>/<应用>/view.js（key = 应用目录名，与后端应用名对齐）
        for app_dir in sorted(g.iterdir()):
            vjs = app_dir / "view.js"
            if not (app_dir.is_dir() and vjs.exists()):
                continue
            scanned.append(vjs)
            meta = _parse_page_meta(vjs)
            key = app_dir.name
            name = meta.get("name") or key
            pid = f"{group}:{key}"
            entry = {
                "id": pid, "key": key, "name": name,
                "ic": meta.get("ic") or "▢",
                "title": meta.get("title") or name,
                "crumb": meta.get("crumb") or "",
                "order": meta.get("order"),
                "url": f"/app/{group}/{key}/view.js",
            }
            if meta.get("col_default_hidden"):
                entry["col_default_hidden"] = meta["col_default_hidden"]
            pages.append(entry)
            services[pid] = _read_services(vjs)

        # ② 组级页：view/<组>/<key>.js（无后端应用的组级聚合页，如 dashboard）
        gview = VIEW_DIR / group
        if gview.is_dir():
            for js in sorted(gview.glob("*.js")):
                scanned.append(js)
                meta = _parse_page_meta(js)
                key = meta.get("key") or js.stem
                name = meta.get("name") or key
                pid = f"{group}:{key}"
                pages.append({
                    "id": pid, "key": key, "name": name,
                    "ic": meta.get("ic") or "▦",
                    "title": meta.get("title") or name,
                    "crumb": meta.get("crumb") or "",
                    "order": meta.get("order"),
                    "url": f"/view/{group}/{js.name}",
                })
                services[pid] = _read_services(js)

        if pages:
            modules.append({"module": group, "pages": pages})

    # 平台公共页（console 除外：动态调用不可派生，仅 admin 可见）
    meta = _parse_meta(VIEW_DIR / "lib" / "shell.js")
    platform_pages = []
    plat_dir = VIEW_DIR / "pages"
    if plat_dir.is_dir():
        for js in sorted(plat_dir.glob("*.js")):
            scanned.append(js)
            key = js.stem
            if key == CONSOLE_KEY:
                continue
            name, ic = meta.get(key, (key, "✦"))
            platform_pages.append(
                {"id": f"{PLATFORM_MODULE}:{key}", "key": key, "name": name, "ic": ic})

    token = max((f.stat().st_mtime for f in scanned if f.exists()), default=0)
    return {"modules": modules, "platform_pages": platform_pages,
            "services": services, "token": token}


def _mtime_token() -> float:
    """stat 级探测令牌：全部被扫描文件的 mtime 最大值（不读内容，供逐请求缓存校验）。"""
    files = [VIEW_DIR / "lib" / "shell.js"]
    for g in _groups():
        for app_dir in g.iterdir():
            vjs = app_dir / "view.js"
            if app_dir.is_dir() and vjs.exists():
                files.append(vjs)
        gview = VIEW_DIR / g.name
        if gview.is_dir():
            files.extend(gview.glob("*.js"))
    pd = VIEW_DIR / "pages"
    if pd.is_dir():
        files.extend(pd.glob("*.js"))
    return max((f.stat().st_mtime for f in files if f.exists()), default=0)


def _current() -> dict:
    """取缓存；mtime 令牌变化（新增页面/改源码）才整体重扫读内容。"""
    if _cache["data"] is None or _mtime_token() != _cache["token"]:
        fresh = _scan()
        _cache["data"], _cache["token"] = fresh, fresh["token"]
    return _cache["data"]


def invalidate() -> None:
    """手动清缓存（管理页「重新扫描」）。"""
    _cache["token"], _cache["data"] = None, None


def registry() -> dict:
    """授权 UI / 线路图用：{modules:[{module, pages:[{id,key,name,ic,title,crumb,
    order,url}]}], platform_pages:[...], services:{page_id: ['app.svc', ...]}}。"""
    d = _current()
    return {"modules": d["modules"], "platform_pages": d["platform_pages"],
            "services": d["services"]}


def viewable_groups() -> list:
    """有视图页面的组名（/view/ 清单与通用壳渲染判据）。"""
    return [m["module"] for m in _current()["modules"]]


def boot_manifest(module: str) -> dict | None:
    """某组的壳启动清单：{module, brand, pages(按 order 升序)}；无页面的组返回 None。

    品牌按约定推导，无配置文件——与后端"组建目录即生效"对称。"""
    d = _current()
    mod = next((m for m in d["modules"] if m["module"] == module), None)
    if mod is None:
        return None
    pages = sorted(
        mod["pages"],
        key=lambda p: (p.get("order") is None, p.get("order") or 0, p["key"]))
    n = len(pages)
    return {
        "module": module,
        "brand": {
            "name": f"FDE<em>·</em>{module.upper()}",
            "sub": "FORWARD DEPLOYED",
            "foot": f"{module} 组 · {n} 页面",
        },
        "pages": pages,
    }


def all_page_ids() -> set:
    """注册表内全部 page_id（含平台页，不含 console）。"""
    d = _current()
    ids = {p["id"] for m in d["modules"] for p in m["pages"]}
    ids |= {p["id"] for p in d["platform_pages"]}
    return ids


def page_services(page_id: str) -> set:
    """页面派生的 (app, service) 边集（隐式放行判定用；未知页 → 空集）。"""
    d = _current()
    return {tuple(k.split(".", 1)) for k in d["services"].get(page_id, [])}
