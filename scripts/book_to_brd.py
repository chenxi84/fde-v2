#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""书籍 → BRD 分章 md（一次性预处理，接在平台外）。

    python scripts/book_to_brd.py <组名> [--force] [--dry-run]
    python scripts/book_to_brd.py <组名> --only 3404 --prefix WBS    # 往已有组里追加一本

把 `app/<组>/book/` 下的原始书籍（pdf / epub / docx / html，或已是 md / txt）
转成 Markdown，切成章，落到 `app/<组>/brd/第NN章-<标题>.md`。

⚠ **一个组放多本书**：每本书的章号都从「第00章-前言」重启，
不区分就会**后写的覆盖先写的**（且不报错），所以第二本起必须给 `--prefix`
（`WBS-第01章-….md`）。`--only <子串>` 用来只处理其中一本 —— 不加它会把整个
`book/` 重转一遍，把已冻结的那本书的章节文件也重写掉。

切章依据依次降级（见 `_split_chapters`）：
  1. Markdown 一级标题 `# `（EPUB / 手写 md 的正常情况）
  2. **文档自身的编号结构**（`1.0 xxx` / `Appendix A`）——PDF 转出来常常没有标题
  3. 按长度硬切（认不出结构时的兜底）

## PDF 转出来的东西长什么样（两个实测坑，别再踩）

以 NASA 系统工程手册（297 页）为例，markitdown 的产出：

| 现象 | 实测数据 | 本脚本的处理 |
|---|---|---|
| **没有 Markdown 标题** | 297 页只认出 1 个 `#`，还是表格里的一行**假标题** | 降级到"按文档编号结构切"；判有没有真标题用**数量门槛**（真教材一章一个 `#`，动辄十几个），不是"有就行" |
| **页眉页脚逐字重复** | 书名 `NASA SYSTEMS ENGINEERING HANDBOOK` 出现 **268 次**；章节名也当页眉（某一章名 59 次） | 自动剔除：短、重复 ≥5 次、不像句子的行 |

⚠ **页眉剔除必须"保留每个重复行的第一次出现"**：章节名**本身就是重复行**（既作章标题、又作该章每页的页眉）。早期版本把重复行全删，结果真标题也没了、**正文全落进上一章**（第一章吃掉 94% 的篇幅）。

⚠ **附录标题会被正文句子误伤**：`Appendix B of this handbook) and how it will be applied` 也能被 `^Appendix X` 匹配。判据用长度 + 括号，**别用"含 and/of"**——`Appendix F: Functional, Timing, and State Analysis` 会被误杀（踩过）。

修完的效果：27 章，字符保留 97.8%，分布合理（正文 6 章 + 附录 A–T + 前言）。

## 为什么要有这个脚本（而不是手工敲命令）

1. **转换器是可选外部依赖**——装了哪个用哪个，都没装就报清楚怎么装。
   它们**不进平台依赖树**：转换是"每本书跑一次"的离线动作，嵌进来只增安装负担；
   且 MinerU 要下 0.8~2GB 模型、自带重推理依赖，与本项目把 torch 隔离进
   `embed_service` 的既定做法同类，却没常驻价值。
2. **扫描版 PDF 会静默出空文件**——markitdown 的 OCR 是插件，且**没传 llm_client 时
   静默跳过、不报错**。所以这里强制做产出校验：抽出的字符太少就当场报错并给处置建议，
   而不是让你拿着一份空 BRD 往下走。
3. **不覆盖已有 BRD**——目标组的 `brd/` 里若已有 .md（如 PSC 的手写业务文档），
   默认拒绝写入，必须显式 `--force`。

## 目录约定

    app/<组>/book/   原始书籍，任意格式——**不入索引**（见 knowledge_graph._collect_docs）
    app/<组>/brd/    转换产物（分章 md）——**索引源**，也是 design-plus 第①步的输入

## 手工路线（脚本不覆盖的情况）

MinerU 的表格/版面还原强于 markitdown，若转换后表格被压平，可自己跑：

    uv pip install "mineru>=4.0,<5" && mineru -p book.pdf -o out/
    然后把 out/ 里的大 md 丢进 app/<组>/book/ 再跑本脚本——**已是 md 的直接切章，不需要转换器**。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"

# 需要转换器才能读的格式 → 给用户的装法提示
INSTALL_HINT = """装一个转换器即可（任选，**不必**装进项目依赖树）：

  pip install 'markitdown[pdf,docx]'      # 推荐：纯 Python、无 torch，下载约 27 MB
  uv pip install 'mineru>=4.0,<5'         # 表格/版面最强，首次要下模型（约 0.8~2 GB）
  # pandoc（读不了 PDF）：https://pandoc.org/installing.html

扫描版 PDF 另需 OCR：markitdown 要装 markitdown-ocr 插件并传 llm_client，
否则**静默跳过、不报错**（本脚本会因此报"产出过少"）。"""

# 抽出的字符数低于此值就认为转换失败/是扫描件（一本书的正文远大于此）
MIN_CHARS = 800


# ────────────────────────────────────────────────────────────
# 转换器探测
# ────────────────────────────────────────────────────────────

def _markitdown_convert(path: pathlib.Path) -> str:
    """优先用 markitdown 库；库没装但 CLI 在 PATH 上就走 CLI。"""
    try:
        from markitdown import MarkItDown
    except ImportError:
        return subprocess.run(["markitdown", str(path)], capture_output=True,
                              text=True, encoding="utf-8", check=True).stdout
    return MarkItDown().convert(str(path)).text_content


def _pandoc_convert(path: pathlib.Path) -> str:
    """pandoc 只承 epub/docx/html（**读不了 PDF**），所以只作兜底。"""
    r = subprocess.run(["pandoc", "-f", path.suffix.lstrip("."), "-t", "gfm", str(path)],
                       capture_output=True, text=True, encoding="utf-8", check=True)
    return r.stdout


def _detect_converter():
    """返回 (名字, 转换函数)；一个都没有 → None。markitdown 优先。"""
    has_md_lib = False
    try:
        import markitdown  # noqa: F401
        has_md_lib = True
    except ImportError:
        pass
    if has_md_lib or shutil.which("markitdown"):
        return ("markitdown（库）" if has_md_lib else "markitdown（CLI）", _markitdown_convert)
    if shutil.which("pandoc"):
        return ("pandoc", _pandoc_convert)
    return None


# ────────────────────────────────────────────────────────────
# 切章
# ────────────────────────────────────────────────────────────

_SAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _split_by_h1(text: str) -> list[tuple[str, str, bool]]:
    """按一级标题 `# ` 切章 → [(标题, 正文, 是否前言)]。

    开头若有一级标题之前的内容（书名页/前言），归入「前言」（编为第00章），
    不静默丢弃——一本书的前言常含"本书讲什么"，对抽取有价值。
    第三个元素就是给调用方区分"该不该占正文章号"用的。
    """
    lines = text.splitlines()
    chapters: list[tuple[str, str, bool]] = []
    title: str | None = None
    buf: list[str] = []

    def flush():
        if buf and any(x.strip() for x in buf):
            chapters.append((title or "前言", "\n".join(buf).strip(), title is None))

    for ln in lines:
        m = re.match(r"^#\s+(.+?)\s*$", ln)
        if m and not ln.startswith("## "):
            flush()
            buf = []
            title = m.group(1).strip()
        else:
            buf.append(ln)
    flush()
    return chapters


# ────────────────────────────────────────────────────────────
# 兜底切分：PDF 转出来的**平铺文本**（没有 Markdown 标题）
# ────────────────────────────────────────────────────────────

# 主体一级章节：`1.0 Introduction` / `4.0 System Design Processes`
_BODY_SEC = re.compile(r"^([1-9])\.0\s+([A-Z][^\n]{2,70})$")
# 另一种常见的章标题写法：`Chapter 1: Introduction`（NASA WBS 手册就是这种）。
# ⚠ 它**优先于** `N.0`：这类书里 `2.2.1 …` 是**节**，拿它当章会把一章碎成几十份。
_CHAPTER_KW = re.compile(r"^Chapter\s+([1-9]\d*)\s*[:.]?\s+([A-Z][^\n]{2,70})$")
# 最后兜底：**裸章号 + 标题**（`4 Schedule Management Planning`）。
# ⚠ 只在上面两种都认不出时才用（优先级最低）—— 否则会把别的书里的普通编号行当章标题。
# ⚠ 长度放到 78：PDF 里长标题会**折行**（实测「2 NASA Schedule Management: Life Cycle,
#   Requirements, and Best / Practices」被切成两行，标题只到 "…and Best"）。
_BARE_CHAP = re.compile(r"^([1-9]\d?)\s{1,3}([A-Z][^\n]{2,78})$")
# 附录标题：`Appendix A: Acronyms` / `Appendix H: Integration Plan Outline`
# ⚠ 要 `re.I`：有的手册全大写印「APPENDIX A: ACRONYM LISTING」（NASA WBS 手册就是），
#   不忽略大小写这些附录不会单独成章、被并进上一章里（实测：49k 字符的一大坨）
_APPENDIX = re.compile(r"^(Appendix\s+([A-Z]))\b[:.]?\s*(.{0,70})$", re.I)
# 目录行末尾带页码，不是真标题
_TAIL_PAGE = re.compile(r"\s\d{1,3}$")


def _bare_ok(s: str) -> bool:
    """裸章号行的可用性判据（挡 PDF 里的三类假标题）。

    实测踩到的三种：
      · `3 SCoPe website, https://community.max.gov/…` —— **脚注**（带 URL）
      · `54 CADRe/ONCE – Data Collection and Database.` —— 脚注（编号过大、带斜杠、以句点结尾）
      · `4 O c t '1 4` —— 页脚日期被逐字加了空格
    """
    if "http" in s or "/" in s or s.endswith("."):
        return False
    body = s.split(None, 1)[1] if " " in s else ""
    # 逐字加空格的乱码：连续出现 3 个以上"单字符词"
    if len(re.findall(r"(?:^|\s)\S(?=\s|$)", body)) >= 3:
        return False
    return True


def _appendix_ok(s: str) -> bool:
    """排除"像句子的假附录行"。

    平铺文本里 `Appendix B of this handbook) and how it will be applied` 这类
    正文句子也会被 `^Appendix X` 匹配到，靠长度与括号挡掉。

    ⚠ 别用"含 and/of"当判据：合法标题里就有 ——
    `Appendix F: Functional, Timing, and State Analysis` 会被误杀（实测踩过）。
    """
    if len(s) > 70 or "(" in s or ")" in s:
        return False
    return " of this " not in s


def _drop_running_headers(lines: list[str], min_repeats: int = 5,
                          maxlen: int = 60) -> tuple[list[str], int]:
    """丢掉页眉/页脚，**但保留每个重复行的第一次出现**。

    判据：短、重复多次、且不像句子。真实 PDF 每页印书名与当前章节名
    （实测 NASA 手册：书名重复 268 次，章节名重复 25~59 次），逐字相同的噪声
    会进每个 chunk、抽出幽灵实体。

    ⚠ 「保留第一次」是关键：**章节名本身就是重复行**（它既是章标题、又是该章
    每页的页眉）。若把重复行全删，真标题也会跟着没了 —— 正文随即全落进上一章。
    """
    from collections import Counter

    cnt = Counter(l.strip() for l in lines if l.strip())

    def looks_like_header(s: str) -> bool:
        if not s or len(s) > maxlen or cnt[s] < min_repeats:
            return False
        if s.endswith((".", "。", ";", "；", ":", "：", "?", "？", "!", "！")):
            return False          # 像句子 → 不当页眉
        return len(s.split()) <= 9

    out: list[str] = []
    seen: set[str] = set()
    for l in lines:
        s = l.strip()
        if looks_like_header(s):
            if s in seen:
                continue          # 第二次起 = 页眉，丢
            seen.add(s)           # 第一次留下（很可能就是真标题）
        out.append(l)
    return out, len(lines) - len(out)


def _split_by_structure(text: str) -> list[tuple[str, str, bool]]:
    """按**文档自身的编号结构**切章（PDF 平铺文本的兜底）。

    规则（针对"章 + 附录"这类技术手册/教材）：
      1. 主体：`N.0 标题`（N 一位数），按**章号**去重（标题折行会有变体，按整行去重会切重）；
      2. 一旦出现 `Appendix X`，主体规则停用——附录内部有自己的 `1.0 / 2.0`
         小标题（如 Appendix H 的提纲），不关掉会把附录切碎；附录同样按**字母**去重；
      3. 目录行（结尾带页码）、以及像句子的假附录行不认；
      4. 页眉页脚丢弃（保留首次出现）。
    """
    lines = text.splitlines()

    def scan(rx: re.Pattern, tag: str, ok=None) -> list[tuple[str, str]]:
        """认一遍章标题（附录另算）。`seen` 去重，目录里的重复标题被丢掉。`ok` 是可选可用性判据。"""
        marks: list[tuple[str, str]] = []
        seen: set[str] = set()
        in_appendix = False
        for ln in lines:
            s = ln.strip()
            if not s or _TAIL_PAGE.search(s):  # 目录行/带页码 → 跳过
                continue
            ma = _APPENDIX.match(s)
            if ma and _appendix_ok(s):
                key, title = "app:" + ma.group(2), s
                in_appendix = True
            elif not in_appendix:
                m = rx.match(s)
                if not m or (ok is not None and not ok(s)):
                    continue
                key, title = f"{tag}:{m.group(1)}", s
            else:
                continue
            if key in seen:
                continue
            seen.add(key)
            marks.append((title, key))
        return marks

    # 优先显式章标题（`Chapter N:`）；认不出才退到 `N.0` 编号章
    # ⚠ 必须是**嵌套回退**，不能写成两个并列的 if —— 并列时第三级会在"第二级没用到"时
    #   无条件覆盖第一级已经认出来的结果（实测：WBS 那本从 9 章掉回 5 章，附录全丢）。
    marks = scan(_CHAPTER_KW, "chap")
    if len([m for m in marks if m[1].startswith("chap")]) < 2:
        marks = scan(_BODY_SEC, "sec")
        if len([m for m in marks if m[1].startswith("sec")]) < 2:
            marks = scan(_BARE_CHAP, "bare", _bare_ok)   # 最后兜底，只在上面都认不出时用
    if len(marks) < 2:                          # 认不出结构 → 交给按长度切
        return []

    cleaned, dropped = _drop_running_headers(lines)
    titles = [t for t, _ in marks] + [None]
    chapters: list[tuple[str, str, bool]] = []
    buf: list[str] = []
    idx = 0
    head: list[str] = []

    for ln in cleaned:
        s = ln.strip()
        if idx < len(marks) and s == titles[idx]:
            # 遇到第 idx 个章标题：把已积累的正文归给上一章
            if idx == 0:
                head = buf
            else:
                chapters.append((titles[idx - 1], "\n".join(buf).strip(), False))
            buf = []
            idx += 1
            continue
        buf.append(ln)
    if idx > 0:                                  # 最后一章
        chapters.append((titles[idx - 1], "\n".join(buf).strip(), False))

    if any(x.strip() for x in head):             # 第一个标题之前 = 封面/目录/前言
        chapters.insert(0, ("前言", "\n".join(head).strip(), True))

    chapters.append(("__boilerplate__", str(dropped), False))   # 报表用，main 里弹出
    return chapters


def _split_by_size(text: str, chunk: int = 40000) -> list[tuple[str, str, bool]]:
    """最后兜底：按长度切，避免整本书挤成一个文件（那样溯源无从谈起）。"""
    lines = text.splitlines()
    chapters, buf, size, n = [], [], 0, 0
    for ln in lines:
        buf.append(ln)
        size += len(ln) + 1
        if size >= chunk:
            n += 1
            chapters.append((f"片段{n}", "\n".join(buf).strip(), False))
            buf, size = [], 0
    if buf and any(x.strip() for x in buf):
        n += 1
        chapters.append((f"片段{n}", "\n".join(buf).strip(), False))
    return chapters


def _split_chapters(text: str):
    """切章调度 → ([(标题, 正文, 是否前言)], 模式说明)。

    真实 PDF 转出来常常**没有 Markdown 标题**（实测 markitdown 处理一本 297 页手册：
    只产出 1 个 `#`，还是表格里的一行假标题），此时按 `# ` 切会静默退回"整本一章"。
    所以三种切法都跑一遍，**比谁切得更细**：

      1. Markdown 一级标题（`# `）
      2. **文档自身的编号结构**（`1.0 xxx` / `Appendix A`）
      3. 按长度兜底

    ⚠ 判据是**章数多少，不是"有没有标题"**：
      · 真 Markdown 书有几十个 `#`；平铺 PDF 里混进一个假 `#` 只切出 2 段
        —— 比数量比"有就行"稳得多（早先用"≥4 个 `#`"的固定门槛，
        结果 3 章以内的真 Markdown 书被降级成按长度切、标题结构全丢）。
      · 平手时**优先 Markdown 标题**：语义标题优于位置规则。
    """
    h1 = _split_by_h1(text)

    st = _split_by_structure(text)
    st_note = "文档编号结构"
    if st and st[-1][0] == "__boilerplate__":
        st_note += "（丢弃页眉/页脚 %s 行）" % st.pop()[1]

    if len(h1) >= 2 and len(h1) >= len(st):
        return h1, "Markdown 标题（%d 个）" % len(h1)
    if len(st) >= 2:
        return st, st_note
    return _split_by_size(text), "按长度（未识别出任何标题结构）"


def _clean_title(title: str) -> str:
    """清掉 PDF 抽取留下的断词痕迹，如 `H ow` → `How`、`C oncept` → `Concept`。

    只用在**标题**上（文件名与 `#` 首行），不碰正文——正文里同样的模式可能是
    正常换行，动了反而坏。单字母+空格+小写词的组合在标题里几乎只可能是断词。
    """
    t = re.sub(r"\b([A-Z]) (?=[a-z]{2,}\b)", r"\1", title)
    return re.sub(r"\s+", " ", t).strip()


def _chapter_filename(i: int, title: str) -> str:
    """第NN章-<标题>.md。

    标题里若已带章号（"第1章 客户与联系人"），去掉它——否则文件名成
    "第01章-第1章 客户与联系人.md"，重复且难看。文件内的标题原文不动。
    另把路径非法字符换成下划线，压到 60 字内。
    """
    t = re.sub(r"^第\s*[\d一二三四五六七八九十百]+\s*[章节]\s*[、.．:：]?\s*", "", title)
    safe = _SAFE.sub("_", t or title).strip("_ ")
    return f"第{i:02d}章-{safe[:60] or '无题'}.md"


# ────────────────────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────────────────────

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="书籍 → BRD 分章 md（app/<组>/book → app/<组>/brd）")
    ap.add_argument("group", help="应用组名（对应 app/<组>/）")
    ap.add_argument("--force", action="store_true", help="覆盖 brd/ 下已有 .md（默认拒绝）")
    ap.add_argument("--dry-run", action="store_true", help="只列出会产出什么，不写文件")
    ap.add_argument("--only", default="", metavar="子串",
                    help="只处理文件名含该子串的书（一个组里放了多本书时用）")
    ap.add_argument("--prefix", default="", metavar="前缀",
                    help="章节文件名前缀，如 `--prefix WBS` → `WBS-第01章-….md`。"
                         "**一个组放多本书时必须给** —— 每本书的章号都从「第00章-前言」重启，"
                         "不给前缀就是后写的把那本覆盖掉，而且**不报错**")
    args = ap.parse_args()

    book_dir = APP_DIR / args.group / "book"
    brd_dir = APP_DIR / args.group / "brd"
    if not book_dir.is_dir():
        print(f"✗ 未找到 {book_dir}——原始书籍放这里（pdf/epub/docx/md 均可）")
        return 1

    srcs = sorted(p for p in book_dir.rglob("*") if p.is_file() and not p.name.startswith("."))
    if args.only:
        srcs = [p for p in srcs if args.only in p.name]
        if not srcs:
            print(f"✗ book/ 里没有文件名含「{args.only}」的书"
                  f"（现有：{'、'.join(p.name for p in book_dir.iterdir())}）")
            return 1
    if not srcs:
        print(f"✗ {book_dir} 是空的")
        return 1

    # 给了前缀就只认**本前缀**的既有产物：这样往一个已有组里**追加一本**书是允许的
    existing = sorted(brd_dir.glob(f"{args.prefix}-*.md" if args.prefix else "*.md")) \
        if brd_dir.is_dir() else []
    if existing and not args.force and not args.dry_run:
        print(f"✗ {brd_dir} 已有 {len(existing)} 份 .md（如 {'、'.join(p.name for p in existing[:3])} …）")
        print("  本脚本不覆盖已有 BRD。确认要重建请加 --force；")
        print("  只想看看会产出什么，用 --dry-run。")
        return 1

    # 已是文本的不用转换；其余要转换器
    TEXTUAL = {".md", ".markdown", ".txt"}
    need_conv = [p for p in srcs if p.suffix.lower() not in TEXTUAL]
    conv = _detect_converter() if need_conv else None
    if need_conv and conv is None:
        print(f"✗ 有 {len(need_conv)} 份需要转换的文件（{'、'.join(p.name for p in need_conv[:3])}），"
              "但没找到任何转换器。\n")
        print(INSTALL_HINT)
        return 1
    if conv:
        print(f"转换器：{conv[0]}")

    # 先全部读/转 + 切章到内存，**校验通过再落盘**——避免报错时留下半份产物
    plan: list[tuple[pathlib.Path, str, list[tuple[str, str, bool]], str]] = []
    scanned: list[str] = []
    for p in srcs:
        ext = p.suffix.lower()
        if ext in TEXTUAL:
            # 已经是文本：**不设阈值**。空产出这个风险只属于"从二进制里抽"，
            # 用户自己递进来的 txt/md 少就是少（如 MinerU 手工转出的大 md 也走这条路）。
            text = p.read_text(encoding="utf-8", errors="replace")
        else:
            try:
                text = conv[1](p)
            except Exception as e:
                print(f"✗ {p.name} 转换失败：{e}")
                return 1
            if len(text.strip()) < MIN_CHARS:
                scanned.append(p.name)
        chapters, mode = _split_chapters(text)
        plan.append((p, text, chapters, mode))

    if scanned:
        print(f"✗ 这些文件几乎没抽出内容（< {MIN_CHARS} 字符）：{'、'.join(scanned)}")
        print("  ——**疑似扫描版 PDF**。markitdown 的 OCR 是插件，且没传 llm_client 时"
              "静默跳过、不报错：")
        print("    pip install markitdown-ocr openai     # 走 LLM Vision，不引新 ML 库")
        print("  或改用 MinerU（内建 OCR）自己转出 md，丢进 book/ 再跑本脚本。")
        print("  （未写出任何文件）")
        return 2

    written: list[pathlib.Path] = []
    for p, text, chapters, mode in plan:
        print(f"\n── {p.name}")
        print(f"   {len(text)} 字符 → {len(chapters)} 章（切分依据：{mode}）")
        seq = 0
        for title, body, is_pre in chapters:
            title = _clean_title(title)
            if is_pre:
                name = _chapter_filename(0, "前言")      # 前言占第00章
            else:
                seq += 1
                name = _chapter_filename(seq, title)     # 正文从第01章起
            if args.prefix:                              # 多本书：靠前缀分家（否则章号撞车）
                name = f"{args.prefix}-{name}"
            print(f"     {name}  ({len(body)} 字符)")
            if args.dry_run:
                continue
            brd_dir.mkdir(parents=True, exist_ok=True)
            (brd_dir / name).write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
            written.append(brd_dir / name)

    print()
    if not args.dry_run:
        print(f"✓ 已写出 {len(written)} 份分章 md → {brd_dir}")
    print("\n下一步：")
    print(f"  1) 写 app/{args.group}/kg_config.json"
          "（gleaning=1 + entity_types + language，书籍散文建议开补抽）")
    print("  2) python -m fde_platform.embed_service")
    print(f"  3) python -m fde_platform.knowledge_graph index {args.group}")
    print(f"  4) python -m fde_platform.knowledge_graph export {args.group}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
