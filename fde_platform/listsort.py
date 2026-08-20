"""平台级 list 服务通用排序（方案 E · 零应用改动）。

机制：REST 调用 `list` 服务时若携带平台保留参数 `sort_by` / `sort_dir`，
平台在调用层拦截——剥掉 page/size 后调用应用 list（按 CONVENTION 返回全量），
在平台进程内做类型感知排序，再按请求的 page/size 切片返回。
应用侧永远看不到这两个参数（web 层先行弹出），契约签名零变化。

- sort_by  排序字段名（须为 list 返回项的键；不存在时静默降级为默认序）
- sort_dir asc / desc（缺省 asc）
- 空值（None/""）恒排末尾，与方向无关；排序为稳定排序
"""
import re

_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")
_PAGE_KEYS = ("page", "size", "page_size")


def wants_sort(raw: dict) -> bool:
    """请求体是否要求平台排序（仅对 list 服务有意义，调用方自行限定）。"""
    v = raw.get("sort_by")
    return isinstance(v, str) and bool(v.strip())


def pop_sort(raw: dict):
    """弹出排序参数，返回 (sort_by, sort_dir)。"""
    sort_by = str(raw.pop("sort_by")).strip()
    sort_dir = str(raw.pop("sort_dir", "") or "").strip().lower()
    return sort_by, "desc" if sort_dir == "desc" else "asc"


def pop_paging(raw: dict):
    """弹出并解析分页参数（容错非法值），返回 (page, size)。"""
    def _int(v, default):
        try:
            n = int(str(v).strip())
            return n if n > 0 else default
        except (TypeError, ValueError):
            return default
    page = _int(raw.pop("page", None), 1)
    size = raw.pop("size", None)
    if size is None:
        size = raw.pop("page_size", None)   # 历史漂移命名兼容（部分应用 list 用 page_size）
    else:
        raw.pop("page_size", None)
    return page, _int(size, 20)


def apply(result, sort_by: str, sort_dir: str, page: int, size: int):
    """对 list 返回值排序 + 分页切片。容错：结构不符原样返回（不阻断业务）。"""
    extra = {}
    if isinstance(result, dict):
        items = result.get("items")
        if not isinstance(items, list):
            return result
        extra = {k: v for k, v in result.items() if k not in ("items",)}
    elif isinstance(result, list):
        items = result
    else:
        return result

    items = _sorted(items, sort_by, sort_dir)

    total = len(items)
    start = (page - 1) * size
    out = dict(extra)
    out["items"] = items[start:start + size]
    out["total"] = total
    return out


def _sorted(items: list, sort_by: str, sort_dir: str) -> list:
    """类型感知稳定排序；空值恒排末尾；列不存在/不可比较时保持原序。"""
    def val(it):
        return it.get(sort_by) if isinstance(it, dict) else None

    present = [it for it in items if val(it) not in (None, "")]
    absent = [it for it in items if val(it) in (None, "")]
    if not present:
        return items

    # 类型探测：取首个非空值判定整列比较方式
    sample = val(present[0])
    if isinstance(sample, bool):
        kind = "num"
    elif isinstance(sample, (int, float)):
        kind = "num"
    elif isinstance(sample, str) and _DATE_PREFIX.match(sample):
        kind = "date"      # ISO 日期串按字典序即时间序
    else:
        kind = "str"

    def keyfun(it):
        v = val(it)
        if kind == "num":
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        return str(v)

    try:
        if kind == "num" and any(keyfun(it) is None for it in present):
            # 数字列混入不可转数值 → 整体退化为字符串比较
            present.sort(key=lambda it: str(val(it)), reverse=(sort_dir == "desc"))
        else:
            present.sort(key=keyfun, reverse=(sort_dir == "desc"))
    except TypeError:
        # 混合类型兜底：字符串比较，绝不抛错
        present.sort(key=lambda it: str(val(it)), reverse=(sort_dir == "desc"))

    return present + absent
