"""Agent 架构文档读取 helper（供 leader system prompt 装配）。

原「单 Agent」的进度表 / system prompt 组装 / 会话持久化已随应用级 Agent（chat_widget）
一并退役；仅保留 leader 跨应用编排用的架构文档读取。
"""

# 架构文档候选文件名（按优先级）：旧「应用组设计」产出中文名，新「应用组构建」三步法产出英文名。
_ARCH_FILENAMES = ("架构设计.md", "architecture.md")


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
