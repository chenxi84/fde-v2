"""Agent 架构文档读取 helper（供 leader system prompt 装配）。

原「单 Agent」的进度表 / system prompt 组装 / 会话持久化已随应用级 Agent（chat_widget）
一并退役；仅保留 leader 跨应用编排用的架构文档读取。
"""

# 架构文档候选文件名（按优先级）：旧「应用组设计」产出中文名，新「应用组构建」三步法产出英文名。
_ARCH_FILENAMES = ("架构设计.md", "architecture.md")

# 应用级设计文档类型 → 文件名（供智能体按需读取，just-in-time；新增组遵循同一约定即可）
_APP_DOC_FILENAMES = {
    "应用详设": "应用详设.md",
    "前端详设": "前端详设.md",
    "前端测试用例": "前端测试用例.md",
    "README": "README.md",
}


def _read_arch_docs(platform, group: str | None = None) -> str:
    """读取架构设计文档（app/<组>/架构设计.md 或 architecture.md），拼成跨应用编排依据。

    group 非空时只读该组；None 读全部组。
    """
    groups = [group] if group else platform.groups()
    parts = []
    apps_dir = platform.apps_dir
    for g in groups:
        text = ""
        for fname in _ARCH_FILENAMES:
            p = apps_dir / g / fname
            try:
                if p.is_file():
                    text = p.read_text(encoding="utf-8").strip()
                    if text:
                        break
            except OSError:
                continue
        if text:
            parts.append(f"# 应用组：{g}\n\n{text}")
    return "\n\n---\n\n".join(parts)


def read_app_doc(platform, app_name: str, doc_type: str) -> str:
    """按需读取指定应用的某类设计文档，返回全文（缺失返回空串）。

    用于智能体深入某个应用开发/改造前，先了解其业务规则（BR）/功能（FUNC）/数据字典。
    app_name 支持 qualname（如 psc/sales_forecast）或短名；doc_type 见 _APP_DOC_FILENAMES。
    """
    fname = _APP_DOC_FILENAMES.get(doc_type)
    if not fname:
        return ""
    try:
        handle = platform.handle(app_name)
        if handle is None:
            return ""
        p = handle.folder / fname
        if not p.is_file():
            return ""
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
