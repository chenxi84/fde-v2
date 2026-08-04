"""服务内省 —— 从聚合根类提取"服务清单 + JSON Schema"。

约定（CONVENTION §3）：聚合根的**公共方法**即对外服务，服务名 = 方法名，
`_` 前缀的方法是内部辅助、不暴露；方法的参数与类型标注 + docstring 即入参契约。

本模块用 `inspect`（不执行任何业务代码）把上述契约读成结构化数据，
供三处共用：Web 调用表单、MCP tool 定义、Agent 的 LLM function calling。
"""
import inspect


# Python 类型 → JSON Schema 类型
_TYPE_MAP = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
    "NoneType": "null",
}


def _annotation_to_str(annotation) -> str:
    """把签名里的类型标注归一为字符串（兼容真实类型对象与字符串标注）。"""
    if annotation is inspect.Parameter.empty:
        return "any"
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)


def _json_type(py_type: str) -> str:
    """Python 类型字符串 → JSON Schema 类型（复合类型取基底）。"""
    base = py_type.split("[", 1)[0].strip()
    return _TYPE_MAP.get(base, "string")


def _parse_docstring_args(docstring: str) -> dict:
    """从 Google 风格 docstring 的 Args 段提取 {参数名: 描述}。"""
    descriptions = {}
    in_args = False
    for line in (docstring or "").split("\n"):
        stripped = line.strip()
        if stripped.lower() in ("args:", "arguments:", "parameters:"):
            in_args = True
            continue
        if in_args:
            if stripped.lower().startswith(
                ("returns:", "raises:", "yields:", "examples:", "---")
            ):
                break
            if not stripped or ":" not in stripped:
                continue
            name_part = stripped.split(":", 1)[0].strip()
            desc = stripped.split(":", 1)[1].strip()
            if "(" in name_part:  # 去掉 "name (type)" 里的类型
                name_part = name_part.split("(", 1)[0].strip()
            if name_part and name_part[0].isalpha():
                descriptions[name_part] = desc
    return descriptions


def _safe_default(value):
    """默认值转 JSON 可序列化；不可序列化时退化为字符串。"""
    if value is inspect.Parameter.empty:
        return None
    try:
        import json

        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def list_services(cls) -> list[dict]:
    """列出聚合根类对外暴露的服务（公共方法）及其入参契约。

    Returns:
        [{name, description, parameters:[{name,type,json_type,required,default,description}]}]
        按方法名排序；`_` 前缀与继承自 object 的方法一律不暴露。
    """
    services = []
    for name, fn in vars(cls).items():
        if name.startswith("_") or not inspect.isfunction(fn):
            continue  # 只暴露公共方法；内部辅助（_init_db/_row…）不暴露

        sig = inspect.signature(fn)
        docstring = inspect.getdoc(fn) or ""
        arg_docs = _parse_docstring_args(docstring)

        params = []
        for pname, p in sig.parameters.items():
            if pname == "self":
                continue
            py_type = _annotation_to_str(p.annotation)
            required = p.default is inspect.Parameter.empty
            params.append(
                {
                    "name": pname,
                    "type": py_type,
                    "json_type": _json_type(py_type),
                    "required": required,
                    "default": None if required else _safe_default(p.default),
                    "description": arg_docs.get(pname, ""),
                }
            )

        services.append(
            {
                "name": name,
                "description": docstring.split("\n", 1)[0].strip(),
                "docstring": docstring,
                "parameters": params,
            }
        )

    services.sort(key=lambda s: s["name"])
    return services


def to_mcp_tool(prefix: str, service: dict, *, qualname: str = None,
                group=None, app_name: str = None) -> dict:
    """把一个服务转成 MCP / LLM function calling 通用的 tool 定义。

    工具名 = `<prefix>__<服务名>`，prefix 为组限定应用前缀（'组__名' 或未分组的 '名'，
    见 runtime.tool_prefix；MCP 工具名只允许 [A-Za-z0-9_-]）。_meta.app 为 qualname（路由用）。
    """
    properties = {}
    required = []
    for p in service["parameters"]:
        prop = {"type": p["json_type"]}
        desc = p["description"] or p["name"]
        if p["default"] is not None:
            desc += f"（默认 {p['default']!r}）"
        prop["description"] = desc
        if p["default"] is not None:
            prop["default"] = p["default"]
        properties[p["name"]] = prop
        if p["required"]:
            required.append(p["name"])

    qn = qualname or prefix
    display_app = app_name or qn
    return {
        "name": f"{prefix}__{service['name']}",
        "description": service["description"] or f"{display_app}.{service['name']}",
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
        # 平台内部路由元数据（不进入对外的 MCP schema）；app=qualname 供 platform.call 精确路由
        "_meta": {"app": qn, "service": service["name"], "group": group, "app_name": display_app},
    }


if __name__ == "__main__":  # 手工自检：python -m fde_platform.introspect <app名>
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fde_platform.runtime import FdePlatform

    pf = FdePlatform(Path(__file__).resolve().parents[1] / "app")
    pf.load_all()
    target = sys.argv[1] if len(sys.argv) > 1 else "customer"
    print(json.dumps(pf.services(target), ensure_ascii=False, indent=2))
