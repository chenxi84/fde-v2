"""FDE v2 平台 —「FDE 应用组构建」后台 runner（LangGraph 独立 agent）。

把「架构创建」建模为一张 LangGraph 状态图，**分段生成**避免单次输出超长被截断：

    gather → outline → cards → relations → assemble → write
      收集输入   ①总表    ②逐聚合根卡   ③关系图+决策   拼装+完整性校验   落盘

由**单个后台 worker 线程串行**执行任务；SqliteSaver 断点持久化（config/groupbuild_graph.db）
→ 重启可续跑。cards 段对多个聚合根做有界并发（≤_CARDS_PARALLEL）的 LLM 调用以提速。

与旧「应用组设计」功能（design_runner / builder / skill）**零关联**：
- 不调用 builder.py 任何提示词函数，system prompt 本模块自写；
- 只通过 fde_platform.llm.get_provider(LLM_ROLE) 取 LLM —— llm.py 是全平台共用的
  留存基础设施，LLM_ROLE="builder" 仅是其配置档案键（共用 builder 的模型配置），
  并非引用将被删除的 builder.py 代码。
"""
import ast
import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from fde_platform import groupbuild_store, llm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = PROJECT_ROOT / "app"
DESIGN_SPEC = PROJECT_ROOT / "design" / "架构设计.md"   # 第①步聚合根识别技能规格（方法依据）
DESIGN_SPEC_DETAIL = PROJECT_ROOT / "design" / "应用设计.md"   # 第②步逐聚合根应用设计规格（模板+契约）
GRAPH_DB = PROJECT_ROOT / "config" / "groupbuild_graph.db"
GRAPH_DB_DESIGN = PROJECT_ROOT / "config" / "groupbuild_design_graph.db"   # 第②步图断点库
GRAPH_DB_CODE = PROJECT_ROOT / "config" / "groupbuild_code_graph.db"       # 第③步图断点库
GRAPH_DB_TESTCASE = PROJECT_ROOT / "config" / "groupbuild_testcase_graph.db"   # 第④步图断点库
GRAPH_DB_TESTEXEC = PROJECT_ROOT / "config" / "groupbuild_testexec_graph.db"   # 第⑤步图断点库
GRAPH_DB_BUGFIX = PROJECT_ROOT / "config" / "groupbuild_bugfix_graph.db"       # ⑤回路·提案任务断点库
GRAPH_DB_BUGFIX_APPLY = PROJECT_ROOT / "config" / "groupbuild_bugfix_apply_graph.db"  # ⑤回路·应用任务断点库
GRAPH_DB_CONTRACTS = PROJECT_ROOT / "config" / "groupbuild_contracts_graph.db"  # ⑧契约冻结断点库
GRAPH_DB_FDESIGN = PROJECT_ROOT / "config" / "groupbuild_fdesign_graph.db"  # ⑨前端详设断点库
GRAPH_DB_FCODE = PROJECT_ROOT / "config" / "groupbuild_fcode_graph.db"      # ⑩前端编码断点库
GRAPH_DB_FTEST = PROJECT_ROOT / "config" / "groupbuild_ftest_graph.db"      # ⑪前端测试（用例生成）断点库
GRAPH_DB_FVERIFY = PROJECT_ROOT / "config" / "groupbuild_fverify_graph.db"  # ⑫前端测试执行断点库
FDESIGN_SPEC = PROJECT_ROOT / "design" / "前端设计.md"        # ⑨（九步法第⑥步）前端设计技能规格
FCODE_SPEC = PROJECT_ROOT / "design" / "前端编码.md"          # ⑩（九步法第⑦步）前端编码技能规格
FTEST_SPEC = PROJECT_ROOT / "design" / "前端测试.md"          # ⑪（九步法第⑧步）前端测试用例技能规格
FVERIFY_SPEC = PROJECT_ROOT / "design" / "前端测试执行.md"    # ⑫（九步法第⑨步）前端测试执行技能规格
VIEW_VERIFY_PARADIGM = PROJECT_ROOT / "design" / "前端验收样板" / "verify_view_e2e.py"  # ⑫ 脚本范式（组级形态）
VIEW_CONVENTION = PROJECT_ROOT / "design" / "VIEW_CONVENTION.md"  # 前端视图约定正本
VIEW_PATTERNS = PROJECT_ROOT / "design" / "view-convention" / "patterns.md"  # 前端代码骨架（逐块范式）
VIEW_PITFALLS = PROJECT_ROOT / "design" / "view-convention" / "pitfalls.md"  # 前端踩坑清单（dashboard 铁律来源）
VIEW_DIR = PROJECT_ROOT / "view"                              # 组级看板落点根（view/<组>/dashboard.*，在 APPS_DIR 之外）
CODING_SPEC = PROJECT_ROOT / "design" / "CONVENTION.md"   # 第③步编码规范正本（CONVENTION v2）
TESTCASE_SPEC = PROJECT_ROOT / "design" / "应用测试.md"   # 第④步测试用例生成技能规格
TESTEXEC_SPEC = PROJECT_ROOT / "design" / "测试执行.md"   # 第⑤步测试执行技能规格
BUGFIX_SPEC = PROJECT_ROOT / "design" / "BUG修复.md"      # 第⑤步回路·BUG 修复技能规格
SANDBOX_BASE = PROJECT_ROOT / "config" / ".testexec"   # 一次性沙箱根（⑧契约冻结 dump 用；第⑤步已改真实树直跑）
# ⑤回路·BUG 修复提案生成的并发度（逐失败例一次 LLM 调用）
_BUGFIX_PARALLEL = int(os.environ.get("GROUPBUILD_BUGFIX_PARALLEL", "3"))

# 共用 builder 的大模型配置（llm.py 的配置档案键，非 builder.py 代码）
LLM_ROLE = "builder"


# ── 任务终止（协作式取消）──────────────────────────────
class TaskCancelled(Exception):
    """任务被用户终止（在检查点感知到 cancel_requested 标志）。"""

# 本进程 worker 当前执行的任务 id（单线程串行，线程本地即安全）；LLM 中断钩子据此检查
_CANCEL_LOCAL = threading.local()
# 进程内快速取消标志（admin API 线程写、worker 线程与 LLM 钩子读；set 操作 GIL 原子）
_CANCEL_FLAGS: set = set()


def _cancel_flagged() -> bool:
    """快速检查（LLM 流式逐块钩子 / 子进程轮询用）：当前线程任务是否已被请求取消。"""
    tid = getattr(_CANCEL_LOCAL, "tid", None)
    return tid is not None and tid in _CANCEL_FLAGS


def _check_cancel(task_id: int = None) -> None:
    """检查点：进程内标志或 DB cancel_requested → 抛 TaskCancelled。

    由 _cancel_guard（节点入口）、_chat（LLM 调用前）、修复 / 运行循环调用。"""
    tid = task_id if task_id is not None else getattr(_CANCEL_LOCAL, "tid", None)
    if tid is None:
        return
    if tid in _CANCEL_FLAGS:
        raise TaskCancelled(f"任务 #{tid} 已被用户终止")
    t = groupbuild_store.get_task(tid)
    if t and t.get("cancel_requested"):
        _CANCEL_FLAGS.add(tid)
        raise TaskCancelled(f"任务 #{tid} 已被用户终止")


def request_cancel_task(task_id: int) -> bool:
    """请求终止任务（admin API 调）：DB 标志 + 进程内快速标志。"""
    ok = groupbuild_store.request_cancel(task_id)
    if ok:
        _CANCEL_FLAGS.add(task_id)
    return ok


def _cancel_guard(fn):
    """图节点包装：进节点前先查取消（命中即抛，run_task 落 cancelled 终态）。"""
    def wrapped(state):
        _check_cancel(state.get("task_id"))
        return fn(state)
    return wrapped


llm.set_interrupt_check(_cancel_flagged)   # 长时生成秒级中断：流式逐块检查取消标志

# 逐聚合根卡生成的并发度（LLM I/O 密集；过高易触发网关限流）
_CARDS_PARALLEL = 3
# 第②步应用详设并发度：把「N 应用 × 4 段」全部摊平成独立 LLM 任务统一调度，并发
# 跨应用、跨段同时铺开（故默认高于第①步卡并发）。过高易触发网关限流，可 env 调。
_DETAIL_PARALLEL = int(os.environ.get("GROUPBUILD_DETAIL_PARALLEL", "6"))
# 第③步应用编码并发度：把「N 应用 ×（2 段代码 + 1 README）」全部摊平统一调度，同第②步。
_CODE_PARALLEL = int(os.environ.get("GROUPBUILD_CODE_PARALLEL", "6"))
# 第③步门禁失败（语法错）后的自动重生成修复次数：把错误行及上下文回喂模型、只重发出错段。
_CODE_REPAIR_RETRIES = int(os.environ.get("GROUPBUILD_CODE_REPAIR_RETRIES", "2"))
# 第④步测试用例：数据字典先行冻结，主链 / 分支两段摊平并发（段数固定为 2，故并发小）。
_TESTCASE_PARALLEL = int(os.environ.get("GROUPBUILD_TESTCASE_PARALLEL", "2"))
# 第⑤步测试执行：跑败后 LLM 回喂修复脚本的最大重跑轮数（应用 bug 只降级软失败、不自动改应用代码）
_TESTEXEC_REPAIR = int(os.environ.get("GROUPBUILD_TESTEXEC_REPAIR", "3"))
# 第⑤步单次运行超时（秒）
_TESTEXEC_RUN_TIMEOUT = int(os.environ.get("GROUPBUILD_TESTEXEC_RUN_TIMEOUT", "900"))
# ⑧契约冻结：沙箱 dump 超时（秒；带造数链的组本地 stub 约 1–3 分钟）
_CONTRACTS_RUN_TIMEOUT = int(os.environ.get("GROUPBUILD_CONTRACTS_RUN_TIMEOUT", "600"))
# ⑨前端详设：逐应用 job（+1 dashboard job）摊平并发度与门禁重生成轮数
_FDESIGN_PARALLEL = int(os.environ.get("GROUPBUILD_FDESIGN_PARALLEL", "6"))
_FDESIGN_REPAIR = int(os.environ.get("GROUPBUILD_FDESIGN_REPAIR", "2"))
# ⑩前端编码：单元 = 应用 + dashboard 同池摊平（单元内 js→html 两阶段串行，每单元 2–4 次 LLM
# 调用，故默认并发低于⑨）；门禁重生成轮数按文件计（js/html 各自 ≤N 轮）。
_FCODE_PARALLEL = int(os.environ.get("GROUPBUILD_FCODE_PARALLEL", "4"))
_FCODE_REPAIR = int(os.environ.get("GROUPBUILD_FCODE_REPAIR", "2"))
# ⑪前端测试用例：逐应用 job（+1 组级补充 job）摊平并发度与门禁重生成轮数
_FTEST_PARALLEL = int(os.environ.get("GROUPBUILD_FTEST_PARALLEL", "6"))
_FTEST_REPAIR = int(os.environ.get("GROUPBUILD_FTEST_REPAIR", "2"))
# ⑫前端测试执行：脚本生成并发（单脚本产出 500–700 行长流，网关并发长流易空响应，默认串行）
# / 逐脚本修复轮数 / 单脚本运行超时（秒）
_FVERIFY_PARALLEL = int(os.environ.get("GROUPBUILD_FVERIFY_PARALLEL", "1"))
_FVERIFY_REPAIR = int(os.environ.get("GROUPBUILD_FVERIFY_REPAIR", "2"))
_FVERIFY_RUN_TIMEOUT = int(os.environ.get("GROUPBUILD_FVERIFY_RUN_TIMEOUT", "600"))
# 第⑤步回喂模型 / 写入报告的运行输出尾部长度（字符）
_TESTEXEC_OUTPUT_TAIL = int(os.environ.get("GROUPBUILD_TESTEXEC_OUTPUT_TAIL", "6000"))
# 第⑤步分块生成的单块用例文本上限（字符）：超大组（如 19 应用、10 万字用例）按 § 章节 +
# TC 用例块边界自适应切成多块逐块生成，规避单段撞 max_tokens 截断（'{' was never closed）/ 网关推理超时。
_CHUNK_MAX_CHARS = int(os.environ.get("GROUPBUILD_CHUNK_MAX_CHARS", "30000"))
# 第④步每个应用详设节选截断上限（字符）：整组详设全注入过大，取前段（§1-4 功能/BR/状态机为主）。
_DETAIL_EXCERPT = int(os.environ.get("GROUPBUILD_DETAIL_EXCERPT", "9000"))
# 单份 BRD 文件读入内容的截断上限（字符），避免超大文件撑爆上下文
_BRD_MAX_CHARS = 40000
# 视为文本、可读入内容的扩展名；其余按二进制登记（不读内容）
_TEXT_SUFFIXES = {".md", ".txt", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml",
                  ".html", ".htm", ".log", ""}

# 所有分段共用的角色与方法 preamble（自写，不复用 builder.py）
_ROLE_PREAMBLE = (
    "你是 FDE 平台的「聚合根识别」技能（fde-aggregate-identification），"
    "负责把一个业务整体设计识别为一组 DDD 聚合根，每个聚合根对应一个 FDE 应用。\n"
    "严格依照下面给出的《技能规格》执行其『识别方法』与『输出结构』。铁律：\n"
    "- 聚合根名用英文 snake_case、类名 PascalCase；一个聚合根 = 一个同名应用/文件夹/类/库/事务边界；\n"
    "- 聚合间用 ID 弱引用 + 跨应用调用（self.fde.call），不共享事务；主数据独立成基础应用；外部系统不建聚合；\n"
    "- 绝不臆造——输入未覆盖的内容不自行填充。\n"
)

# ── 第②步（逐聚合根应用设计）分段规格 ──────────────────
# 每份《应用详设》按模板第1–7部分拆 4 段生成，规避单次输出超 max_tokens 被截断
# （S1=§1-2 / S2=§3 / S3=§4 / S4=§5-7）。每段 (键, 范围标签, 指令)。
_DETAIL_SECTIONS = [
    ("part12", "第1部分『需求概览』+ 第2部分『用户故事』",
     "本次【只】输出第1部分『需求概览』和第2部分『用户故事』的 markdown（以 `## 1. 需求概览` 开头）。"
     "把该聚合根的每个对外操作（含被其它聚合调用的服务）映射为用户故事 US-xx，各含 Given-When-Then 验收场景。"
     "不要输出第3部分及之后。"),
    ("part3", "第3部分『业务场景』",
     "本次【只】输出第3部分『业务场景』的 markdown（以 `## 3. 业务场景` 开头）。含业务流程、业务规则"
     "（BR-xx：除卡内边界不变量外，**必须补全逐字段校验规则**——唯一/必填/取值范围/数量上下限/金额>0 等，"
     "每条含适用场景与示例）、业务数据、状态机（mermaid stateDiagram + 状态转换规则矩阵；无状态机则注明）。"
     "不要输出其它部分。"),
    ("part4", "第4部分『功能描述』",
     "本次【只】输出第4部分『功能描述』的 markdown（以 `## 4. 功能描述` 开头）。含功能清单（FUNC-xx）+ "
     "功能详细说明（每个对外操作/被调服务一个功能，含功能类型/用户操作流程/输入输出数据/业务规则/特殊处理/字段表）。"
     "把核心属性（含值对象、行项目子实体）展开为字段表（字段名/字段类型/是否必填/默认值/业务逻辑）。不要输出其它部分。"),
    ("part567", "第5部分『权限要求』+ 第6部分『验收标准』+ 第7部分『参考资料』",
     "本次【只】输出第5部分『权限要求』（功能权限矩阵 PERM-xx + 数据权限）、第6部分『验收标准』、"
     "第7部分『参考资料』的 markdown（以 `## 5. 权限要求` 开头）。在§7外部依赖中列清：引用的聚合（by ID 弱引用）、"
     "跨应用调用（self.fde.call，注明调用方→被调服务）、外部系统接口（SAP E-0x / MOM / APS / WMS / TMS / MDM / CTCT，"
     "注明为外部适配器）；把 architecture.md『待确认』中与本聚合相关的条目落入§6.3已知限制/§7.4备注。不要输出第1–4部分。"),
]

_DETAIL_PREAMBLE = (
    "你是 FDE 平台的「逐聚合根应用设计」技能（应用构建第②步），负责为**一个**聚合根（= 一个 FDE 应用）"
    "产出《用户需求规格说明书》（即『应用详设』）。严格依照下面给出的《应用设计.md》模板的第1–7部分结构、"
    "ID 体系（US/BR/FUNC/PERM）与『使用契约·填写映射』执行。铁律：\n"
    "- 只聚焦指定的这一个聚合根；跨聚合协作写进『特殊处理/外部依赖』，不替别的聚合设计；\n"
    "- US/BR/FUNC/PERM 编号按本份文件独立递增（US-01…/BR-01…/FUNC-01…/PERM-01…）；\n"
    "- 绝不臆造——architecture.md 与 BRD 都未说清的字段/规则/流程，标注『待确认』，不编造取值或步骤。\n"
)

# 第②步单份详设完整性闸门：须含 7 个部分关键词 + 四类 ID 前缀
_DETAIL_PARTS = ["需求概览", "用户故事", "业务场景", "功能", "权限", "验收标准", "参考资料"]

# ── 第③步（应用编码）分段规格 ──────────────────────────
# 每个聚合根的 <应用>.py 拆 2 段生成（code0=文件头+建表+核心方法 / code1=其余方法+适配器），
# 规避整份大类撞 max_tokens 截断；README 另一次短调用。各段 (槽位键, 范围标签, 指令)。
_CODE_PREAMBLE = (
    "你是 FDE 平台的「应用编码」技能（应用组构建第③步），负责把**一个**聚合根的《应用详设》"
    "落成可运行的 FDE 应用代码（`<应用>.py`）。编码规范**严格依照**下方《CONVENTION.md》"
    "（CONVENTION v2 正本）。铁律：\n"
    "- 一个聚合根 = 一个同名类/文件/库/事务边界；类名 = 应用名的 PascalCase；\n"
    "- 文件顶部 `from fde import FdeError`；`_init_db(self)` **必选**、幂等 `CREATE TABLE IF NOT EXISTS`，"
    "字段严格按详设§4字段表；\n"
    "- 用 `self.db` 执行 SQL、`self.fde.call(\"应用\",\"服务\",**params)` 跨应用（只认名不 import）、"
    "`self.ctx` 读身份；**不** `sqlite3.connect`、**不** import 其它应用、**不**写 `__init__`、"
    "**不**写鉴权、**不**手动 commit/rollback（事务归平台）；\n"
    "- 业务失败 `raise FdeError(\"人话\")`；成功返回可 JSON 序列化业务值；\n"
    "- ⚠️ **公共方法禁写返回类型注解**（§12.1，内省陷阱 `'function' object is not subscriptable`）；参数注解可保留；\n"
    "- 外部系统（SAP/MOM/WMS/APS/MDM/CTCT…）封装为 `_` 前缀适配器方法，不建聚合；\n"
    "- 绝不臆造：详设 / 架构未说清的字段 / 规则标『待确认』注释，不编造实现。\n"
    "- **代码中一律使用半角 ASCII 标点**：全角中文标点（，；：（）｛｝等）只能出现在字符串字面量"
    "（如 FdeError 消息）或注释里，**绝不可出现在代码中**（会导致 `invalid character` 语法错）。\n"
    "- **只输出纯代码 / markdown 正文，不要 ``` 围栏、不要任何解释文字**。\n"
)

# 加载 e2e 黄金参考代码（注入 builder prompt 提升生成质量）
def _load_golden_ref() -> str:
    """读 e2e 参考应用代码，作为 builder 的黄金代码样例。"""
    refs = []
    for app_name in ("member", "task"):
        p = PROJECT_ROOT / "app" / "e2e" / app_name / f"{app_name}.py"
        if p.is_file():
            try:
                refs.append(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    if not refs:
        return ""
    return ("\n\n===== 黄金参考范例（FDE v2 标准代码，严格模仿其风格/模式/质量）=====\n"
            + "\n---\n".join(refs[:1])   # 只给一个范例（member.py 173行），避免 prompt 过长
            + "\n----- 范例结束 -----\n"
            + "上述代码展示了 FDE 应用的**唯一正确写法**：\n"
            + "- 所有 import 在文件顶部（绝不在方法体内 import）\n"
            + "- SQL 只用参数化 `?` 占位符（绝不用 f-string 拼接 SQL）\n"
            + "- 私有辅助方法 `_clean()` / `_validate_*()` / `_to_dict()` 抽取公共逻辑\n"
            + "- 类内方法定义行恰好缩进 4 空格，方法体 8 空格\n"
            + "- 绝不出现重复方法定义\n"
            + "**你的代码必须达到同样的质量标准。**\n")

_GOLDEN_REF = _load_golden_ref()

_CODE_SLOTS = [
    ("code0", "`<应用>.py` 前半部分（文件头 + 建表 + 核心公共方法）",
     "本次【只】输出 `<应用>.py` 的**前半部分**：从文件顶部开始——模块 docstring、必要 import"
     "（含 `from fde import FdeError`）、聚合根类 `class <类名>:` 及类 docstring、`_init_db(self)` "
     "幂等建表（字段严格按详设§4字段表）、以及**核心公共方法**（建单 / 查询 / 状态主干等）。"
     "⚠️ 缩进铁律：`class` 行顶格；类内方法定义行（`def _init_db`、`def create` 等）**恰好缩进 4 个空格**，"
     "方法体 8 空格，嵌套逐层 +4——全程只用空格、禁用 Tab，方法定义行绝不能顶格或缩进 8 空格。"
     "【到此为止】不要写收尾、不要闭合类、不要 ``` 围栏；剩余方法与外部适配器由下一段补充。"),
    ("code1", "`<应用>.py` 后半部分（其余公共方法 + 外部系统适配器）",
     "接续前半部分，【只】输出该类**剩余的公共方法**与**外部系统适配器方法**（`_` 前缀）。"
     "它们都属于同一个类：每个方法定义行 `def xxx(self, ...)` **恰好缩进 4 个空格**（与 `_init_db` 完全同级），"
     "方法体 8 空格、嵌套逐层 +4；**严禁**方法定义行顶格（0 空格）或缩进 8 空格，全程只用空格、禁 Tab；"
     "不要重复 import、不要再写 `class` 行、"
     "不要 ``` 围栏、不要重复 `_init_db` 或前半已给的核心方法。若确无剩余方法，只输出一行 "
     "`# （无更多方法）`。"),
    ("readme", "README.md（该应用 Agent 操作指南）",
     "本次【只】输出该应用的 `README.md`（写给该应用 Agent 的操作指南），**严格按 CONVENTION §11 "
     "规定的 README 章节结构**编写，内容依据下方《应用详设》的对外服务、业务规则与标准工作流。"
     "只输出 markdown 正文，不要 ``` 围栏。"),
]

# ── 第④步（测试用例生成）规格 ──────────────────────────
_TESTCASE_PREAMBLE = (
    "你是 FDE 平台的「测试用例生成」技能（应用组构建第④步），负责为**整个应用组**生成一份"
    "结构化测试用例（覆盖完整业务流程 + 自洽测试数据 + 异步回执模拟）。严格依照下方《应用测试.md》"
    "规格。铁律：\n"
    "- 每条用例四要素齐全：**步骤**（`<应用>.<服务>(参数)`）/ **测试数据** / **期望**（可机器校验）/ "
    "**回执模拟点**（仅涉异步外部系统的用例需要）；\n"
    "- 服务名 / 参数名以 `_contracts.md`（若有）或详设§4 功能清单为准，**不臆造**不存在的服务 / 参数；\n"
    "- **数据字典先冻结、后续只引用不新造**：标识贯穿全链一致，且符合各应用 BR（数量>0、必填、取值范围等）；\n"
    "- 覆盖：主数据 + 主业务链（异步外部系统处标**回执模拟成功路**）+ 分支 / 异常（撤回 / 驳回 / 超额阻止 / "
    "失败重试 / 幂等 / 状态非法转换，及外部系统**失败路**）；\n"
    "- 期望必须可机器校验（字段=值 / 进入某状态 / `抛 FdeError 含『关键词』`），不写「应该成功」这类模糊结论；\n"
    "- 出向适配器（如 `_send_e14`）默认走本地 stub，**无需**模拟；只需模拟**异步回执**（`on_*_result` 回写服务）；\n"
    "- 绝不臆造业务：架构 / 详设未说清的链路标『待确认』，不编造步骤或断言；\n"
    "- 只输出**结构化 Markdown 正文**（数据用 markdown 表格），不要用 ``` 围栏包裹整篇。\n"
)

# ── 第⑤步（测试执行）规格 ──────────────────────────────
_TESTEXEC_PREAMBLE = (
    "你是 FDE 平台的「测试执行」技能（应用组构建第⑤步），负责把**整个应用组**的《测试用例.md》"
    "翻译成一个**可直接运行**的集成测试脚本（`verify_chain_<组>.py`），经平台真实路由驱动应用组"
    "跑通主链与分支，并产出可 triage 的 PASS/FAIL 结果。严格依照下方《测试执行.md》规格。铁律：\n"
    "- 测试设计**只来自**《测试用例.md》，不凭架构 / 详设另起用例；\n"
    "- 每一步经 `platform.call` **真实路由**（含跨应用 self.fde.call、事务、状态机），**不** import 应用类直调；\n"
    "- 用例四要素逐一落地：步骤→`call(\"<应用>\",\"<服务>\",**参数)`；测试数据→脚本顶部常量"
    "（**单据号别名一律从对应 create 的返回值捕获再串联**，禁止硬编码单号）；期望→assert 字段 / 状态，"
    "错误分支用 `expect_err(fn,\"关键词\")`；回执模拟点→**主动调用回写服务**（`on_*_result` 等）模拟外部异步回执；\n"
    "- 入参名 / 必填项以给出的**应用代码实际签名**为准；用例与签名冲突时按签名校准（用例 §4『待确认』亦按实际报错校准）；\n"
    "- **参数纪律**：入参严格按用例给出的示例数据 + 签名取用，**不要自行添加用例未出现的可选参数**"
    "（如 `source` 等）；报错指出缺某字段时**直接补齐该字段**（值取自用例数据字典 / 字段表），"
    "**严禁**编写『多种入参形态轮询探测』之类的试探循环——那会互相掩盖真实错误；\n"
    "- **步骤标记**：每条用例首行 `step(\"<TC编号> <名称>\")`（打印 `→ <名称>`），便于失败定位与逐例记录；\n"
    "- **脚本骨架由平台生成**（隔离头部 / `step` · `expect_err` · `clean` · `record` 助手 / 三态结果哨兵 "
    "`VERIFY_RESULT: PASS | PARTIAL x/M | CRASH` / `__main__` 入口全部自动补齐；平台还对每条用例**自动包 "
    "try/except 软失败记录**——某例失败只记录原因、不阻断后续用例）：两段输出里都**不要**写任何 "
    "import / 助手函数 / def main / 结果哨兵 / `__main__` 入口，只写用例语句本身；\n"
    "- 只输出纯 Python 代码，不要 ``` 围栏、不要任何解释文字。\n"
)

# 第⑤步 harness：骨架（隔离头部 / 助手 / 三态哨兵 / __main__ 入口）为平台静态代码，模型只写
# 用例语句体（按 § 章节自适应分块逐批生成），平台按 step() 标记逐例包 try/except（软失败记录、不阻断）后拼装。
# 拼装产物符合 design/测试执行.md 的完整独立模板（可单独 python 运行）；分段规避整份大类撞网关
# 单请求推理上限（HTTP 504）。手工执行该规格时照模板写整份脚本，与本 harness 产物同构。

_SCRIPT_HEADER = '''"""verify_chain___GROUP__.py — __GROUP__ 应用组联通测试**编排器**（平台按 design/测试执行.md 自动生成）。

运行：python app/__GROUP__/tests/verify_chain___GROUP__.py（依次执行同目录各 verify_chain___GROUP___partN.py）。
初始化：clean() 清空本组各应用库的全部表（**保留库文件、只清数据**——规避 Windows 文件锁，平台开着也能跑）。
    ⚠️ 运行测试会**清空本组全部业务数据**（测试环境初始化语义）；config/ 下平台库（auth/llm/聊天记录等）不受影响。
外部系统：清各基址，出向适配器自动降级为本地 stub。
崩溃隔离：某 part 脚本级崩溃只记录该例、继续跑后续 part。
"""
import importlib
import os
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _project_root():
    """向上找项目根（含 fde_platform/ 的目录）——脚本落点深度不固定，按标记定位才稳。"""
    p = HERE
    while not (p / "fde_platform").is_dir():
        if p.parent == p:
            raise RuntimeError("无法定位项目根目录（未找到 fde_platform/）")
        p = p.parent
    return p


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# stub 模式：清 LLM 与外部系统基址，出向适配器自动降级为本地 stub
for _k in ("LLM_BASE_URL", "LLM_API_KEY", "SAP_BASE_URL", "MOM_BASE_URL",
           "WMS_BASE_URL", "MDM_BASE_URL", "APS_BASE_URL", "CTCT_BASE_URL"):
    os.environ.pop(_k, None)

GROUP = "__GROUP__"
APPS = __APPS__

from fde import FdeError  # noqa: E402
from fde_platform.runtime import FdePlatform  # noqa: E402

STEP = ""
STEP_RESULTS = []   # 逐例记录 [(步骤名, 是否通过, 备注)]


def step(name):
    global STEP
    STEP = name
    print(f"  → {name}", flush=True)


def record(ok, note=""):
    STEP_RESULTS.append((STEP, ok, note))


def expect_err(fn, substr):
    """错误分支断言：fn 应抛 FdeError 且消息含 substr。"""
    try:
        fn()
    except FdeError as e:
        assert substr in str(e), f"错误应含『{substr}』，实际: {e}"
        return str(e)
    raise AssertionError(f"应抛 FdeError(含『{substr}』)，但未抛出")


def clean():
    """测试初始化：清空本组各应用库的全部表（保留库文件、只清数据；不碰 config/ 平台库）。"""
    for dbf in (ROOT / "app" / GROUP).glob("*/*.db"):
        con = sqlite3.connect(str(dbf), timeout=15)
        try:
            tabs = [r[0] for r in con.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
            for t in tabs:
                con.execute(f'delete from "{t}"')
            con.commit()
        finally:
            con.close()


def main():
    clean()
    pf = FdePlatform()
    pf.load_all()
    for a in APPS:
        assert f"{GROUP}/{a}" in pf.app_names(), f"应用未加载: {GROUP}/{a}"

    def call(app, svc, **kw):
        return pf.call(f"{GROUP}/{app}", svc, **kw)
'''

# 编排器中段：按序执行各 part（__PARTS__ = [(模块名, 标签)]）；part 级脚本崩溃只记录、继续跑
# 后续 part（崩溃隔离；业务步的软失败由各 part 内逐例 try/except 记录，走不到这里）。
_ORCHESTRATOR_PARTS = '''
    _parts = __PARTS__
    sys.path.insert(0, str(HERE))   # 保证可从本目录 import 各 part（手工从他处 import 编排器时亦成立）
    for _name, _label in _parts:
        print(f"══ part: {_label} ({_name}) ══", flush=True)
        _mod = importlib.import_module(f"verify_chain_{GROUP}_{_name}")
        try:
            _mod.run_part(call, step, expect_err, record)
        except Exception as e:
            record(False, f"[{_label}] CRASH: {type(e).__name__}: {e}")
            print(f"  ✗ part {_label} 崩溃：{type(e).__name__}: {e}", flush=True)
'''

# part 模块头部：__GROUP__/__NAME__/__LABEL__ 占位；用例语句体经 _wrap_cases 逐例包 try/except
# 后缩进在 run_part 内（4 空格基线，与 call/step/expect_err/record 形参配合）。
_PART_HEADER = '''"""verify_chain___GROUP______NAME__.py — __LABEL__ 用例语句体。

平台自动生成（第⑤步测试执行）；由编排器 verify_chain___GROUP__.py 调用 run_part 执行，勿直接运行。
"""
from fde import FdeError   # noqa: E402（逐例软失败包装的 except FdeError 需要）


def run_part(call, step, expect_err, record):
'''

# 平台静态收尾：逐例结果表 + 三态哨兵（PASS / PARTIAL x/M / FAIL 0/M）+ __main__（脚本级崩溃 → CRASH）
_SCRIPT_CLOSER = '''
    clean()
    total = len(STEP_RESULTS)
    passed = sum(1 for _t, ok, _n in STEP_RESULTS if ok)
    print()
    for name, ok, note in STEP_RESULTS:
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else " | " + note))
    if total and passed == total:
        print(f"VERIFY_RESULT: PASS {total}/{total}")
    elif passed > 0:
        print(f"VERIFY_RESULT: PARTIAL {passed}/{total}")
    else:
        print(f"VERIFY_RESULT: FAIL 0/{total}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:   # 脚本级崩溃（非用例软失败）
        print(f"FAIL_STEP: {STEP}")
        print(f"CRASH: {type(e).__name__}: {e}")
        print("VERIFY_RESULT: CRASH")
        sys.exit(1)
'''

_SEC_HEAD = re.compile(r"^##\s*§?\s*(\d+)[.、]?\s*(.*)$", re.M)
_TC_BLOCK = re.compile(r"(?=^- \*\*TC-)", re.M)


def _split_testcase_sections(testcase_md: str) -> list:
    """按 `## §N …` 标题切节 → [(编号str, 标题, 含标题正文)]；无标题 → 整篇作 "all" 一节。"""
    matches = list(_SEC_HEAD.finditer(testcase_md))
    if not matches:
        return [("all", "全部用例", testcase_md)]
    secs = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(testcase_md)
        secs.append((m.group(1), (m.group(2) or "").strip() or f"§{m.group(1)}",
                     testcase_md[m.start():end]))
    return secs


def _chunk_section(label: str, body: str, max_chars: int) -> list:
    """单节按 TC 用例块边界切成 ≤max_chars 字符的生成块 → [(块标签, 块文本)]（不劈单条用例）。"""
    if len(body) <= max_chars:
        return [(label, body)]
    blocks = _TC_BLOCK.split(body)
    head_part = ""
    if blocks and not blocks[0].lstrip().startswith("- **TC-"):
        head_part, blocks = blocks[0], blocks[1:]
    chunks, cur, cur_len, n = [], head_part, len(head_part), 1
    for blk in blocks:
        if cur_len + len(blk) > max_chars and cur.strip():
            chunks.append((label if n == 1 else f"{label}-续{n}", cur))
            n += 1
            cur, cur_len = blk, len(blk)
        else:
            cur += blk
            cur_len += len(blk)
    if cur.strip():
        chunks.append((label if n == 1 else f"{label}-续{n}", cur))
    return chunks or [(label, body)]


def _plan_chunks(testcase_md: str, max_chars: int) -> list:
    """把《测试用例.md》切成生成块 [(标签, 文本)]：§0+§1 合并为主数据块，其余各节（§2 主链 /
    §3 分支…）各自按需再切；每块 ≤ max_chars。小组退化为 2~3 块，超大组自适应多块。"""
    secs = _split_testcase_sections(testcase_md)
    if len(secs) == 1 and secs[0][0] == "all":
        return _chunk_section("用例", secs[0][2], max_chars)
    by_no, order = {}, []
    for no, title, body in secs:
        if no not in by_no:
            order.append(no)
        by_no.setdefault(no, []).append((title, body))
    chunks = []
    md_bodies = [b for no in ("0", "1") for _t, b in by_no.get(no, [])]
    if md_bodies:
        have = [no for no in ("0", "1") if no in by_no]
        label = ("§0+§1 主数据" if len(have) == 2
                 else ("§1 主数据" if have[0] == "1" else "§0 数据字典"))
        chunks += _chunk_section(label, "\n\n".join(md_bodies), max_chars)
    for no in order:
        if no in ("0", "1"):
            continue
        title = by_no[no][0][0]
        if "待确认" in title:      # §4 待确认是备注非用例，不生成
            continue
        body = "\n\n".join(b for _t, b in by_no[no])
        chunks += _chunk_section(f"§{no} {title}"[:32], body, max_chars)
    return chunks


def _chunk_instr(label: str, idx: int, total: int) -> str:
    """单批用例的生成指令（各批共用；批次序号用于跨批变量复用约定）。"""
    return (f"本次【只】输出**本批用例（{label}，第 {idx}/{total} 批）**的语句体：将被平台放入已生成好的 "
        "main() 内（call / step / expect_err 助手与逐例 try/except 软失败记录均已备好，**严禁写**任何 "
        "import / 助手函数 / def main / 结果哨兵 / `__main__` 入口）。契约：\n"
        "- **顶格书写**（相对缩进从 0 起；平台统一沉入 main 并逐例包软失败记录）；\n"
        "- 每条用例**首行**必须是 `step(\"<TC编号> <名称>\")`；随后该用例语句：数据准备 / "
        "`call(\"<应用>\",\"<服务>\",**参数)` / 断言（`assert ...==...`；错误分支用 "
        "`expect_err(lambda: call(...),\"关键词\")`）；\n"
        "- **单据号变量命名固定**：fc_no / so_no / fo_no / dn_no / recon_no / cc_no / ro_no（对应用例别名 "
        "FC1/SO1/FO1/DN1/R1/CC1/RO1）；本批首次用到某单据时从其 create 返回值捕获（如 `so_no = "
        "call(\"sales_order\",\"create\",...)[\"so_no\"]`），**后续批次直接复用同名变量**（同一 main "
        "作用域，定义可不在本批文本中）；禁止硬编码单号；\n"
        "- **入参形态严格照『数据契约』（建表必填列）与用例数据示例**；不要自行添加用例未出现的可选参数"
        "（如 source 等），严禁编写多形态轮询探测循环；\n"
        "- 异步回执模拟点直接调用回写服务（如 `call(\"reconciliation\",\"on_settlement_result\",...)`）；"
        "依赖主链状态的分支若需自造数据，就地先造再验。")

# ── 状态 ────────────────────────────────────────────────

class GroupBuildState(TypedDict, total=False):
    task_id: int
    group: str              # 英文应用组名
    name_cn: str            # 中文应用组名
    business_text: str      # 来源②：随调用的长文本业务描述
    spec: str               # design/架构设计.md 规格全文
    brd_context: str        # 来源①：brd/ 各文件内容拼装
    outline_md: str         # ① 聚合根清单总表（含简短引言）
    app_names: list         # 从总表解析出的应用名（决定扇出与卡顺序）
    app_cards: dict             # {应用名: 聚合根卡 markdown}
    relations_md: str       # ③ 聚合关系图 + 关键设计决策 + 待确认
    architecture_md: str    # 拼装后的最终文档
    error: str


# 第②步（逐聚合根应用设计）状态
class DesignState(TypedDict, total=False):
    task_id: int
    group: str              # 英文应用组名
    name_cn: str            # 中文应用组名
    target_apps: list       # 指定聚合根子集（空=总表全部）
    spec: str               # design/应用设计.md 规格/模板全文
    arch_md: str            # app/<组>/architecture.md 全文
    brd_context: str        # 来源①：brd/ 各文件内容拼装
    business_text: str      # （第②步通常为空，仅复用 _business_block）
    app_names: list         # 本次要详设的聚合根应用名
    cards_map: dict         # {应用名: 聚合根卡 markdown}
    rows_map: dict          # {应用名: 总表行 dict(name_cn/cls/id)}
    shared_md: str          # 全组共享上下文（总表/关系图/设计决策/待确认）
    detail_docs: dict       # {应用名: 应用详设 markdown}
    failed_apps: list       # 生成失败/不完整的聚合根
    error: str


# 第③步（应用编码）状态
class CodeState(TypedDict, total=False):
    task_id: int
    group: str              # 英文应用组名
    name_cn: str            # 中文应用组名
    target_apps: list       # 指定聚合根子集（空=总表全部）
    convention: str         # design/CONVENTION.md 编码规范全文
    arch_shared: str        # architecture.md 共享上下文（总表 / 关系图 / 决策 / 待确认）
    app_names: list         # 本次要编码的聚合根应用名
    detail_map: dict        # {应用名: 应用详设.md 全文}（主输入）
    rows_map: dict          # {应用名: 总表行 dict(name_cn/cls/id)}
    code_map: dict          # {应用名: {"py": str, "readme": str}}（通过门禁的产出）
    failed_apps: list       # 生成失败 / 未过门禁的聚合根
    error: str


# 第④步（测试用例生成）状态
class TestCaseState(TypedDict, total=False):
    task_id: int
    group: str              # 英文应用组名
    name_cn: str            # 中文应用组名
    spec: str               # design/应用测试.md 规格全文
    arch_shared: str        # architecture.md 共享段（总表 / 关系图 / 决策 / 待确认，已去聚合根卡）
    contracts: str          # app/<组>/_contracts.md 全文（若有；服务签名以此为准）
    digests: dict           # {应用名: 详设测试相关摘要(BR / 状态机 / [功能] / 外部依赖)}
    master_apps: list       # 主数据应用（总表『是否主数据』）：数据字典段只投喂这些
    app_names: list         # 聚合根应用名清单
    testcase_md: str        # 拼装后的整组测试用例文档
    error: str


# 第⑤步（测试执行）状态
class TestExecState(TypedDict, total=False):
    task_id: int
    group: str              # 英文应用组名
    name_cn: str            # 中文应用组名
    spec: str               # design/测试执行.md 规格全文
    testcase_md: str        # app/<组>/测试用例.md 全文（唯一测试设计来源）
    arch_shared: str        # architecture.md 共享段（总表 / 关系图 / 决策 / 待确认）
    signatures: str         # 各应用公共方法签名校准摘要（ast 静态抽取，不 import 生成物）
    contracts_digest: str   # 各应用 _init_db 建表字段 / 必填列摘要（数据契约）
    dict_block: str         # §0 数据字典节原文（分块生成时共享恒带）
    apps: list              # 已编码应用名清单（写入脚本 APPS）
    script_set: dict        # 当前测试脚本集 {文件名: 内容}（编排器 + 各 part；修复轮之间更新）
    result: dict            # 运行结果 {verdict, counts, failed_step, steps, output_tail, iterations, history}
    error: str


# ⑧契约冻结状态
class ContractsState(TypedDict, total=False):
    task_id: int
    group: str              # 英文应用组名
    name_cn: str            # 中文应用组名
    apps: list              # 组内已编码应用（gather 预检）
    dump_output: str        # 沙箱 dump 运行输出尾部（失败排查用）
    error: str


# ⑨前端详设状态
class FdesignState(TypedDict, total=False):
    task_id: int
    group: str              # 英文应用组名
    name_cn: str            # 中文应用组名
    target_apps: list       # 指定应用子集（空=全部已详设应用）
    spec: str               # design/前端设计.md 规格全文
    convention: str         # VIEW_CONVENTION.md 正本全文
    pitfalls: str           # 前端踩坑清单（dashboard job 输入）
    contracts: str          # app/<组>/_contracts.md 全文（硬屏障）
    arch_md: str            # architecture.md 全文（软依赖，可空）
    shared_md: str          # 架构共享段（总表/关系图/决策/待确认；dashboard job 输入）
    rows_map: dict          # {应用名: 总表行 dict}
    menu_plan: dict         # {应用名/dashboard: {order, ic, crumb, form_hint}}（确定性分配）
    detail_map: dict        # {应用名: 应用详设.md 全文}（目标应用）
    fdesign_docs: dict      # {应用名: 前端详设.md}（通过门禁的产出）
    dashboard_doc: str      # 前端详设/dashboard.md
    failed_apps: list       # 生成失败/未过门禁的应用
    error: str


# ⑩前端编码状态
class FcodeState(TypedDict, total=False):
    task_id: int
    group: str              # 英文应用组名
    name_cn: str            # 中文应用组名
    target_apps: list       # 指定应用子集（空=全部已有前端详设的应用）
    spec: str               # design/前端编码.md 规格全文
    convention: str         # VIEW_CONVENTION.md 正本全文
    patterns: str           # view-convention/patterns.md 代码骨架全文
    pitfalls: str           # view-convention/pitfalls.md 踩坑清单全文
    contracts: str          # app/<组>/_contracts.md 全文（硬屏障 · 字段复核）
    dashboard_design: str   # app/<组>/前端详设/dashboard.md（dashboard 单元主输入）
    fdesign_map: dict       # {应用名: 前端详设.md 全文}（目标应用）
    js_map: dict            # {应用名: view.js}（通过门禁的产出）
    html_map: dict          # {应用名: view.html}
    dashboard_js: str       # view/<组>/dashboard.js
    dashboard_html: str     # view/<组>/dashboard.html
    failed_apps: list       # 生成失败/未过门禁的单元
    error: str


# ⑪前端测试用例状态
class FtestState(TypedDict, total=False):
    task_id: int
    group: str              # 英文应用组名
    name_cn: str
    target_apps: list       # 指定应用子集（空=全部已有前端详设的应用）
    spec: str               # design/前端测试.md 规格全文
    pitfalls: str           # view-convention/pitfalls.md 选择器规则
    contracts: str          # app/<组>/_contracts.md 全文（硬屏障 · 造数签名依据）
    dashboard_design: str   # app/<组>/前端详设/dashboard.md（组级单元主输入）
    menu_meta: str          # 各应用 §1 PAGE_META 摘录（组级单元菜单序断言依据）
    fdesign_map: dict       # {应用名: 前端详设.md 全文}（目标应用）
    ftest_docs: dict        # {应用名: 前端测试用例.md}（通过门禁的产出）
    group_doc: str          # 组级补充 app/<组>/前端测试用例.md
    failed_apps: list
    error: str


# ⑫前端测试执行状态
class FverifyState(TypedDict, total=False):
    task_id: int
    group: str              # 英文应用组名
    name_cn: str
    target_apps: list       # 指定应用子集（空=全部已有前端测试用例的应用）
    spec: str               # design/前端测试执行.md 规格全文
    paradigm: str           # design/前端验收样板/verify_view_e2e.py 范式全文（基建段照抄依据）
    pitfalls: str           # view-convention/pitfalls.md 选择器规则
    case_map: dict          # {应用名: 前端测试用例.md 全文}（目标应用）
    group_case: str         # 组级补充用例全文
    script_map: dict        # {单元名(应用 或 '_group'): 脚本内容}（通过门禁的产出）
    results: dict           # {单元名: {verdict, rounds, failed_step, output_tail}}
    failed_apps: list
    error: str


# ── LLM 辅助 ────────────────────────────────────────────

def _chat(system: str, user: str) -> str:
    """调 LLM 取正文；统一判错 + 剥围栏。失败抛 RuntimeError（→ 任务 failed）。"""
    _check_cancel()
    try:
        resp = llm.get_provider(LLM_ROLE).chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
    except llm.LLMInterrupted:
        raise TaskCancelled("任务已被用户终止（LLM 生成中断）")
    except Exception as e:
        raise RuntimeError(f"LLM 调用异常：{e}")
    content = (resp.get("content") or "").strip()
    if not content or content.startswith("LLM 调用失败") or "未配置 LLM" in content:
        raise RuntimeError(content or "大模型空输出")
    return _strip_fences(content)


def _business_block(state: GroupBuildState) -> str:
    """组装业务输入段（来源②文字 + 来源① brd），供各分段 user prompt 复用。"""
    parts = []
    bt = (state.get("business_text") or "").strip()
    if bt:
        parts.append("## 业务描述（来源②：随调用文字）\n" + bt)
    brd = (state.get("brd_context") or "").strip()
    if brd:
        parts.append("## 组级业务设计（来源①：brd/ 文件）\n" + brd)
    return "\n\n".join(parts)


def _read_brd(group: str) -> tuple:
    """读取 app/<组>/brd/ 下文件内容（文本截断、二进制登记），返回 (拼装上下文, 文件数)。"""
    brd_dir = APPS_DIR / group / "brd"
    parts, count = [], 0
    if brd_dir.is_dir():
        for f in sorted(p for p in brd_dir.rglob("*") if p.is_file() and not p.name.startswith(".")):
            count += 1
            rel = f.relative_to(brd_dir).as_posix()
            if f.suffix.lower() in _TEXT_SUFFIXES:
                try:
                    body = f.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    body = f"（读取失败：{e}）"
                if len(body) > _BRD_MAX_CHARS:
                    body = body[:_BRD_MAX_CHARS] + "\n…（内容过长，已截断）"
                parts.append(f"### 文件：{rel}\n\n{body}")
            else:
                parts.append(f"### 文件：{rel}\n\n（二进制文件，未读入内容）")
    return "\n\n---\n\n".join(parts), count


# ── 图节点 ──────────────────────────────────────────────

def node_gather(state: GroupBuildState) -> dict:
    """收集业务输入：规格 + brd/ 文件（来源①）+ 长文本（来源②）；输入完备性预检。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gather")
    groupbuild_store.append_log(task_id, "gather：读取技能规格与业务输入…")

    spec = DESIGN_SPEC.read_text(encoding="utf-8") if DESIGN_SPEC.is_file() else ""
    if not spec:
        raise RuntimeError("缺少技能规格文件：design/架构设计.md")

    brd_dir = APPS_DIR / group / "brd"
    parts, brd_count = [], 0
    if brd_dir.is_dir():
        for f in sorted(p for p in brd_dir.rglob("*") if p.is_file() and not p.name.startswith(".")):
            brd_count += 1
            rel = f.relative_to(brd_dir).as_posix()
            if f.suffix.lower() in _TEXT_SUFFIXES:
                try:
                    body = f.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    body = f"（读取失败：{e}）"
                if len(body) > _BRD_MAX_CHARS:
                    body = body[:_BRD_MAX_CHARS] + "\n…（内容过长，已截断）"
                parts.append(f"### 文件：{rel}\n\n{body}")
            else:
                parts.append(f"### 文件：{rel}\n\n（二进制文件，未读入内容；如需分析请转写为文本后重新上传）")
    brd_context = "\n\n---\n\n".join(parts)
    business_text = (state.get("business_text") or "").strip()

    if not brd_context.strip() and not business_text:
        raise RuntimeError("无业务输入：brd/ 为空且未填写业务描述。请上传 BRD 文件或填写业务描述后重试。")

    name_cn = state.get("name_cn") or ""
    if not name_cn:
        g = groupbuild_store.get_group(group)
        name_cn = (g or {}).get("name_cn", "") if g else ""

    groupbuild_store.append_log(
        task_id, f"gather 完成：规格 {len(spec)} 字；BRD 文件 {brd_count} 份；"
                 f"业务描述 {'有' if business_text else '无'}。")
    return {"spec": spec, "brd_context": brd_context, "name_cn": name_cn}


def node_outline(state: GroupBuildState) -> dict:
    """① 生成聚合根清单总表，并解析出应用名清单（决定后续扇出与卡顺序）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="outline")
    groupbuild_store.append_log(task_id, "outline：识别聚合根、生成清单总表…")

    system = (_ROLE_PREAMBLE +
              "本次【只】产出输出结构①『聚合根清单总表』：一张 markdown 表格，"
              "列依次为：# / 聚合根 / 应用名 / 类名 / 一句话定义 / 标识 / 是否主数据。"
              "可在表格前加一行简短引言。不要输出聚合根卡，不要输出关系图。\n\n"
              "===== 技能规格（design/架构设计.md）=====\n" + (state.get("spec") or ""))
    user = (f"应用组英文名：<组> = {group}\n"
            + (f"应用组中文名：{state.get('name_cn')}\n" if state.get("name_cn") else "")
            + "\n" + _business_block(state)
            + f"\n\n请为应用组 `{group}` 产出聚合根清单总表。")

    outline_md = _chat(system, user)
    app_names = _table_app_names(outline_md)
    if not app_names:
        raise RuntimeError("总表未解析到任何应用名（输出格式异常），无法继续逐卡生成。")
    groupbuild_store.append_log(
        task_id, f"outline 完成：识别到 {len(app_names)} 个聚合根 → {', '.join(app_names)}")
    return {"outline_md": outline_md, "app_names": app_names}


def node_cards(state: GroupBuildState) -> dict:
    """② 逐聚合根生成卡（有界并发），各卡只输出自己那一张。"""
    task_id, group = state["task_id"], state["group"]
    app_names = state.get("app_names") or []
    groupbuild_store.update_task(task_id, current_step="cards")
    groupbuild_store.append_log(
        task_id, f"cards：逐个生成 {len(app_names)} 张聚合根卡【并发≤{_CARDS_PARALLEL}】…")

    outline = state.get("outline_md") or ""
    biz = _business_block(state)

    def gen(name: str):
        system = (_ROLE_PREAMBLE +
                  "本次【只】为指定的一个聚合根产出一张完整的『聚合根卡』，包含："
                  "标识（主键）、核心属性、对外操作（将成公共方法）、关键不变量（界定一致性边界，2–5 条）、"
                  "引用的聚合（by ID）、跨应用调用（self.fde.call）、状态机（如有）。\n"
                  "【关键不变量铁律】只写**解释『为何这些实体必须同聚合/同事务』的少数边界约束**（2–5 条）；"
                  "**严禁**罗列字段级校验规则（如『金额>0』『比例必填』『名称非空』）——那些属于第二步详设的业务规则（BR）。\n"
                  "【格式铁律】卡片主标题用三级标题 `### 聚合根：xxx`；卡内各小节（核心属性/对外操作/关键不变量/"
                  "引用的聚合/跨应用调用/状态机 等）一律用四级标题 `####`；更细的分组（如抬头属性/行项目属性）"
                  "用五级标题 `#####` 或加粗文本。**严禁在卡内使用 `#` 或 `##`**（那会与文档顶层 ①②③ 冲突）。"
                  "只输出这一张卡的 markdown，不要总表、不要关系图、不要其它聚合根。\n\n"
                  "===== 技能规格（design/架构设计.md）=====\n" + (state.get("spec") or ""))
        user = (f"应用组：{group}（{state.get('name_cn') or ''}）\n"
                f"本次要写的聚合根（应用名）：`{name}`\n\n"
                f"## 全组聚合根清单总表（供你确定引用 / 跨应用调用对象）\n{outline}\n\n"
                f"{biz}\n\n请只输出聚合根 `{name}` 的这一张卡。")
        try:
            return name, _chat(system, user)
        except Exception as e:              # 并发内异常收集，统一报错
            return name, f"__ERR__{e}"

    cards = {}
    failed = []
    workers = max(1, min(len(app_names), _CARDS_PARALLEL))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for name, md in ex.map(gen, app_names):
            if md.startswith("__ERR__"):
                failed.append(name)
                groupbuild_store.append_log(task_id, f"cards `{name}` 生成失败：{md[7:][:200]}")
                continue
            cards[name] = md
    if failed:
        raise RuntimeError(f"以下聚合根卡生成失败：{', '.join(failed)}")
    groupbuild_store.append_log(task_id, f"cards 完成：{len(cards)} 张聚合根卡。")
    return {"app_cards": cards}


def node_relations(state: GroupBuildState) -> dict:
    """③ 生成聚合关系图（mermaid）+ 关键设计决策 + 待确认清单。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="relations")
    groupbuild_store.append_log(task_id, "relations：生成聚合关系图与设计决策…")

    outline = state.get("outline_md") or ""
    cards = state.get("app_cards") or {}
    cards_digest = "\n\n".join(f"#### {n}\n{cards[n]}" for n in (state.get("app_names") or []) if n in cards)
    system = (_ROLE_PREAMBLE +
              "本次【只】产出输出结构③『聚合关系图』及其后内容：\n"
              "1) 一张 mermaid 关系图——标注聚合间的 by ID 弱引用（虚线）与 self.fde.call 跨应用调用（粗实线），"
              "外部系统（SAP/MOM/WMS 等）画出但不建聚合；\n"
              "2) 『关键设计决策』清单（含有争议或需业务确认的拆分/合并取舍）；\n"
              "3) 『待确认』清单。只输出这些段，不要总表、不要聚合根卡。\n\n"
              "===== 技能规格（design/架构设计.md）=====\n" + (state.get("spec") or ""))
    user = (f"应用组：{group}（{state.get('name_cn') or ''}）\n\n"
            f"## 聚合根清单总表\n{outline}\n\n"
            f"## 各聚合根卡（要点参照）\n{cards_digest}\n\n"
            f"{_business_block(state)}\n\n请产出聚合关系图 + 关键设计决策 + 待确认。")
    relations_md = _chat(system, user)
    groupbuild_store.append_log(task_id, f"relations 完成（{len(relations_md)} 字）。")
    return {"relations_md": relations_md}


def node_assemble(state: GroupBuildState) -> dict:
    """按规格顺序拼装最终文档并做完整性闸门（缺卡/缺图则失败、不落盘）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="assemble")
    app_names = state.get("app_names") or []
    cards = state.get("app_cards") or {}
    missing_cards = [n for n in app_names if n not in cards]
    if missing_cards:
        raise RuntimeError(f"缺少聚合根卡：{', '.join(missing_cards)}")

    title_cn = f"（{state['name_cn']}）" if state.get("name_cn") else ""
    sections = [
        f"# 应用组 `{group}` 聚合根架构设计{title_cn}",
        "> 产出技能：`fde-aggregate-identification`（唯一产出文件 "
        f"`app/{group}/architecture.md`）。\n"
        "> 方法：按**一致性边界**识别聚合根——一个聚合根 = 一个 FDE 应用"
        "（同名文件夹 / 类 / 库 / 事务边界）。",
        "## ① 聚合根清单总表\n" + (state.get("outline_md") or "").strip(),
        "## ② 聚合根卡\n" + "\n\n---\n\n".join(_normalize_card(cards[n].strip()) for n in app_names),
        "## ③ 聚合关系图\n" + _strip_dup_relation_heading(state.get("relations_md") or ""),
    ]
    doc = "\n\n".join(sections).strip() + "\n"

    missing = _check_completeness(doc)
    if missing:
        raise RuntimeError("拼装后完整性校验未通过，不落盘。缺失：" + "、".join(missing))
    groupbuild_store.append_log(task_id, f"assemble 完成（{len(doc)} 字，完整性校验通过）。")
    return {"architecture_md": doc}


def node_write(state: GroupBuildState) -> dict:
    """落盘 app/<组>/architecture.md（固定唯一产出）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="write")
    doc = state.get("architecture_md") or ""
    if not doc.strip():
        raise RuntimeError("无可写内容：assemble 未产出正文")
    out_dir = APPS_DIR / group
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "architecture.md").write_text(doc, encoding="utf-8")
    groupbuild_store.append_log(task_id, f"write 完成 → app/{group}/architecture.md（{len(doc)} 字）。")
    return {}


# ── 第②步图节点（逐聚合根应用设计）─────────────────────

def node_gather_design(state: DesignState) -> dict:
    """收集第②步输入：应用设计.md 模板 + architecture.md（解析总表/卡/共享段）+ brd/。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gather")
    groupbuild_store.append_log(task_id, "gather：读取应用设计模板与架构产出…")

    spec = DESIGN_SPEC_DETAIL.read_text(encoding="utf-8") if DESIGN_SPEC_DETAIL.is_file() else ""
    if not spec:
        raise RuntimeError("缺少技能规格文件：design/应用设计.md")

    arch_path = APPS_DIR / group / "architecture.md"
    if not arch_path.is_file():
        raise RuntimeError(f"缺少 app/{group}/architecture.md，请先运行『生成架构』（第①步）。")
    arch_md = arch_path.read_text(encoding="utf-8")

    rows = _table_rows(arch_md)
    all_apps = [r["app"] for r in rows]
    if not all_apps:
        raise RuntimeError("architecture.md 总表未解析到任何聚合根，无法做应用详设。")
    target = state.get("target_apps") or []
    apps = [a for a in all_apps if a in target] if target else all_apps
    if target and not apps:
        raise RuntimeError(f"指定的聚合根均不在总表中：{', '.join(target)}")

    cards_map = _split_arch_cards(arch_md, apps)
    no_card = [a for a in apps if a not in cards_map]
    if no_card:
        groupbuild_store.append_log(
            task_id, f"提示：以下聚合根未切出独立卡，将依据总表行设计：{', '.join(no_card)}")

    brd_context, brd_count = _read_brd(group)
    name_cn = state.get("name_cn") or ""
    if not name_cn:
        g = groupbuild_store.get_group(group)
        name_cn = (g or {}).get("name_cn", "") if g else ""

    groupbuild_store.append_log(
        task_id, f"gather 完成：模板 {len(spec)} 字；聚合根 {len(apps)} 个 → {', '.join(apps)}；BRD {brd_count} 份。")
    return {"spec": spec, "arch_md": arch_md, "app_names": apps,
            "cards_map": cards_map, "rows_map": {r["app"]: r for r in rows},
            "shared_md": _build_shared(arch_md), "brd_context": brd_context, "name_cn": name_cn}


def _assemble_detail(group, app, cn, cls, idk, sections) -> str:
    head = (f"# 应用详设 · `{group}` / `{app}`（{cn}）\n\n"
            f"> 产出技能：逐聚合根应用设计（第②步，规格 `design/应用设计.md`）。\n"
            f"> 输入：`app/{group}/architecture.md` + `app/{group}/brd/`。类名 `{cls}`，标识 `{idk}`。\n"
            f"> 本文件为该聚合根（应用）的《用户需求规格说明书》；US/BR/FUNC/PERM 编号按本文件独立递增。\n")
    return head + "\n\n" + "\n\n".join(s.strip() for s in sections) + "\n"


def _check_detail_complete(doc: str) -> list:
    """单份详设完整性闸门：须含 7 部分关键词 + 四类 ID 前缀（空=合格）。"""
    missing = [p for p in _DETAIL_PARTS if p not in doc]
    for pre in ("US-", "BR-", "FUNC-", "PERM-"):
        if pre not in doc:
            missing.append(pre.rstrip("-") + "编号")
    return missing


def node_design_apps(state: DesignState) -> dict:
    """逐聚合根、分段（×4）生成《应用详设》。

    把「N 应用 × 4 段」共 4N 次 LLM 调用**全部摊平成相互独立的任务**，用一个有界线程池
    统一调度（并发跨应用、跨段同时铺开，上限 _DETAIL_PARALLEL）——取代旧实现「应用级并发
    ≤3、每应用内 4 段串行」。旧结构任一时刻最多 3 个 LLM 调用在跑；摊平后始终把在途调用
    顶到上限，吞吐显著提升（prompt / 拼装 / 完整性闸门逻辑均不变）。各份详设独立拼装 + 校验。
    """
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="design")
    apps = state.get("app_names") or []
    cards_map = state.get("cards_map") or {}
    rows_map = state.get("rows_map") or {}
    spec = state.get("spec") or ""
    shared = state.get("shared_md") or ""
    groupbuild_store.append_log(
        task_id, f"design：{len(apps)} 份应用详设 ×4 段 = {len(apps) * 4} 次 LLM 调用，"
                 f"摊平并发≤{_DETAIL_PARALLEL}…")

    # 主线程序列化预构造每个 (应用, 段) 的 prompt（便宜、无并发风险）
    jobs = []    # (app, sec_idx, system, user)
    meta = {}    # app -> (cn, cls, idk)
    for app in apps:
        row = rows_map.get(app, {})
        cn, cls, idk = row.get("name_cn", app), row.get("cls", ""), row.get("id", "")
        meta[app] = (cn, cls, idk)
        card = cards_map.get(app) or (
            f"（未切出独立卡，请依据总表行与全组上下文设计）\n应用名 {app} / 类名 {cls} / 标识 {idk} / 中文名 {cn}")
        for sec_idx, (_key, label, instr) in enumerate(_DETAIL_SECTIONS):
            system = (_DETAIL_PREAMBLE + "【本次任务】" + instr +
                      "\n\n===== 技能规格 / 模板（design/应用设计.md）=====\n" + spec)
            user = (f"应用组：{group}（{state.get('name_cn') or ''}）\n"
                    f"本次要设计的聚合根：应用名 `{app}` / 类名 `{cls}` / 标识 `{idk}` / 中文名 {cn}\n\n"
                    f"## 该聚合根卡（来自 architecture.md）\n{card}\n\n"
                    f"## 全组共享上下文（总表 / 关系图 / 设计决策 / 待确认）\n{shared}\n\n"
                    f"{_business_block(state)}\n\n"
                    f"请只输出{label}的 markdown。")
            jobs.append((app, sec_idx, system, user))

    def run_job(job):
        app, sec_idx, system, user = job
        try:
            return app, sec_idx, _chat(system, user), None
        except Exception as e:              # 并发内异常收集，统一报错
            return app, sec_idx, None, str(e)

    sec_map, errs = {}, {}   # {app: {sec_idx: 正文}} / {app: [错误...]}
    workers = max(1, min(len(jobs), _DETAIL_PARALLEL))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for app, sec_idx, text, err in ex.map(run_job, jobs):
            if err is not None:
                errs.setdefault(app, []).append(
                    f"第{sec_idx + 1}段生成异常：{err}")
            else:
                sec_map.setdefault(app, {})[sec_idx] = text

    # 逐应用按段序拼装 + 完整性闸门（段缺失/异常/校验不过 → 该份失败，其余不受影响）
    detail_docs, failed = {}, []
    for app in apps:
        cn, cls, idk = meta[app]
        secs = sec_map.get(app, {})
        miss_sec = [label for i, (_k, label, _x) in enumerate(_DETAIL_SECTIONS)
                    if i not in secs]
        app_errs = errs.get(app, [])
        if app_errs or miss_sec:
            failed.append(app)
            why = "；".join(app_errs + [f"缺失：{m}" for m in miss_sec])
            groupbuild_store.append_log(task_id, f"design `{app}` 未通过：{why[:300]}")
            continue
        doc = _assemble_detail(group, app, cn, cls, idk,
                               [secs[i] for i in range(len(_DETAIL_SECTIONS))])
        miss = _check_detail_complete(doc)
        if miss:
            failed.append(app)
            groupbuild_store.append_log(task_id, f"design `{app}` 未通过：{'、'.join(miss)}")
        else:
            detail_docs[app] = doc

    if failed and not detail_docs:
        raise RuntimeError(f"全部聚合根详设生成失败：{', '.join(failed)}")
    msg = f"design 完成：{len(detail_docs)} 份应用详设"
    if failed:
        msg += f"；失败 {len(failed)} 个（跳过）：{', '.join(failed)}"
    groupbuild_store.append_log(task_id, msg)
    return {"detail_docs": detail_docs, "failed_apps": failed}


def node_write_design(state: DesignState) -> dict:
    """逐聚合根落盘 app/<组>/<应用名>/应用详设.md（同名应用文件夹）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="write")
    detail_docs = state.get("detail_docs") or {}
    if not detail_docs:
        raise RuntimeError("无可写内容：design 未产出任何详设")
    written = []
    for app, doc in detail_docs.items():
        d = APPS_DIR / group / app
        d.mkdir(parents=True, exist_ok=True)
        (d / "应用详设.md").write_text(doc, encoding="utf-8")
        written.append(app)
    groupbuild_store.append_log(
        task_id, f"write 完成：{len(written)} 份 → app/{group}/<应用名>/应用详设.md（{', '.join(written)}）")
    return {}


# ── 第③步图节点（应用编码）─────────────────────────────

def node_gather_code(state: CodeState) -> dict:
    """收集第③步输入：CONVENTION.md（编码规范）+ architecture.md（跨应用上下文）
    + 每个目标聚合根的 应用详设.md（主输入，缺失即失败 → 提示先跑第②步）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gather")
    groupbuild_store.append_log(task_id, "gather：读取编码规范（CONVENTION.md）与架构 / 详设产出…")

    convention = CODING_SPEC.read_text(encoding="utf-8") if CODING_SPEC.is_file() else ""
    if not convention:
        raise RuntimeError("缺少编码规范文件：design/CONVENTION.md")

    arch_path = APPS_DIR / group / "architecture.md"
    if not arch_path.is_file():
        raise RuntimeError(f"缺少 app/{group}/architecture.md，请先运行『生成架构』（第①步）。")
    arch_md = arch_path.read_text(encoding="utf-8")

    rows = _table_rows(arch_md)
    all_apps = [r["app"] for r in rows]
    if not all_apps:
        raise RuntimeError("architecture.md 总表未解析到任何聚合根，无法编码。")
    target = state.get("target_apps") or []
    apps = [a for a in all_apps if a in target] if target else all_apps
    if target and not apps:
        raise RuntimeError(f"指定的聚合根均不在总表中：{', '.join(target)}")

    # 主输入：每个聚合根的 应用详设.md（第②步产出）；缺失即停下，不臆造
    detail_map, missing = {}, []
    for app in apps:
        p = APPS_DIR / group / app / "应用详设.md"
        if p.is_file():
            detail_map[app] = p.read_text(encoding="utf-8")
        else:
            missing.append(app)
    if missing:
        raise RuntimeError(
            f"以下聚合根缺少 应用详设.md，请先运行『生成应用详设』（第②步）：{', '.join(missing)}")

    name_cn = state.get("name_cn") or ""
    if not name_cn:
        g = groupbuild_store.get_group(group)
        name_cn = (g or {}).get("name_cn", "") if g else ""

    groupbuild_store.append_log(
        task_id, f"gather 完成：规范 {len(convention)} 字；聚合根 {len(apps)} 个 → "
                 f"{', '.join(apps)}；详设 {len(detail_map)} 份。")
    return {"convention": convention, "arch_shared": _build_shared(arch_md),
            "app_names": apps, "detail_map": detail_map,
            "rows_map": {r["app"]: r for r in rows}, "name_cn": name_cn}


def _strip_code_fences(text: str) -> str:
    """剥掉模型偶发包在段外的 ``` / ```python 围栏与首尾空行。

    **保留各行原有缩进**（不用整段 .strip()，否则会剥掉代码段首行的类体缩进，
    导致 code0/code1 拼接后缩进不一致而 IndentationError）。"""
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _normalize_code_text(text: str) -> str:
    """归一代码段空白：Tab→4 空格、行首全角空格（U+3000）→4 空格、空白行→空行、
    去行尾空白与 BOM / 混入的 \\r。只动缩进 / 空白，不改任何代码内容。"""
    if text.startswith("﻿"):
        text = text[1:]
    out = []
    for ln in text.split("\n"):
        ln = ln.replace("\r", "")
        lead = ln[: len(ln) - len(ln.lstrip())]
        if "\t" in lead or "　" in lead:
            ln = lead.replace("\t", "    ").replace("　", "    ") + ln.lstrip()
        out.append(ln.rstrip())
    while out and not out[0]:
        out.pop(0)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


_CLASS_LINE = re.compile(r"^\s*class\s+\w+")
_DEF_LINE = re.compile(r"^\s*(?:async\s+)?def\s")


def _fix_class_indent(text: str) -> str:
    """修复模型最常见的类体缩进错位：把 `class` 行之后的方法定义行对齐到 4 空格。

    取各 `def` 行缩进宽度的**众数**为模型实际的成员层级 M：
    - M == 4：把个别顶格（< 4）的杂散 `def` 行补回 4（方法体相对缩进不动）；
    - M != 4：整段被模型系统性平移（如全体 8 空格）→ `class` 行之后各行统一位移
      (4 - M) 空格（class / import 等顶格行钳制在 0，方法内部相对缩进保持）。
    众数本身不一致（同段混用多级）时本函数可能修不净，由静态门禁 + 重生成重试兜底。"""
    lines = text.split("\n")
    cls_at = next((i for i, ln in enumerate(lines) if _CLASS_LINE.match(ln)), None)
    start = (cls_at + 1) if cls_at is not None else 0
    defs = [(i, len(ln) - len(ln.lstrip())) for i, ln in enumerate(lines)
            if i >= start and _DEF_LINE.match(ln)]
    if not defs:
        return text
    counts = {}
    for _i, w in defs:
        counts[w] = counts.get(w, 0) + 1
    # 众数为成员层级 M；同票取更接近 4（约定缩进）者——类内 def 顶格绝不正确，优先信 4。
    m = max(counts, key=lambda w: (counts[w], -abs(w - 4)))
    if m == 4:
        for i, w in defs:
            if w < 4:
                lines[i] = "    " + lines[i].lstrip()
    else:
        shift = 4 - m
        for i in range(start, len(lines)):
            ln = lines[i]
            if not ln.strip():
                continue
            w = len(ln) - len(ln.lstrip())
            lines[i] = " " * max(0, w + shift) + ln.lstrip()
    return "\n".join(lines)


def _seal_open_block(code: str) -> str:
    """code0 若恰以 `:` 结尾（模型停在块开口处）→ 补一行深一层缩进的 `pass`，
    使 code1 续接时不产生悬空反缩进。注释行结尾不触发。"""
    last = next((ln for ln in reversed(code.split("\n")) if ln.strip()), None)
    if last is None:
        return code
    s = last.strip()
    if s.startswith("#") or not s.endswith(":"):
        return code
    w = len(last) - len(last.lstrip())
    return code + "\n" + " " * (w + 4) + "pass"


def _process_code_part(part: str) -> str:
    """单个代码段的完整处理链：剥围栏 → 空白归一 → 类体缩进修复。"""
    return _fix_class_indent(_normalize_code_text(_strip_code_fences(part)))


def _join_code(part0: str, part1: str) -> str:
    """拼装两段代码为整份 <应用>.py：前半（文件头+类+建表+核心方法）+ 后半（其余方法）。
    各段先经 _process_code_part 归一并修复缩进；后半若为『无更多方法』占位则丢弃。"""
    a = _seal_open_block(_process_code_part(part0))
    b = _process_code_part(part1)
    if "无更多方法" in b:
        b = ""
    if not b.strip():
        result = a + "\n"
    else:
        result = a + "\n\n" + b.rstrip() + "\n"
    # 去重：检测重复的方法定义，删除第二次出现的完整方法
    result = _dedup_methods(result)
    return result


def _dedup_methods(py_text: str) -> str:
    """移除文件中重复的方法定义（保留首次出现，删除后续同名方法）。
    修复了 LLM 在两段生成中输出重复方法的常见问题。"""
    import re as _re_dedup
    method_re = _re_dedup.compile(r'^(\s{4}def )(\w+)(\(self)', _re_dedup.MULTILINE)
    seen = set()
    lines = py_text.split('\n')
    to_remove = {}   # method_name -> (start_line, end_line)
    # 找到所有方法定义位置
    method_starts = {}  # line_idx -> method_name
    for i, line in enumerate(lines):
        m = method_re.match(line)
        if m:
            name = m.group(2)
            if name in seen:
                to_remove[name] = i
            else:
                seen.add(name)
            method_starts[i] = name
    if not to_remove:
        return py_text
    # 删除重复方法：找到它们的起止行
    sorted_methods = sorted([(idx, name) for name, idx in to_remove.items()], key=lambda x: x[0])
    sorted_all = sorted([(idx, name) for idx, name in method_starts.items()], key=lambda x: x[0])
    # 为每个重复方法找到结束行（下一个方法定义前一行，或文件末尾）
    remove_ranges = []
    for dup_idx, dup_name in sorted_methods:
        # 找到下一个方法定义的位置
        end_idx = len(lines) - 1
        for mi, mn in sorted_all:
            if mi > dup_idx:
                end_idx = mi - 1
                break
        # 向上回溯去除空行
        while end_idx > dup_idx and lines[end_idx].strip() == '':
            end_idx -= 1
        remove_ranges.append((dup_idx, end_idx))
    # 从后往前删除（避免索引偏移）
    result_lines = list(lines)
    for start, end in reversed(remove_ranges):
        del result_lines[start:end + 1]
    return '\n'.join(result_lines) + ('\n' if py_text.endswith('\n') else '')


def _syntax_err(py_text: str):
    """返回 ast.parse 的首个 SyntaxError（可解析 → None）。供门禁修复判定。"""
    try:
        ast.parse(py_text)
        return None
    except SyntaxError as e:
        return e


def _locate_bad_slot(err_lineno: int, res: dict) -> tuple:
    """按出错行号把语法错定位到 code0 / code1，返回 (槽位, 段内行号)。

    code1 在拼接文件中自 code0 处理后行数 +2 行起（中间隔一空行）。"""
    a_n = len(_seal_open_block(_process_code_part(res["code0"])).split("\n"))
    if err_lineno <= a_n:
        return "code0", err_lineno
    return "code1", max(1, err_lineno - (a_n + 1))


def _err_context(py_text: str, lineno: int, span: int = 2) -> str:
    """出错行 ±span 行上下文（repr 显示缩进，ASCII 安全，可回喂模型 / 写任务日志）。"""
    lines = py_text.split("\n")
    lo, hi = max(1, lineno - span), min(len(lines), lineno + span)
    return "\n".join(f"{i:5}| {lines[i - 1]!r}" for i in range(lo, hi + 1))


def _to_halfwidth(c: str) -> str:
    """单个全角标点 → 半角等价（仅用于代码位置；字符串 / 注释内不调用本函数）。"""
    o = ord(c)
    if 0xFF01 <= o <= 0xFF5E:        # 全角 ASCII 块 ！..～ → 半角 !..~（含 ，；：（）｛｝＝．）
        return chr(o - 0xFEE0)
    return {0x3001: ",", 0x3002: ".", 0x3010: "[", 0x3011: "]",   # 、。【】
            0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'}.get(o, c)  # 弯引号


def _fix_fullwidth_in_code(src: str) -> str:
    """把**代码位置**（字符串字面量与注释之外）的全角标点转半角，消除 `invalid character` 语法错。

    字符串内（如 FdeError 中文消息）与注释中的全角标点**原样保留**。用字符状态机跟踪
    单 / 三引号字符串（含 r/f/b/u 前缀与反斜杠转义）与 # 注释；对截断 / 畸形输入容错（不抛异常）。
    已知局限：f-string 替换字段 `{...}` 内的全角标点按字符串内容保留（极少见，未深入解析）。"""
    res = []
    i, n = 0, len(src)
    in_str = None       # 当前字符串引号字符（' 或 "）；None=代码位置
    triple = False
    while i < n:
        c = src[i]
        if in_str is None:
            # —— 代码位置 ——
            if c == "#" or c == "＃":       # 注释（含全角＃）：# 及整行原样保留
                j = src.find("\n", i)
                end = j if j != -1 else n
                res.append("#" + src[i + 1:end])
                if j == -1:
                    i = n
                    break
                i = j
                continue
            if c in "\"'":
                if src[i:i + 3] == c * 3:        # 三引号字符串
                    in_str, triple = c, True
                    res.append(c * 3); i += 3
                else:
                    in_str, triple = c, False
                    res.append(c); i += 1
                continue
            if c in "rRfFbBuU":                  # 字符串前缀（f" / r" / rb" 等）
                k = i
                while k < n and src[k] in "rRfFbBuU" and k - i < 2:
                    k += 1
                if k < n and src[k] in "\"'":
                    res.append(src[i:k]); i = k  # 输出前缀，下轮处理引号
                    continue
            res.append(_to_halfwidth(c)); i += 1
        else:
            # —— 字符串内：原样保留，仅定位结束引号 ——
            if triple:
                if src[i:i + 3] == in_str * 3:
                    res.append(in_str * 3); i += 3; in_str = None; triple = False
                elif c == "\\":
                    res.append(src[i:i + 2]); i += 2
                else:
                    res.append(c); i += 1
            else:
                if c == "\\":
                    res.append(src[i:i + 2]); i += 2
                elif c == in_str:
                    res.append(c); i += 1; in_str = None
                else:
                    res.append(c); i += 1
    return "".join(res)


def _verify_code(app: str, cls: str, py_text: str) -> list:
    """静态门禁（进程内，不 import 生成物）：返回问题清单（空=通过）。

    检查项（对应 CONVENTION §13 验收清单 + §12.1）：
    1. 语法可解析（ast.parse）；
    2. 含 `from fde import FdeError` / `class <类名>` / `def _init_db` / `CREATE TABLE IF NOT EXISTS`；
    3. 未定义 `__init__`（ctx/db/fde 由平台注入）；
    4. 公共方法（不以 _ 开头）无返回类型注解（§12.1 内省陷阱）。
    """
    try:
        tree = ast.parse(py_text)
    except SyntaxError as e:
        return [f"语法错误：{e.msg}（行 {e.lineno}）"]
    problems = []
    if "from fde import FdeError" not in py_text:
        problems.append("缺 `from fde import FdeError`")
    if not re.search(rf"^class\s+{re.escape(cls)}\b", py_text, re.M):
        problems.append(f"缺聚合根类 `class {cls}`")
    if "def _init_db" not in py_text:
        problems.append("缺 `_init_db`")
    if "CREATE TABLE IF NOT EXISTS" not in py_text.upper():
        problems.append("缺 `CREATE TABLE IF NOT EXISTS`")
    # SQL 安全检查：禁止 f-string 拼接 SQL（须用参数化 ? 占位符）
    import re as _re_sql
    if _re_sql.search(r"[fF][\"']\s*(SELECT|INSERT|UPDATE|DELETE|CREATE)\b", py_text):
        problems.append("禁止 f-string 拼接 SQL（须用参数化 ? 占位符，防 SQL 注入）")

    cls_node = next((n for n in tree.body
                     if isinstance(n, ast.ClassDef) and n.name == cls), None)
    if cls_node is None:
        if not any(p.startswith("缺聚合根类") for p in problems):
            problems.append(f"未找到类 {cls} 定义")
    else:
        # 方法去重检查：检测类内重复方法定义
        seen_methods = set()
        for n in cls_node.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if n.name == "__init__":
                problems.append("禁止定义 `__init__`（ctx/db/fde 由平台注入）")
            elif not n.name.startswith("_") and n.returns is not None:
                problems.append(f"公共方法 `{n.name}` 禁写返回类型注解（§12.1）")
            if n.name in seen_methods:
                problems.append(f"重复方法定义 `{n.name}`（类内不可有同名方法）")
            seen_methods.add(n.name)
    return problems


def node_code_apps(state: CodeState) -> dict:
    """逐聚合根、分段（2 段代码 + 1 README）生成应用代码，摊平并发；各份独立静态门禁 + 自动修复。

    把「N 应用 ×（code0 + code1 + readme）」共 3N 次 LLM 调用全部摊平成独立任务，用一个
    有界线程池统一调度（并发上限 _CODE_PARALLEL，同第②步）。两段代码经 _join_code 归一 /
    修复缩进后过 _verify_code 静态门禁；门禁报**语法错**时带错误行及上下文**只重发出错段**
    （≤_CODE_REPAIR_RETRIES 次）。仍未通过的应用标 failed、不落盘，其余照常写。
    """
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="code")
    apps = state.get("app_names") or []
    detail_map = state.get("detail_map") or {}
    rows_map = state.get("rows_map") or {}
    convention = state.get("convention") or ""
    shared = state.get("arch_shared") or ""
    groupbuild_store.append_log(
        task_id, f"code：{len(apps)} 个应用 ×（2 段代码 + README）= {len(apps) * 3} 次 LLM 调用，"
                 f"摊平并发≤{_CODE_PARALLEL}…")

    # 主线程序列化预构造每个 (应用, 槽位) 的 prompt
    jobs = []    # (app, slot, system, user)
    prompts = {}  # (app, slot) -> (system, user)：门禁失败后重生成修复复用
    meta = {}    # app -> (cn, cls, idk)
    for app in apps:
        row = rows_map.get(app, {})
        cn, cls, idk = row.get("name_cn", app), row.get("cls", ""), row.get("id", "")
        meta[app] = (cn, cls, idk)
        detail = detail_map.get(app) or "（缺应用详设）"
        for slot, label, instr in _CODE_SLOTS:
            system = (_CODE_PREAMBLE + _GOLDEN_REF + "【本次任务】" + instr +
                      "\n\n===== 编码规范正本（design/CONVENTION.md）=====\n" + convention)
            user = (f"应用组：{group}（{state.get('name_cn') or ''}）\n"
                    f"本次要编码的聚合根：应用名 `{app}` / 类名 `{cls}` / 标识 `{idk}` / 中文名 {cn}\n\n"
                    f"## 跨应用上下文（architecture.md：总表 / 关系图 / 设计决策 / 待确认）\n{shared}\n\n"
                    f"## 该聚合根《应用详设》（主输入）\n{detail}\n\n"
                    f"请只输出{label}。")
            jobs.append((app, slot, system, user))
            prompts[(app, slot)] = (system, user)

    def run_job(job):
        app, slot, system, user = job
        try:
            text = _chat(system, user)
            if slot in ("code0", "code1"):   # 仅代码段做全角→半角；README 是 markdown，保留原文
                text = _fix_fullwidth_in_code(text)
            return app, slot, text, None
        except Exception as e:              # 并发内异常收集，统一报错
            return app, slot, None, str(e)

    results, errs = {}, {}   # {app: {slot: 正文}} / {app: [错误...]}
    workers = max(1, min(len(jobs), _CODE_PARALLEL))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for app, slot, text, err in ex.map(run_job, jobs):
            if err is not None:
                errs.setdefault(app, []).append(f"{slot} 生成异常：{err}")
            else:
                results.setdefault(app, {})[slot] = text

    # 逐应用拼接 + 静态门禁（槽位缺失 / 异常 / 门禁不过 → 该份失败，其余不受影响）
    code_map, failed = {}, []
    for app in apps:
        cn, cls, idk = meta[app]
        res = results.get(app, {})
        miss_slot = [s for s in ("code0", "code1", "readme") if s not in res]
        app_errs = errs.get(app, [])
        if app_errs or miss_slot:
            failed.append(app)
            why = "；".join(app_errs + [f"缺失：{s}" for s in miss_slot])
            groupbuild_store.append_log(task_id, f"code `{app}` 未通过：{why[:300]}")
            continue
        py_text = _join_code(res["code0"], res["code1"])
        problems = _verify_code(app, cls, py_text)
        # 门禁报语法错 → 定位出错段、带错误行及上下文回喂模型重生成修复（≤_CODE_REPAIR_RETRIES 次）
        for attempt in range(_CODE_REPAIR_RETRIES):
            if not problems:
                break
            err = _syntax_err(py_text)
            if err is None or not err.lineno:
                break                   # 缺项类问题（缺 _init_db / 返回注解等）重生成无益
            slot, _local = _locate_bad_slot(err.lineno, res)
            sys_p, usr_p = prompts[(app, slot)]
            usr_fix = (usr_p
                       + f"\n\n⚠️ 你上次的输出拼接成整文件后，第 {err.lineno} 行报语法错：{err.msg}。"
                       + "出错处上下文（行号| 代码，repr 显示缩进）：\n" + _err_context(py_text, err.lineno)
                       + "\n这几乎总是缩进错位：类内方法定义行 `def xxx(self, ...)` 必须**恰好缩进 4 个空格**"
                         "（与 `_init_db` 完全同级），方法体 8 空格，嵌套逐层 +4；"
                         "严禁方法定义行顶格 / 缩进 8 空格，严禁 Tab。"
                         "请保持功能不变、仅修正缩进，重新输出本段完整内容，不要任何解释。")
            groupbuild_store.append_log(
                task_id, f"code `{app}` 门禁未过（{err.msg}@行 {err.lineno}），"
                         f"重生成 {slot} 修复（{attempt + 1}/{_CODE_REPAIR_RETRIES}）…")
            try:
                res[slot] = _fix_fullwidth_in_code(_chat(sys_p, usr_fix))
            except Exception as e:      # 修复调用失败 → 放弃修复，按原门禁结果记失败
                groupbuild_store.append_log(
                    task_id, f"code `{app}` 修复重生成失败：{str(e)[:200]}")
                break
            py_text = _join_code(res["code0"], res["code1"])
            problems = _verify_code(app, cls, py_text)
        if problems:
            failed.append(app)
            err = _syntax_err(py_text)
            ctx = f"\n{_err_context(py_text, err.lineno)}" if err and err.lineno else ""
            groupbuild_store.append_log(
                task_id, f"code `{app}` 未过静态门禁（已尝试修复）：{'；'.join(problems)[:300]}{ctx}")
            continue
        code_map[app] = {"py": py_text, "readme": _strip_code_fences(res["readme"]).strip() + "\n"}

    if failed and not code_map:
        raise RuntimeError(f"全部聚合根编码失败：{', '.join(failed)}")
    msg = f"code 完成：{len(code_map)} 个应用代码通过静态门禁"
    if failed:
        msg += f"；失败 {len(failed)} 个（跳过）：{', '.join(failed)}"
    groupbuild_store.append_log(task_id, msg)
    return {"code_map": code_map, "failed_apps": failed}


def node_write_code(state: CodeState) -> dict:
    """逐聚合根落盘 app/<组>/<应用>/<应用>.py + README.md（同名应用文件夹）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="write")
    code_map = state.get("code_map") or {}
    if not code_map:
        raise RuntimeError("无可写内容：code 未产出任何应用代码")
    written = []
    for app, parts in code_map.items():
        d = APPS_DIR / group / app
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{app}.py").write_text(parts["py"], encoding="utf-8")
        (d / "README.md").write_text(parts["readme"], encoding="utf-8")
        written.append(app)
    groupbuild_store.append_log(
        task_id, f"write 完成：{len(written)} 个应用 → app/{group}/<应用>/<应用>.py + README.md"
                 f"（{', '.join(written)}）")
    return {}


# ── 第④步图节点（测试用例生成）─────────────────────────

def node_gather_testcase(state: TestCaseState) -> dict:
    """收集第④步输入并瘦身：应用测试.md 规格 + architecture.md 共享段（_build_shared 去卡）
    + 各应用详设的**测试相关摘要**（BR/状态机/[功能]/外部依赖；缺失即失败 → 先跑第②步）
    + _contracts.md（若有，服务签名以此为准）+ 主数据应用清单（总表『是否主数据』）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gather")
    groupbuild_store.append_log(task_id, "gather：读取测试用例规格与架构 / 详设 / 契约…")

    spec = TESTCASE_SPEC.read_text(encoding="utf-8") if TESTCASE_SPEC.is_file() else ""
    if not spec:
        raise RuntimeError("缺少技能规格文件：design/应用测试.md")

    arch_path = APPS_DIR / group / "architecture.md"
    if not arch_path.is_file():
        raise RuntimeError(f"缺少 app/{group}/architecture.md，请先运行『生成架构』（第①步）。")
    arch_md = arch_path.read_text(encoding="utf-8")

    rows = _table_rows(arch_md)
    all_apps = [r["app"] for r in rows]
    if not all_apps:
        raise RuntimeError("architecture.md 总表未解析到任何聚合根，无法生成测试用例。")

    detail_map, missing = {}, []
    for app in all_apps:
        p = APPS_DIR / group / app / "应用详设.md"
        if p.is_file():
            detail_map[app] = p.read_text(encoding="utf-8")
        else:
            missing.append(app)
    if missing:
        raise RuntimeError(
            f"以下聚合根缺少 应用详设.md，请先运行『生成应用详设』（第②步）：{', '.join(missing)}")

    contracts_path = APPS_DIR / group / "_contracts.md"
    contracts = contracts_path.read_text(encoding="utf-8") if contracts_path.is_file() else ""
    has_contracts = bool(contracts.strip())

    # 输入瘦身（P0+P1+P2）：
    #  - arch 只取共享段（_build_shared 去聚合根卡）；
    #  - 每份详设抽测试相关段（BR/状态机/[功能]/外部依赖），丢 prose；主数据应用恒含功能段
    #    （数据字典要据此冻结字段值），非主数据应用在有 _contracts.md 时可省功能段（签名以契约为准）。
    rows_map = {r["app"]: r for r in rows}
    master_apps = [a for a in all_apps if rows_map.get(a, {}).get("is_master")]
    digests = {app: _detail_test_digest(detail_map[app],
                                        include_func=(app in master_apps) or not has_contracts)
               for app in all_apps}
    digest_total = sum(len(d) for d in digests.values())

    name_cn = state.get("name_cn") or ""
    if not name_cn:
        g = groupbuild_store.get_group(group)
        name_cn = (g or {}).get("name_cn", "") if g else ""

    groupbuild_store.append_log(
        task_id, f"gather 完成：规格 {len(spec)} 字；聚合根 {len(all_apps)} 个 → "
                 f"{', '.join(all_apps)}；详设 {len(detail_map)} 份；契约 "
                 f"{'有（_contracts.md）' if has_contracts else '无（以详设功能清单为准）'}；"
                 f"主数据应用 {len(master_apps)} 个；详设摘要合计 {digest_total} 字"
                 f"（原始 {sum(len(v) for v in detail_map.values())} 字，已瘦身）。")
    return {"spec": spec, "arch_shared": _build_shared(arch_md), "contracts": contracts,
            "digests": digests, "master_apps": master_apps,
            "app_names": all_apps, "name_cn": name_cn}


def _testcase_user_block(state: TestCaseState, label: str, detail_block: str) -> str:
    """第④步各分段的 user 上下文（组信息 + 架构共享段 + 契约 + **按段投喂的详设摘要**）。

    detail_block 由各段自备：数据字典段只给主数据应用摘要，主链/分支段给全量摘要（P2 按需投喂）。"""
    group = state["group"]
    return (f"应用组：{group}（{state.get('name_cn') or ''}）\n\n"
            f"## 架构（总表 / 关系图 / 设计决策 / 待确认 / 异步回执点）\n{state.get('arch_shared') or ''}\n\n"
            f"## 服务契约（_contracts.md，服务名 / 参数名以此为准）\n"
            f"{state.get('contracts') or '（未冻结 _contracts.md，服务名 / 参数名以详设功能清单为准）'}\n\n"
            f"{detail_block}\n\n"
            f"请只输出{label}。")


def node_gen_testcase(state: TestCaseState) -> dict:
    """生成整组测试用例：**先冻结测试数据字典**，再以冻结字典为约束**摊平并发**生成
    主业务链 + 分支 / 异常两段，最后拼装。三段均依规格四要素 + 数据自洽铁律。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gen")
    spec = state.get("spec") or ""
    spec_suffix = "\n\n===== 规格（design/应用测试.md）=====\n" + spec

    # 按段投喂的详设摘要（P2）：数据字典段只需主数据应用；主链/分支段需全量
    digests = state.get("digests") or {}
    apps = state.get("app_names") or []
    master_apps = state.get("master_apps") or []

    def render(names):
        return "\n\n".join(f"### 应用：{a}\n{digests[a]}" for a in names if digests.get(a))

    master_block = "## 主数据应用详设摘要（据此冻结数据字典字段值）\n" + render(master_apps or apps)
    all_block = "## 各应用详设摘要（BR / 状态机 / 功能 / 外部依赖）\n" + render(apps)

    # ① 数据字典先行冻结（§0 + §1 主数据，只投喂主数据摘要）——后续主链 / 分支只引用其中标识
    groupbuild_store.append_log(task_id, "gen：先冻结测试数据字典（§0 + §1，仅主数据摘要）…")
    data_instr = ("本次【只】输出『## §0 测试数据字典（冻结）』+『## §1 主数据准备』。"
                  "§0 用 markdown 表格冻结贯穿全链的标识（客户 / 物料 / 组织 / 手册 / 关键单据号等）+ 关键值；"
                  "§1 给主数据应用（如 customer / product / sales_org / bonded_handbook）的建数 / 同步用例"
                  "（各含 步骤 / 数据 / 期望）。后续主链 / 分支用例将**只引用**§0 标识，故此处务必冻结完整、自洽。"
                  "不要输出主业务链 / 分支用例。")
    data_sec = _strip_fences(_chat(_TESTCASE_PREAMBLE + "【本次任务】" + data_instr + spec_suffix,
                                   _testcase_user_block(state, "§0 测试数据字典 + §1 主数据准备", master_block)))

    # ② 主链 + 分支 摊平并发（投喂全量摘要 + 已冻结字典作约束）
    groupbuild_store.append_log(task_id, f"gen：摊平并发≤{_TESTCASE_PARALLEL} 生成 §2 主业务链 + §3 分支用例…")
    frozen = f"\n\n【已冻结的测试数据字典（§0），以下用例只可引用其中标识、禁止新造】\n{data_sec}\n"
    sections = [
        ("main", "## §2 主业务链用例",
         "本次【只】输出『## §2 主业务链』happy path 用例序列：从主数据沿架构关系图推进到终态，"
         "每用例含 步骤 / 数据 / 期望；**异步外部系统处标注回执模拟点**（调 `on_*_result` 成功路）。"
         + frozen + "不要输出数据字典 / 分支用例。"),
        ("branch", "## §3 分支 / 异常用例",
         "本次【只】输出『## §3 分支 / 异常用例』：撤回 / 驳回 / 超额阻止 / 失败重试 / 幂等 / 状态非法转换，"
         "及外部系统**失败路**（如 SAP 退回→重提）。期望多为 `抛 FdeError 含『…』`。"
         + frozen + "不要输出数据字典 / 主链用例。"),
    ]

    def run_job(item):
        key, label, instr = item
        try:
            return key, _strip_fences(_chat(
                _TESTCASE_PREAMBLE + "【本次任务】" + instr + spec_suffix,
                _testcase_user_block(state, label, all_block))), None
        except Exception as e:              # 并发内异常收集，统一报错
            return key, None, str(e)

    results, errs = {}, {}
    workers = max(1, min(len(sections), _TESTCASE_PARALLEL))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for key, text, err in ex.map(run_job, sections):
            if err is not None:
                errs[key] = err
            else:
                results[key] = text
    if errs:
        raise RuntimeError("测试用例分段生成失败：" + "；".join(f"{k}={v[:120]}" for k, v in errs.items()))

    # ③ 拼装整份文档
    title_cn = f"（{state['name_cn']}）" if state.get("name_cn") else ""
    header = (f"# 应用组 `{group}` 测试用例{title_cn}\n\n"
              "> 产出技能：测试用例生成（第④步，规格 `design/应用测试.md`）。\n"
              "> 输入：`architecture.md` + 各应用详设 + `_contracts.md`（若有）。本文件为整组联通测试用例，"
              "含自洽测试数据；**生成与执行分离**——用例四要素（步骤 / 数据 / 期望 / 回执模拟）即执行器接口。\n")
    doc = (header + "\n" + data_sec.strip() + "\n\n"
           + results["main"].strip() + "\n\n" + results["branch"].strip() + "\n")
    groupbuild_store.append_log(task_id, f"gen 完成：测试用例 {len(doc)} 字（§0-§3 齐）。")
    return {"testcase_md": doc}


def node_write_testcase(state: TestCaseState) -> dict:
    """落盘 app/<组>/测试用例.md（整组唯一一份）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="write")
    doc = state.get("testcase_md") or ""
    if not doc.strip():
        raise RuntimeError("无可写内容：gen 未产出测试用例")
    out_dir = APPS_DIR / group
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "测试用例.md").write_text(doc, encoding="utf-8")
    groupbuild_store.append_log(task_id, f"write 完成 → app/{group}/测试用例.md（{len(doc)} 字）。")
    return {}


# ── 第⑤步图节点（测试执行）─────────────────────────────

def _app_public_signatures(py_path: Path) -> list:
    """ast 抽单个应用的公共方法签名（['create(so_data, …)', ...]），静态分析、不 import 生成物。

    公共方法 = 不以 _ 开头（与 _verify_code / scanner 口径一致）；带默认值的参数标 `=…`。"""
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    sigs = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for n in node.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if n.name.startswith("_"):
                continue
            args = [a.arg for a in n.args.args if a.arg != "self"]
            n_def = len(n.args.defaults)
            req = args[: len(args) - n_def] if n_def else args
            opt = args[len(args) - n_def:] if n_def else []
            sigs.append(f"{n.name}({', '.join(req + [f'{o}=…' for o in opt])})")
    return sigs


def _signatures_digest(group: str, apps: list) -> str:
    """各应用公共方法签名校准摘要（供 gen 产出正确入参名）。"""
    parts = []
    for app in apps:
        sigs = _app_public_signatures(APPS_DIR / group / app / f"{app}.py")
        if sigs:
            parts.append(f"### 应用：{app}\n" + "\n".join(f"- {s}" for s in sigs))
    return "\n\n".join(parts)


def _verify_script(group: str, script: str) -> list:
    """第⑤步脚本静态门禁：语法可解析 + 必要骨架标记齐（返回问题清单，空=通过）。"""
    try:
        ast.parse(script)
    except SyntaxError as e:
        return [f"语法错误：{e.msg}（行 {e.lineno}）"]
    problems = []
    if "def clean(" not in script:
        problems.append("缺测试初始化 clean()")
    if not re.search(rf"GROUP\s*=\s*[\"']{re.escape(group)}[\"']", script):
        problems.append(f"缺 GROUP = \"{group}\"")
    if "VERIFY_RESULT" not in script:
        problems.append("缺结果哨兵 VERIFY_RESULT")
    if not re.search(r"\.call\(", script):
        problems.append("缺 platform.call 真实路由")
    return problems


def node_gather_testexec(state: TestExecState) -> dict:
    """收集第⑤步输入：测试执行.md 规格 + 测试用例.md（唯一测试设计来源，缺即失败 → 先跑第④步）
    + 各应用 .py 的公共方法签名（ast 校准）+ 脚本样板 + 架构共享段。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gather")
    groupbuild_store.append_log(task_id, "gather：读取测试执行规格与测试用例 / 应用签名 / 数据契约…")

    spec = TESTEXEC_SPEC.read_text(encoding="utf-8") if TESTEXEC_SPEC.is_file() else ""
    if not spec:
        raise RuntimeError("缺少技能规格文件：design/测试执行.md")

    tc_path = APPS_DIR / group / "测试用例.md"
    if not tc_path.is_file():
        raise RuntimeError(f"缺少 app/{group}/测试用例.md，请先运行『生成测试用例』（第④步）。")
    testcase_md = tc_path.read_text(encoding="utf-8")

    arch_path = APPS_DIR / group / "architecture.md"
    arch_md = arch_path.read_text(encoding="utf-8") if arch_path.is_file() else ""
    apps = [r["app"] for r in _table_rows(arch_md)] if arch_md else []
    present = [a for a in apps if (APPS_DIR / group / a / f"{a}.py").is_file()]
    if not present:   # 总表为空时的退路：扫描组目录内已有代码的应用
        group_dir = APPS_DIR / group
        if group_dir.is_dir():
            present = sorted(d.name for d in group_dir.iterdir()
                             if d.is_dir() and (d / f"{d.name}.py").is_file())
    if not present:
        raise RuntimeError(f"app/{group} 下没有任何应用代码（<应用>/<应用>.py），请先运行『生成应用代码』（第③步）。")
    missing = [a for a in apps if a not in present]
    if missing:
        groupbuild_store.append_log(
            task_id, f"提示：以下聚合根尚无应用代码，测试脚本仅覆盖已编码应用：{', '.join(missing)}")

    signatures = _signatures_digest(group, present)
    contracts_digest = _app_data_contracts(group, present)

    name_cn = state.get("name_cn") or ""
    if not name_cn:
        g = groupbuild_store.get_group(group)
        name_cn = (g or {}).get("name_cn", "") if g else ""

    # §0 数据字典节单独抽出，供分块生成时作为共享上下文恒带（各批只引用不新造标识）
    dict_block = "\n\n".join(b for no, _t, b in _split_testcase_sections(testcase_md) if no == "0")

    groupbuild_store.append_log(
        task_id, f"gather 完成：规格 {len(spec)} 字；测试用例 {len(testcase_md)} 字；"
                 f"应用代码 {len(present)} 个（签名 {len(signatures)} 字；数据契约 {len(contracts_digest)} 字）。")
    return {"spec": spec, "testcase_md": testcase_md, "arch_shared": _build_shared(arch_md),
            "signatures": signatures, "contracts_digest": contracts_digest,
            "dict_block": dict_block, "apps": present, "name_cn": name_cn}


def _wrap_cases(body: str) -> str:
    """把用例语句体（模型顶格输出）按 step(...) 标记切成用例块，逐块包 try/except 成软失败记录
    （某例失败 → 记原因继续跑，不阻断整脚本）。无 step 标记的非用例语句（如常量定义）原样
    置入；整体沉入 main() 的 4 空格缩进。"""
    lines = _normalize_code_text(_strip_code_fences(body)).split("\n")
    chunks, cur = [], []
    for ln in lines:
        if ln.lstrip().startswith("step(") and cur:
            chunks.append(cur)
            cur = []
        cur.append(ln)
    if cur:
        chunks.append(cur)
    out = []
    for ch in chunks:
        if not any(l.lstrip().startswith("step(") for l in ch):
            out.extend(("    " + l if l.strip() else "") for l in ch)
            continue
        out.append("    try:")
        out.extend(("        " + l if l.strip() else "") for l in ch)
        out.append("    except AssertionError as e:")
        out.append("        record(False, f'断言: {e}')")
        out.append("    except FdeError as e:")
        out.append("        record(False, f'业务错: {e}')")
        out.append("    except Exception as e:")
        out.append("        record(False, f'{type(e).__name__}: {e}')")
        out.append("    else:")
        out.append("        record(True)")
    return "\n".join(out)


_CREATE_RE = re.compile(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\((.*?)\)\s*(?:;|\"|'|$)",
                        re.I | re.S)


def _app_data_contracts(group: str, apps: list) -> str:
    """静态抽各应用 _init_db 里 CREATE TABLE 的表 / 列 / 必填（NOT NULL 且非主键）摘要——
    「数据契约」，供 gen 产出正确入参形态（消除主数据同步类调用的字段误译）。"""
    parts = []
    for app in apps:
        p = APPS_DIR / group / app / f"{app}.py"
        try:
            src = p.read_text(encoding="utf-8")
        except OSError:
            continue
        tables = []
        for m in _CREATE_RE.finditer(src):
            name, body = m.group(1), m.group(2)
            body = re.sub(r"--[^\n]*", "", body)   # 剥 SQL 行注释（建表里的 `-- 说明`）
            cols, depth, seg = [], 0, ""
            for ch in body + ",":
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                if ch == "," and depth == 0:
                    c = seg.strip()
                    seg = ""
                    if not c or c.upper().startswith(("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT")):
                        continue
                    cname = c.split()[0].strip("\"'`[]")
                    up = c.upper()
                    req = ("NOT NULL" in up and "PRIMARY KEY" not in up
                           and "AUTOINCREMENT" not in up)
                    cols.append(cname + ("（必填）" if req else ""))
                else:
                    seg += ch
            if cols:
                tables.append(f"  - 表 `{name}`: " + ", ".join(cols))
        if tables:
            parts.append(f"### 应用：{app}\n" + "\n".join(tables))
    return "\n\n".join(parts)


def _assemble_script_set(bodies: list, labels: list, group: str, apps: list) -> dict:
    """拼装测试脚本集：编排器 verify_chain_<组>.py + 每批一个 part 模块（run_part 语句体）。
    返回 {文件名: 内容}（文件均落 app/<组>/tests/）。运行入口 = 编排器，按序调各 part；
    part 级崩溃被编排器隔离记录（不阻断后续 part），业务步软失败由 part 内逐例 try/except 记录。"""
    files = {}
    parts_meta = []
    for i, (label, body) in enumerate(zip(labels, bodies), 1):
        name = f"part{i}"
        head = (_PART_HEADER.replace("__GROUP__", group)
                .replace("__NAME__", name).replace("__LABEL__", label))
        files[f"verify_chain_{group}_{name}.py"] = head + _wrap_cases(body) + "\n"
        parts_meta.append((name, label))
    orch = (_SCRIPT_HEADER.replace("__GROUP__", group).replace("__APPS__", repr(list(apps)))
            + _ORCHESTRATOR_PARTS.replace("__PARTS__", repr(parts_meta))
            + _SCRIPT_CLOSER.lstrip("\n"))
    files[f"verify_chain_{group}.py"] = orch
    return files


def _verify_script_set(group: str, script_set: dict) -> list:
    """脚本集门禁：编排器走完整门禁（clean / GROUP / 哨兵 / call）；各 part 须可解析且含 run_part。
    问题条目带文件名前缀（`verify_chain_<组>_partN.py: …`），供按文件归属定向重生成。"""
    orch_name = f"verify_chain_{group}.py"
    problems = [f"{orch_name}: {p}" for p in _verify_script(group, script_set.get(orch_name, ""))]
    for fname in sorted(script_set):
        if fname == orch_name:
            continue
        src = script_set[fname]
        try:
            ast.parse(src)
        except SyntaxError as e:
            problems.append(f"{fname}: 语法错误：{e.msg}（行 {e.lineno}）")
            continue
        if "def run_part(" not in src:
            problems.append(f"{fname}: 缺 run_part")
    return problems


def _persist_script_set(group: str, script_set: dict) -> None:
    """脚本集落盘 app/<组>/tests/：先清同前缀旧 part（防上轮更多 part 残留），再写本集全部文件。"""
    test_dir = APPS_DIR / group / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    for old in test_dir.glob(f"verify_chain_{group}_part*.py"):
        old.unlink()
    for fname, src in script_set.items():
        (test_dir / fname).write_text(src, encoding="utf-8")


def _gen_verify_script(state: dict, fix_note: str = "", on_retry=None) -> tuple:
    """按章节自适应分块生成 + harness 拼装整份测试脚本（§0+§1 / §2 / §3… 各按需再切块，
    每块 ≤ _CHUNK_MAX_CHARS；每批只投喂自己那节用例 + 共享的 §0 字典 / 契约 / 签名）。
    门禁未过按问题文件归属**定向重生成该批**（≤4 次）。返回 (script_set, problems, retries)，
    script_set = {文件名: 内容}（编排器 + 各 part，落 app/<组>/tests/）。

    分块是为规避超大组单段撞 max_tokens 截断（'{' was never closed）与网关推理超时（HTTP 504）。"""
    group = state["group"]
    tid = state.get("task_id")
    sys_base = (_TESTEXEC_PREAMBLE +
                "\n\n===== 技能规格（design/测试执行.md）=====\n" + (state.get("spec") or ""))
    shared = (f"## 测试数据字典（§0 冻结，全链标识只引用不新造）\n"
              f"{state.get('dict_block') or '（用例文档未含独立 §0 节，标识见各批用例自身）'}\n\n"
              f"## 数据契约（各应用建表字段；标（必填）的列必须随写入提供）\n"
              f"{state.get('contracts_digest') or '（未抽到建表字段）'}\n\n"
              f"## 各应用服务签名（入参名以此为准）\n"
              f"{state.get('signatures') or '（未抽到签名，按用例参数）'}\n\n"
              f"## 跨应用上下文（architecture.md 共享段）\n{state.get('arch_shared') or ''}")
    chunks = _plan_chunks(state.get("testcase_md") or "", _CHUNK_MAX_CHARS)
    total = len(chunks)
    if tid:
        groupbuild_store.append_log(
            tid, f"gen 分块：{total} 批（" + " / ".join(lb for lb, _b in chunks)
                 + f"）；单块上限 {_CHUNK_MAX_CHARS} 字。")

    def gen_chunk(i, label, body, extra=""):
        user = (f"应用组：{group}（{state.get('name_cn') or ''}）\n\n{shared}\n\n"
                f"## 本批用例（{label}）\n{body}\n\n" + _chunk_instr(label, i, total) + extra)
        return _fix_fullwidth_in_code(_chat(sys_base, user))

    bodies = []
    for i, (label, body) in enumerate(chunks, 1):
        _check_cancel(tid)
        if tid:
            groupbuild_store.append_log(tid, f"gen 批 {i}/{total}（{label}，{len(body)} 字用例）生成中…")
        bodies.append(gen_chunk(i, label, body, fix_note))
    labels = [lb for lb, _b in chunks]
    script_set = _assemble_script_set(bodies, labels, group, state.get("apps") or [])
    problems = _verify_script_set(group, script_set)
    retries = 0
    while problems and retries < 4:
        _check_cancel(tid)
        why = "；".join(problems)[:300]
        # 门禁问题按文件名归属：part 语法错 → 只重生成该批；编排器 / 其他问题 → 全批重出
        m = re.search(rf"verify_chain_{re.escape(group)}_part(\d+)\.py: 语法错误：(.+?)（行 (\d+)）",
                      problems[0])
        if m:
            idx = int(m.group(1)) - 1
            fname = f"verify_chain_{group}_part{m.group(1)}.py"
            ctx = _err_context(script_set[fname], int(m.group(3)))
            msg = m.group(2) or ""
            if on_retry:
                on_retry(f"门禁修复（{why}） → 批 {idx + 1}/{total}")
            note = (f"\n\n⚠️ 上一版本批语句体拼装后未过静态门禁：{why}；出错在第 {m.group(3)} 行，"
                    f"上下文（行号| 代码）：\n{ctx}\n"
                    + ("（疑似本批输出被截断：请压缩注释与空行、保持用例完整，勿超长度。）"
                       if ("never closed" in msg or "EOF" in msg) else "")
                    + "\n请严格按契约修正后重新输出本批完整语句体。")
            lb, bd = chunks[idx]
            bodies[idx] = gen_chunk(idx + 1, lb, bd, note)
        else:
            if on_retry:
                on_retry(f"门禁修复（{why}） → 全批重出")
            note = (f"\n\n⚠️ 上一版未过静态门禁：{why}。请严格按契约修正后重新输出。")
            bodies = [gen_chunk(i + 1, lb, bd, note) for i, (lb, bd) in enumerate(chunks)]
        script_set = _assemble_script_set(bodies, labels, group, state.get("apps") or [])
        problems = _verify_script_set(group, script_set)
        retries += 1
    return script_set, problems, retries


def node_gen_testexec(state: TestExecState) -> dict:
    """按章节自适应分块生成整份测试脚本（§0+§1 / §2 / §3… 各按需再切）+ 静态骨架拼装，
    过 _verify_script 门禁。语法错修不好 → 任务失败；仅标记缺失（理论不会，收尾静态补齐）→ 警告后继续。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gen")
    groupbuild_store.append_log(
        task_id, f"gen：将测试用例翻译为 verify_chain_{group}.py（按章节自适应分块生成 + 拼装）…")

    script_set, problems, retries = _gen_verify_script(
        state, on_retry=lambda m: groupbuild_store.append_log(task_id, f"gen {m}…"))
    if any("语法错误" in p for p in problems):
        raise RuntimeError(f"测试脚本未过静态门禁（已重试 {retries} 次）：{'；'.join(problems)[:300]}")
    if problems:
        groupbuild_store.append_log(task_id, f"gen 提示：标记缺失（{'；'.join(problems)}），运行期兜底判定。")
    groupbuild_store.append_log(
        task_id, f"gen 完成：脚本集 {len(script_set)} 个文件（编排器 + {len(script_set) - 1} 个 part；"
                 f"门禁修复 {retries} 次）。")
    return {"script_set": script_set}


def _sandbox_ignore(src, names):
    """沙箱复制排除集：一切真实数据（*.db* / brd / dbguard 备份与锁 / __pycache__）。"""
    ignored = set()
    for n in names:
        low = n.lower()
        if n in ("__pycache__", ".db_backup", ".dbguard.lock", "brd"):
            ignored.add(n)
        elif low.endswith((".db", ".db-wal", ".db-shm")):
            ignored.add(n)
    return ignored


def _build_sandbox(task_id: int, group: str) -> Path:
    """搭一次性最小可运行树，返回沙箱根。复制 fde_platform/ + fde.py + config/stub/
    + app/<组>/（仅应用代码；tests/ 等测试产物目录不复制——沙箱只跑契约 dump，不依赖 tests/）。

    供⑧契约冻结 dump 使用（造数链在沙箱全新空库内跑、一次性副本即隔离）；第⑤步测试执行
    已改真实树直跑（清表初始化），不再经沙箱。"""
    sandbox = SANDBOX_BASE / str(task_id)
    if sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)
    sandbox.mkdir(parents=True)
    shutil.copytree(PROJECT_ROOT / "fde_platform", sandbox / "fde_platform", ignore=_sandbox_ignore)
    if (PROJECT_ROOT / "fde.py").is_file():
        shutil.copy2(PROJECT_ROOT / "fde.py", sandbox / "fde.py")
    stub = PROJECT_ROOT / "config" / "stub"
    if stub.is_dir():
        shutil.copytree(stub, sandbox / "config" / "stub", ignore=_sandbox_ignore)
    dst_group = sandbox / "app" / group
    src_group = APPS_DIR / group
    if src_group.is_dir():
        for d in src_group.iterdir():
            if d.is_dir() and d.name not in ("brd", "test", "tests", "__pycache__"):
                shutil.copytree(d, dst_group / d.name, ignore=_sandbox_ignore)
    return sandbox


def _run_script(group: str) -> dict:
    """真实树 subprocess 直跑测试脚本（stub 环境、超时保护），解析哨兵 → 结果 dict。

    脚本自身 clean() 做清表初始化（保留库文件、只清数据，平台持库连接也无锁冲突）。
    verdict 优先取 `VERIFY_RESULT:` 哨兵；无哨兵（旧式脚本）回退 rc + 关键字判定。"""
    script = (APPS_DIR / group / "tests" / f"verify_chain_{group}.py").resolve()
    env = dict(os.environ)
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "SAP_BASE_URL", "MOM_BASE_URL",
              "WMS_BASE_URL", "MDM_BASE_URL", "APS_BASE_URL", "CTCT_BASE_URL"):
        env.pop(k, None)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.Popen([sys.executable, str(script)], cwd=str(PROJECT_ROOT), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
    except Exception as e:
        return {"verdict": "CRASH", "rc": 1, "timed_out": False, "counts": None,
                "failed_step": "", "steps": [], "output_tail": f"脚本启动失败：{e}"}
    buf = []

    def _reader():
        for line in proc.stdout:
            buf.append(line)

    rt = threading.Thread(target=_reader, daemon=True)
    rt.start()
    start = time.time()
    timed_out = False
    while proc.poll() is None:
        if _cancel_flagged():          # 用户请求终止 → 杀掉测试子进程，抛 TaskCancelled
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
            rt.join(timeout=5)
            raise TaskCancelled("任务已被用户终止（测试运行中止）")
        if time.time() - start > _TESTEXEC_RUN_TIMEOUT:
            proc.kill()
            timed_out = True
            break
        time.sleep(1)
    rt.join(timeout=5)
    out = "".join(buf)
    if timed_out:
        out += f"\n（运行超时，已终止（>{_TESTEXEC_RUN_TIMEOUT}s））"
    rc = proc.returncode if proc.returncode is not None else 1
    m = re.search(r"VERIFY_RESULT:\s*([A-Z]+)(?:\s+(\d+)/(\d+))?", out)
    if m:
        verdict = m.group(1)
        counts = (int(m.group(2)), int(m.group(3))) if m.group(2) else None
    else:   # 旧式两态脚本（PASS/FAIL）回退判定
        verdict = "PASS" if (rc == 0 and "PASS" in out) else "CRASH"
        counts = None
    fs = re.search(r"FAIL_STEP:\s*(.+)", out)
    steps = [{"tc": sm.group(2).strip(), "ok": sm.group(1) == "PASS",
              "note": (sm.group(3) or "").strip()}
             for sm in re.finditer(r"^(PASS|FAIL) (.+?)(?: \| (.*))?$", out, re.M)]
    return {"verdict": verdict, "rc": rc, "timed_out": timed_out, "counts": counts,
            "failed_step": fs.group(1).strip() if fs else "", "steps": steps,
            "output_tail": out[-_TESTEXEC_OUTPUT_TAIL:]}


def _render_report(group: str, name_cn: str, result: dict) -> str:
    """拼装 app/<组>/test/测试报告.md（三态 verdict + 逐例结果表）。"""
    from datetime import datetime
    verdict_cn = {"PASS": "✅ 全绿", "PARTIAL": "⚠️ 部分通过",
                  "FAIL": "❌ 用例全败", "CRASH": "💥 脚本自身崩溃"}
    counts = result.get("counts")
    cnt = f"（{counts[0]}/{counts[1]} 例通过）" if counts else ""
    lines = [
        f"# 应用组 `{group}` 测试执行报告{('（' + name_cn + '）') if name_cn else ''}",
        "",
        "> 产出技能：测试执行（第⑤步，规格 `design/测试执行.md`，平台自动化任务 · 真实树运行、清表初始化）。",
        f"> 脚本：`app/{group}/tests/verify_chain_{group}.py`（符合规格完整模板，可手动重跑）。",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- **结果**：{verdict_cn.get(result['verdict'], result['verdict'])}{cnt}",
        f"- **运行轮数**：{result['iterations']}（仅 CRASH / 用例全败触发脚本修复）",
    ]
    if result.get("failed_step"):
        lines.append(f"- **崩溃处**：{result['failed_step']}")
    steps = result.get("steps") or []
    if steps:
        lines += ["", "## 逐例结果", "", "| 用例 | 结果 | 备注 |", "|---|---|---|"]
        lines += [f"| {s['tc']} | {'✓' if s['ok'] else '✗'} | {(s['note'] or '—')[:200]} |"
                  for s in steps]
        if any(not s["ok"] for s in steps):
            lines += ["", "> 失败 triage（见规格）：**脚本 / 用例校准错**（修脚本、回填用例）vs **真实应用 bug**"
                      "（记录反馈第③步）；以**首个真实失败用例**为 triage 重点（其后的失败可能是级联）。"]
    lines += ["", "## 最后一次运行输出（尾部）", "", "```",
              (result.get("output_tail") or "").rstrip(), "```", ""]
    return "\n".join(lines)


def node_run_testexec(state: TestExecState) -> dict:
    """真实树直跑测试脚本（clean() 清表初始化，保留库文件、平台持库连接也无锁冲突）；
    verdict 三态：PASS / PARTIAL（直接出报告、不修复）vs CRASH / 用例全败（触发 LLM 回喂
    修复脚本重跑，≤_TESTEXEC_REPAIR 轮）。连续两轮错误签名相同（无进展）或修复输出与
    原脚本一致 → 提前终止。脚本与报告落盘 app/<组>/tests/（人工可核对 / 重跑）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="run")
    script_set = state.get("script_set") or {}
    if not script_set:
        raise RuntimeError("无可运行脚本：gen 未产出")

    history, last_sig, res = [], None, None
    for attempt in range(_TESTEXEC_REPAIR + 1):
        _check_cancel(task_id)
        _persist_script_set(group, script_set)   # 每轮（含修复重生成后）先落盘真实树再跑
        res = _run_script(group)                 # 跑编排器（按序调各 part）
        counts_txt = f"（{res['counts'][0]}/{res['counts'][1]}）" if res.get("counts") else ""
        history.append({"round": attempt + 1, "verdict": res["verdict"],
                        "counts": res.get("counts"), "failed_step": res["failed_step"]})
        groupbuild_store.append_log(
            task_id, f"run 第 {attempt + 1} 轮：{res['verdict']}{counts_txt}"
                     + (f" @ {res['failed_step']}" if res["failed_step"] else ""))
        if res["verdict"] in ("PASS", "PARTIAL"):   # 全绿 / 部分通过 = 真实结果，不修复
            break
        if attempt >= _TESTEXEC_REPAIR:
            break
        sig = (res["failed_step"], res["output_tail"][-300:])
        if sig == last_sig:
            groupbuild_store.append_log(task_id, "修复终止：连续两轮错误签名相同，无进展。")
            break
        last_sig = sig
        # CRASH / 用例全败 → 分段重生成修复（同 gen：避免整份重出撞网关单请求上限）
        fix_note = ("\n\n【修复上下文】上一版脚本本轮运行**脚本级崩溃或用例全败**（多为入参形态等共性问题，"
                    "不是业务失败）。请按《测试执行.md》『失败 triage』规则修复：对照用例示例数据 + 数据契约 + "
                    "服务签名核查调用对象 / 入参形态 / 必填列；**严禁**编写多形态轮询探测循环；"
                    "报错指出缺某字段就直接补齐（值取自用例数据字典）。\n"
                    f"上一轮运行输出（尾部）：\n```\n{res['output_tail']}\n```\n")
        groupbuild_store.append_log(task_id, "run 修复重生成（按章节分块重出）…")
        try:
            new_set, probs, _r = _gen_verify_script(
                state, fix_note=fix_note,
                on_retry=lambda m: groupbuild_store.append_log(task_id, f"run 修复内 {m}…"))
        except Exception as e:
            groupbuild_store.append_log(task_id, f"修复重生成失败：{str(e)[:200]}")
            break
        if any("语法错误" in p for p in probs):
            groupbuild_store.append_log(
                task_id, f"修复终止：重生成脚本仍未过门禁：{'；'.join(probs)[:200]}")
            break
        if new_set == script_set:
            groupbuild_store.append_log(task_id, "修复终止：修复输出与原脚本一致。")
            break
        script_set = new_set

    verdict = res["verdict"] if res else "CRASH"
    if verdict != "PASS":
        groupbuild_store.append_log(task_id, f"最终 {verdict}（脚本与报告已落盘 app/{group}/tests/，可人工核对重跑）。")
    groupbuild_store.append_log(
        task_id, f"run 完成：verdict={verdict}，共 {len(history)} 轮。")
    return {"script_set": script_set,
            "result": {"verdict": verdict, "counts": res.get("counts") if res else None,
                       "failed_step": res["failed_step"] if res else "",
                       "steps": res.get("steps") if res else [],
                       "output_tail": res["output_tail"] if res else "",
                       "iterations": len(history), "history": history}}


def node_write_testexec(state: TestExecState) -> dict:
    """落盘真实树 app/<组>/test/：最终脚本集（编排器 + 各 part）+ 测试报告.md；
    有失败用例 → 追加 BUGS.md（待 triage）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="write")
    script_set = state.get("script_set") or {}
    result = state.get("result") or {}
    if not script_set:
        raise RuntimeError("无可写内容：run 未产出脚本")
    _persist_script_set(group, script_set)
    test_dir = APPS_DIR / group / "tests"
    report = _render_report(group, state.get("name_cn") or "", result)
    (test_dir / f"测试报告_{group}.md").write_text(report, encoding="utf-8")
    failed_steps = [s for s in (result.get("steps") or []) if not s["ok"]]
    if failed_steps:
        bugs = test_dir / f"BUGS_{group}.md"
        head = (f"# {group} 应用组 · 联通测试失败用例台账（待 triage：脚本校准错 vs 应用 bug）\n\n"
                if not bugs.is_file() else "")
        stamp = (f"\n## 自动测试一轮（verdict={result.get('verdict')}，{result.get('iterations')} 轮）\n"
                 + "\n".join(f"- {s['tc']}：{s['note'][:200]}" for s in failed_steps) + "\n")
        with bugs.open("a", encoding="utf-8") as f:
            f.write(head + stamp)
    groupbuild_store.append_log(
        task_id, f"write 完成 → app/{group}/tests/verify_chain_{group}.py + app/{group}/tests/测试报告_{group}.md"
                 + (f"（+ app/{group}/tests/BUGS_{group}.md 追加 {len(failed_steps)} 条失败用例）" if failed_steps else ""))
    # 对账消项：bugfix-apply 落的提案，其用例本轮转绿 → 标 resolved + BUGS.md 打 ✅
    applied_props = groupbuild_store.list_proposals(group, status="applied")
    if applied_props:
        passed_tokens = {s["tc"].split()[0] for s in (result.get("steps") or []) if s["ok"]}
        resolved = [p["entry_ref"].split()[0] for p in applied_props
                    if p["entry_ref"].split()[0] in passed_tokens]
        for p in applied_props:
            if p["entry_ref"].split()[0] in passed_tokens:
                groupbuild_store.set_proposal_status(p["id"], "resolved")
        if resolved:
            _tick_bugs_md(test_dir / f"BUGS_{group}.md", resolved)
            groupbuild_store.append_log(
                task_id, f"对账：{len(resolved)} 条已应用提案的用例转绿，标 resolved（{', '.join(resolved)}）")
    return {}


# ── ⑧契约冻结（沙箱 dump，无 LLM）──────────────────────
# 产出 app/<组>/_contracts.md（前端详设第⑥步的硬依赖屏障）。执行体为平台模块
# fde_platform/contract_dump.py（不依赖 tests/）：沙箱副本排除一切 *.db*，应用在沙箱内
# 建全新空库，造数链（组侧可选钩子 app/<组>/seed_contracts.py，缺则签名级）+ 签名内省，
# 一次性副本即隔离，不调 dbguard。

def node_gather_contracts(state: ContractsState) -> dict:
    """预检：组内至少一个已编码应用（<应用>/<应用>.py），无 → 失败指回第③步编码。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gather")
    groupbuild_store.append_log(task_id, "gather：预检组内应用代码…")
    group_dir = APPS_DIR / group
    apps = sorted(d.name for d in group_dir.iterdir()
                  if d.is_dir() and (d / f"{d.name}.py").is_file()) if group_dir.is_dir() else []
    if not apps:
        raise RuntimeError(f"app/{group} 下没有任何应用代码（<应用>/<应用>.py），"
                           f"请先运行『生成应用代码』（第③步）。")
    groupbuild_store.append_log(
        task_id, f"gather 完成：已编码应用 {len(apps)} 个（{', '.join(apps)}）。")
    return {"apps": apps}


def _run_contracts_dump(task_id: int, sandbox: Path, group: str) -> dict:
    """沙箱内 subprocess 跑契约 dump（stub 环境、超时保护、取消感知）。
    成功判据 = rc==0 且沙箱内 app/<组>/_contracts.md 存在（dump 只出人话，不解析哨兵）。"""
    driver = sandbox / "_dump_driver.py"
    driver.write_text("from fde_platform.contract_dump import dump\n"
                      f"dump({group!r}, seed=True)\n", encoding="utf-8")
    env = dict(os.environ)
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "SAP_BASE_URL", "MOM_BASE_URL",
              "WMS_BASE_URL", "MDM_BASE_URL", "APS_BASE_URL", "CTCT_BASE_URL"):
        env.pop(k, None)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.Popen([sys.executable, str(driver)], cwd=str(sandbox), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "rc": 1, "timed_out": False, "output_tail": f"dump 启动失败：{e}"}
    buf = []

    def _reader():
        for line in proc.stdout:
            buf.append(line)

    rt = threading.Thread(target=_reader, daemon=True)
    rt.start()
    start = time.time()
    timed_out = False
    while proc.poll() is None:
        if _cancel_flagged():          # 用户请求终止 → 杀掉沙箱子进程，抛 TaskCancelled
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
            rt.join(timeout=5)
            raise TaskCancelled("任务已被用户终止（沙箱 dump 中止）")
        if time.time() - start > _CONTRACTS_RUN_TIMEOUT:
            proc.kill()
            timed_out = True
            break
        time.sleep(1)
    rt.join(timeout=5)
    out = "".join(buf)
    if timed_out:
        out += f"\n（dump 超时，已终止（>{_CONTRACTS_RUN_TIMEOUT}s））"
    rc = proc.returncode if proc.returncode is not None else 1
    produced = (sandbox / "app" / group / "_contracts.md").is_file()
    return {"ok": rc == 0 and produced, "rc": rc, "timed_out": timed_out,
            "output_tail": out[-_TESTEXEC_OUTPUT_TAIL:]}


def node_run_contracts(state: ContractsState) -> dict:
    """沙箱内跑 contract_dump.dump(seed=True)。成功 → 拷回真实树 + 删沙箱；
    失败 → 保留沙箱备查（路径入日志）+ raise（无修复回路）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="run")
    groupbuild_store.append_log(task_id, "run：搭建沙箱并运行契约 dump（造数链 + 签名内省）…")
    sandbox = _build_sandbox(task_id, group)
    res = _run_contracts_dump(task_id, sandbox, group)
    groupbuild_store.append_log(task_id, f"run 输出（尾部）：\n{res['output_tail'][-2000:]}")
    if not res["ok"]:
        raise RuntimeError(f"契约 dump 失败（rc={res['rc']}"
                           f"{'，超时' if res['timed_out'] else ''}）；沙箱保留备查：{sandbox}")
    src = sandbox / "app" / group / "_contracts.md"
    dst = APPS_DIR / group / "_contracts.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    shutil.rmtree(sandbox, ignore_errors=True)
    groupbuild_store.append_log(
        task_id, f"run 完成：已拷回 app/{group}/_contracts.md，沙箱已清理。")
    return {"dump_output": res["output_tail"]}


def node_write_contracts(state: ContractsState) -> dict:
    """终验 app/<组>/_contracts.md 存在且非空，日志报应用节数。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="write")
    out = APPS_DIR / group / "_contracts.md"
    text = out.read_text(encoding="utf-8") if out.is_file() else ""
    if not text.strip():
        raise RuntimeError(f"契约文件缺失或为空：app/{group}/_contracts.md")
    groupbuild_store.append_log(
        task_id, f"write：app/{group}/_contracts.md 就绪（{text.count(chr(10) + '## ')} 个应用节）。")
    return {}


# ── ⑨前端详设（逐应用扇出 + 1 dashboard job；规格 design/前端设计.md）────

_FDESIGN_PREAMBLE = (
    "你是 FDE 平台的「前端设计」技能（九步法第⑥步），为应用逐页产出字段级前端详设文档。铁律：\n"
    "- **契约先行，不猜字段**：模态字段以契约 get 真实返回为准；表单字段严格按写服务"
    "（create/update/set_*/edit_draft/import_batch）接受的参数；搜索控件与 list 签名过滤参数一一对应，"
    "不自造前端假过滤；\n"
    "- **详情展示字段 ≠ 表单可写字段**：快照/派生字段只展示并注明「自动生成/快照」；"
    "审计字段（created_at/created_by/version 等）不进表单；\n"
    "- **列表列 ⊆ 详情字段集**；字段顺序统一：单号→状态→归属→数量/金额→时间；\n"
    "- **svc 全字面量** `svc(\"应用\",\"服务\")`（跨应用下拉同样字面量），严禁变量拼名；探测性加载 quiet + 零值兜底；\n"
    "- 枚举选项值与后端校验值严格一致；\n"
    "- **页面零鉴权**：不设计任何权限判断，受限菜单收敛由 shell 负责；\n"
    "- 回调/回写服务（on_*/add_* 等被上游/外部调用的）不是页面动作，不设计按钮。\n"
    "输出要求：只输出 Markdown 文档本身，六节结构（1 页面元数据 PAGE_META / 2 区块构成 / "
    "3 svc 字面量清单 / 4 数据来源与下拉 / 5 交互要点 / 6 验收关注点）；头部三行（来源/落地文件/页面定位）；"
    "精炼不注水，控制在 ~170 行内。")

_FDESIGN_IC_SPECIAL = {"customer_complaint": "⚠️", "return_order": "↩️", "reconciliation": "💰"}


def _fdesign_form_hint(app: str, is_master: bool) -> str:
    """页面形态提示（注入应用 job 的 user prompt）。"""
    if app.endswith("_change_order"):
        return "变更单型（原始快照 vs 变更后对比展示；create/edit/submit/approve/reject/void 按状态动作矩阵）"
    if app.endswith("_gateway"):
        return "网关型（outbox/inbox 列表 + 详情；重投/查结果按契约暴露的动作设计）"
    if is_master:
        return "主数据型（列表 + 详情 + 按契约写服务给创建/编辑；无状态机按钮；同步型可给同步按钮）"
    return "单据型（列表三段式 + 详情模态 + 创建表单；状态机动作按状态 x-show）"


def _static_menu_plan(apps: list, rows_map: dict) -> dict:
    """确定性菜单序分配器：dashboard=10 居首；其余按架构总表序 ×10+10。

    order 规则全部可编码、可复现（规格铁律第 4 条）；ic/crumb 按形态保守默认。"""
    plan = {"dashboard": {"order": 10, "ic": "📊",
                          "crumb": "主链管道 · KPI 指标 · 待办队列", "form_hint": "看板"}}
    for i, app in enumerate(apps):
        row = rows_map.get(app) or {}
        is_master = bool(row.get("is_master"))
        ic = _FDESIGN_IC_SPECIAL.get(
            app, "🗂" if is_master else ("✎" if app.endswith("_change_order")
                                        else ("🔌" if app.endswith("_gateway") else "📄")))
        defn = (row.get("defn") or "").strip()
        plan[app] = {"order": (i + 1) * 10 + 10, "ic": ic,
                     "crumb": defn or (row.get("name_cn") or app),
                     "form_hint": _fdesign_form_hint(app, is_master)}
    return plan


def _page_meta_block(app: str, plan: dict, rows_map: dict) -> str:
    """拼装注入 user prompt 的 PAGE_META 块（原样采用，不得改动）。"""
    p = plan.get(app) or {}
    name_cn = (rows_map.get(app) or {}).get("name_cn") or app
    return ("本页 PAGE_META（原样采用，不得改动）：\n"
            f"key=`{app}`, name=`{name_cn}`, ic=`{p.get('ic', '📄')}`, "
            f"title=`{name_cn}`, crumb=`{p.get('crumb') or name_cn}`, "
            f"order=`{p.get('order', 999)}`")


def _contracts_slice(contracts_md: str, app: str) -> str:
    """切 `## <应用>` 节（从 ^## 应用$ 到下一个 ^## 之前）；切不到返回 ''。"""
    m = re.search(rf"^##\s+{re.escape(app)}\s*$(.*?)(?=^##\s|\Z)", contracts_md, re.M | re.S)
    return ("## " + app + m.group(1)).strip() if m else ""


def _check_fdesign_complete(doc: str, is_dashboard: bool = False) -> list:
    """门禁：返回缺失项清单（空=通过）。六节关键词 + PAGE_META（兼容行内式 key= 与表格式 | key |）
    + order 数字 + svc 字面量；dashboard 变体查 KPI/管道/待办区块。"""
    missing = []
    for kw in ("页面元数据", "区块构成", "svc 字面量", "数据来源", "交互要点", "验收关注点"):
        if kw not in doc:
            missing.append(f"缺节「{kw}」")
    if "PAGE_META" not in doc:
        missing.append("缺 PAGE_META")
    elif not (re.search(r"key\s*=", doc) or re.search(r"\|\s*key\s*\|", doc)):
        missing.append("PAGE_META 缺 key（行内 key= 或表格 | key |）")
    if not re.search(r"order\s*[=|]\s*`?\d+", doc):
        missing.append("order 缺失或非数字")
    if 'svc("' not in doc:
        missing.append("缺 svc(\"应用\",\"服务\") 字面量")
    if is_dashboard:
        for kw in ("KPI", "管道", "待办"):
            if kw not in doc:
                missing.append(f"看板缺区块「{kw}」")
    return missing


def node_gather_fdesign(state: FdesignState) -> dict:
    """收集第⑨步输入：规格 + VIEW_CONVENTION 正本 + 契约（硬屏障）+ 目标应用详设（缺即失败指回②）
    + 架构共享段（软依赖）+ 确定性菜单规划。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gather")
    groupbuild_store.append_log(task_id, "gather：读取前端设计规格 / 视图约定 / 契约 / 应用详设…")

    spec = FDESIGN_SPEC.read_text(encoding="utf-8") if FDESIGN_SPEC.is_file() else ""
    if not spec:
        raise RuntimeError("缺少技能规格文件：design/前端设计.md")
    convention = VIEW_CONVENTION.read_text(encoding="utf-8") if VIEW_CONVENTION.is_file() else ""
    if not convention:
        raise RuntimeError("缺少前端视图约定正本：design/VIEW_CONVENTION.md")
    pitfalls = VIEW_PITFALLS.read_text(encoding="utf-8") if VIEW_PITFALLS.is_file() else ""

    contracts_path = APPS_DIR / group / "_contracts.md"
    if not contracts_path.is_file():
        raise RuntimeError(f"缺少 app/{group}/_contracts.md，请先运行『契约冻结』（⑧，前端段依赖屏障）。")
    contracts = contracts_path.read_text(encoding="utf-8")

    arch_path = APPS_DIR / group / "architecture.md"
    arch_md = arch_path.read_text(encoding="utf-8") if arch_path.is_file() else ""
    if not arch_md:
        groupbuild_store.append_log(task_id, "提示：architecture.md 缺失（软依赖）——菜单序退化为目录序，dashboard 无架构共享段。")
    rows = _table_rows(arch_md) if arch_md else []
    rows_map = {r["app"]: r for r in rows}

    # 目标应用集：指定子集 ∩ 有详设的应用；无架构时退路扫目录
    group_dir = APPS_DIR / group
    all_apps = ([r["app"] for r in rows] if rows else
                sorted(d.name for d in group_dir.iterdir()
                       if d.is_dir() and (d / f"{d.name}.py").is_file()) if group_dir.is_dir() else [])
    targets = state.get("target_apps") or []
    apps = [a for a in (targets or all_apps) if a in set(all_apps)] if targets else all_apps
    missing_detail = [a for a in apps if not (group_dir / a / "应用详设.md").is_file()]
    if missing_detail:
        raise RuntimeError(f"以下应用缺少 应用详设.md，请先运行『生成应用详设』（第②步）：{', '.join(missing_detail)}")
    if not apps:
        raise RuntimeError(f"app/{group} 下没有任何可设计的应用（无架构总表且无应用目录）。")
    detail_map = {a: (group_dir / a / "应用详设.md").read_text(encoding="utf-8") for a in apps}

    menu_plan = _static_menu_plan(apps, rows_map)
    groupbuild_store.append_log(
        task_id, f"gather 完成：规格 {len(spec)} 字；契约 {len(contracts)} 字；"
                 f"目标应用 {len(apps)} 个；菜单序 dashboard=10，应用 {apps[0]}={menu_plan[apps[0]]['order']}"
                 f" … {apps[-1]}={menu_plan[apps[-1]]['order']}。")
    return {"spec": spec, "convention": convention, "pitfalls": pitfalls,
            "contracts": contracts, "arch_md": arch_md, "shared_md": _build_shared(arch_md),
            "rows_map": rows_map, "menu_plan": menu_plan, "detail_map": detail_map,
            "target_apps": apps}


def node_fdesign_apps(state: FdesignState) -> dict:
    """N 个应用 job + 1 个 dashboard job 同池摊平并发；门禁不过 → 整份重出 ≤_FDESIGN_REPAIR 轮；
    失败应用跳过记日志、全败 raise。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gen")
    spec, convention = state["spec"], state["convention"]
    pitfalls = state.get("pitfalls") or ""
    contracts, shared_md = state["contracts"], state.get("shared_md") or ""
    rows_map, menu_plan, detail_map = state["rows_map"], state["menu_plan"], state["detail_map"]
    apps = list(detail_map.keys())
    groupbuild_store.append_log(task_id, f"gen：{len(apps)} 个应用 job + 1 dashboard job 摊平并发…")

    def gen_one(app: str):
        """生成单份前端详设（app 或 'dashboard'），返回 (app, doc, problems)。"""
        is_dash = app == "dashboard"
        if is_dash:
            meta_lines = "\n".join(
                f"- {a}：order={menu_plan[a]['order']}，name={rows_map.get(a, {}).get('name_cn', a)}，"
                f"形态={menu_plan[a]['form_hint']}" for a in apps if a in menu_plan)
            group_dir = APPS_DIR / group
            sm_parts = []
            for a in sorted(p.name for p in group_dir.iterdir()
                            if p.is_dir() and (p / "应用详设.md").is_file()):
                d = (group_dir / a / "应用详设.md").read_text(encoding="utf-8")
                sm = (_extract_section(d, "状态机", cap=1500)
                      or _extract_section(d, "状态流转", cap=1500) or "")
                sm_parts.append(f"### {a}\n{sm}" if sm else f"### {a}\n（无状态机）")
            system = (f"{_FDESIGN_PREAMBLE}\n\n===== 规格全文（design/前端设计.md）=====\n{spec}\n\n"
                      f"===== 前端视图约定正本（design/VIEW_CONVENTION.md）=====\n{convention}\n\n"
                      f"===== 前端踩坑清单（dashboard 铁律来源）=====\n{pitfalls}")
            user = (f"# 为应用组 {group} 产出组级首页看板（dashboard）前端详设\n\n"
                    f"## 全组共享上下文（架构）\n{shared_md}\n\n"
                    f"## 契约全文（_contracts.md，各应用 list 签名与返回样例）\n{contracts}\n\n"
                    f"## 全组 PAGE_META 总表（跳转目标 #/<应用> 与菜单序）\n{meta_lines}\n\n"
                    f"## 各应用状态机摘录（管道状态过滤值据此取）\n" + "\n\n".join(sm_parts) + "\n\n"
                    "只输出该看板的前端详设文档（PAGE_META：key=dashboard，order=10）：KPI 指标带 + "
                    "主链管道（各单据状态分布，状态计数用 list + status 过滤的 svc 字面量调用）+ 待办队列；"
                    "全部 svc 字面量 + quiet + 零值兜底（看板对受限用户恒显）。只输出文档。")
        else:
            slice_ = _contracts_slice(contracts, app)
            if not slice_:
                return app, "", ["契约无本应用节（_contracts.md 缺 ## " + app + "）"]
            system = (f"{_FDESIGN_PREAMBLE}\n\n===== 规格全文（design/前端设计.md）=====\n{spec}\n\n"
                      f"===== 前端视图约定正本（design/VIEW_CONVENTION.md）=====\n{convention}")
            user = (f"# 为应用组 {group} 的应用 {app} 产出前端详设\n\n"
                    f"{_page_meta_block(app, menu_plan, rows_map)}\n"
                    f"形态提示：{menu_plan[app]['form_hint']}\n\n"
                    f"## 本应用契约（字段真相）\n{slice_}\n\n"
                    f"## 本应用详设（业务语义）\n{detail_map[app]}\n\n只输出文档。")
        doc = _chat(system, user)
        problems = _check_fdesign_complete(doc, is_dash)
        retries = 0
        while problems and retries < _FDESIGN_REPAIR:
            retries += 1
            groupbuild_store.append_log(
                task_id, f"gen 门禁重出 {app}（第 {retries} 轮）：{'；'.join(problems)}")
            doc = _chat(system, user + f"\n\n【门禁反馈】上一版产出缺失：{'；'.join(problems)}。请补齐后输出完整文档。")
            problems = _check_fdesign_complete(doc, is_dash)
        return app, doc, problems

    fdesign_docs, dashboard_doc, failed = {}, "", []
    jobs = apps + ["dashboard"]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(len(jobs), _FDESIGN_PARALLEL)) as ex:
        futs = {ex.submit(gen_one, a): a for a in jobs}
        for fut in futs:
            app = futs[fut]
            try:
                _app, doc, problems = fut.result()
            except TaskCancelled:
                raise
            except Exception as e:
                failed.append(app)
                groupbuild_store.append_log(task_id, f"gen 失败 {app}：{str(e)[:200]}")
                continue
            if not doc or problems:
                failed.append(app)
                groupbuild_store.append_log(
                    task_id, f"gen 不完整 {app}：{'；'.join(problems)[:200]}")
                continue
            if app == "dashboard":
                dashboard_doc = doc
            else:
                fdesign_docs[app] = doc
            groupbuild_store.append_log(task_id, f"gen 完成 {app}（{len(doc.splitlines())} 行）。")
    if not fdesign_docs and not dashboard_doc:
        raise RuntimeError("前端详设生成全部失败（详见日志）。")
    groupbuild_store.append_log(
        task_id, f"gen 汇总：应用 {len(fdesign_docs)}/{len(apps)} 份 + dashboard "
                 f"{'1' if dashboard_doc else '0'} 份；失败：{', '.join(failed) if failed else '无'}。")
    return {"fdesign_docs": fdesign_docs, "dashboard_doc": dashboard_doc, "failed_apps": failed}


def node_write_fdesign(state: FdesignState) -> dict:
    """落盘真实树：逐应用 app/<组>/<应用>/前端详设.md + 组级 app/<组>/前端详设/dashboard.md。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="write")
    written = []
    for app, doc in (state.get("fdesign_docs") or {}).items():
        out = APPS_DIR / group / app / "前端详设.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc, encoding="utf-8")
        written.append(f"{app}/前端详设.md")
    if state.get("dashboard_doc"):
        out = APPS_DIR / group / "前端详设" / "dashboard.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(state["dashboard_doc"], encoding="utf-8")
        written.append("前端详设/dashboard.md")
    failed = state.get("failed_apps") or []
    groupbuild_store.append_log(
        task_id, f"write：{len(written)} 份落盘（{', '.join(written)}）"
                 + (f"；失败跳过：{', '.join(failed)}" if failed else "") + "。")
    return {}


# ── ⑩前端编码（单元 js→html 两阶段；规格 design/前端编码.md）────

_FCODE_PREAMBLE = (
    "你是 FDE 平台的「前端编码」技能（九步法第⑦步），为应用生成可运行的前端页面代码。铁律：\n"
    "- 顶部 import 一律**绝对路径**：`import { svc, hue, fmt, toast } from \"/view/lib/api.js\"`"
    " + `import { pageable } from \"/view/lib/shell.js\"`（相对路径迁入应用目录会断）；\n"
    "- **工厂必须默认导出** `export default function pageXxx()`（漏 default 静默坏页），函数体返回 "
    "`Alpine.reactive({...})`；状态写 `self` 上、方法内一律 `self.xxx =`，**不用 this**；\n"
    "- **reactive 状态同步先行**：模板引用的一切状态（tpl、含空 items:[] 的 list=pageable(...)、各模态对象）"
    "在第一个 await 之前同步建好，再 await 拉数；\n"
    "- 模板抓取：`self.tpl = await fetch(new URL(\"view.html\", import.meta.url)).then(r => r.text())`"
    "——应用页模板**固定名 view.html**；组级看板页模板与页面同名（dashboard.html）；\n"
    "- **svc 一律字面量** `svc(\"应用\",\"服务\",{...})`，绝不变量拼名/三元拼名；探测性加载用 "
    "`{quiet:true}` + `.catch` 零值兜底；\n"
    "- 展示工具统一：hue()/fmt() 放进 self；dash()/fmtTime()/tryParse() 是 window 全局、模板直接用；不自造格式化；\n"
    "- **页面零鉴权**；字段忠实于详设与契约：详设与契约漂移时以**契约字段**为准落码，可在末尾注释注明漂移，"
    "不就就、不臆造字段；枚举选项值与后端校验值严格一致；\n"
    "- 字段顺序统一：单号→状态→归属→数量/金额→时间；列表列 ⊆ 详情字段集；表单字段 = 详设 §2.3 可写字段集。\n"
    "输出契约：本轮只输出所要求文件（view.js 或 view.html）的完整内容，不要解释、不要标题、不要 Markdown 围栏。")


def _check_fcode_js(js: str, app: str, is_dashboard: bool = False) -> list:
    """门禁：view.js 机检（按 design/前端编码.md 验收标准），返回违规项清单（空=通过）。"""
    missing = []
    if "export default function" not in js:
        missing.append("缺默认导出工厂 `export default function`")
    if "export const PAGE_META" not in js:
        missing.append("缺 `export const PAGE_META`")
    else:
        key = "dashboard" if is_dashboard else app
        if not re.search(rf'key\s*:\s*["\']{re.escape(key)}["\']', js):
            missing.append(f'PAGE_META key 必须逐字为 "{key}"')
        if not re.search(r"order\s*:\s*\d+", js):
            missing.append("PAGE_META order 缺失或非数字")
    if 'from "/view/lib/' not in js:
        missing.append("缺绝对路径 import /view/lib/*")
    if re.search(r'from\s+["\']\.\.?/', js):
        missing.append("存在相对路径 import（必须全为绝对路径 /view/lib/*）")
    if re.search(r"svc\(\s*(?![\"'])", js):
        missing.append("存在非字面量 svc 调用（变量/三元拼名）")
    if re.search(r"\bthis\.", js):
        missing.append("误用 this.（应一律 self.）")
    if "Alpine.reactive" not in js:
        missing.append("缺 Alpine.reactive（裸对象不触发重渲染）")
    tpl = "dashboard.html" if is_dashboard else "view.html"
    if f'new URL("{tpl}"' not in js:
        missing.append(f'模板抓取名应为 new URL("{tpl}", import.meta.url)')
    if is_dashboard:
        n_svc = len(re.findall(r"svc\(", js))
        n_quiet = len(re.findall(r"quiet\s*:\s*true", js))
        if n_svc == 0:
            missing.append("看板缺 svc 探测")
        elif n_quiet < n_svc:
            missing.append(f"看板探测性加载必须全部 quiet（当前 {n_quiet}/{n_svc}）")
    return missing


def _check_fcode_html(html: str, is_dashboard: bool = False) -> list:
    """门禁：view.html 机检（非空 + Alpine 指令）；dashboard 追加 KPI/管道/待办区块关键词。"""
    missing = []
    if not html or len(html.strip()) < 200:
        missing.append("模板内容过短（<200 字符），疑输出截断")
    elif "x-" not in html:
        missing.append("缺 Alpine 指令（x-data/x-show/x-for/x-text …）")
    if is_dashboard:
        for kw in ("KPI", "管道", "待办"):
            if kw not in html:
                missing.append(f"看板模板缺区块「{kw}」")
    return missing


def _node_check(code: str) -> str | None:
    """软依赖 node --check：环境无 node → 返回 None（调用方记 warn 跳过）；语法错 → 返回错误文本。"""
    node = shutil.which("node")
    if not node:
        return None
    tmp = tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False)
    try:
        tmp.write(code)
        tmp.close()
        r = subprocess.run([node, "--check", tmp.name], capture_output=True,
                           text=True, timeout=30)
        if r.returncode == 0:
            return None
        return (r.stderr or r.stdout or "node --check 失败").strip()[:400]
    except Exception as e:
        return f"node --check 执行异常：{e}"
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def node_gather_fcode(state: FcodeState) -> dict:
    """收集第⑩步输入：规格四件（前端编码/VIEW_CONVENTION/patterns/pitfalls）+ 契约（硬屏障）
    + 逐目标应用前端详设（硬屏障）+ 组级 前端详设/dashboard.md（硬屏障，dashboard 单元主输入）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gather")
    groupbuild_store.append_log(task_id, "gather：读取前端编码规格 / 视图约定 / 代码骨架 / 踩坑清单 / 契约 / 前端详设…")

    spec = FCODE_SPEC.read_text(encoding="utf-8") if FCODE_SPEC.is_file() else ""
    if not spec:
        raise RuntimeError("缺少技能规格文件：design/前端编码.md")
    convention = VIEW_CONVENTION.read_text(encoding="utf-8") if VIEW_CONVENTION.is_file() else ""
    if not convention:
        raise RuntimeError("缺少前端视图约定正本：design/VIEW_CONVENTION.md")
    patterns = VIEW_PATTERNS.read_text(encoding="utf-8") if VIEW_PATTERNS.is_file() else ""
    if not patterns:
        raise RuntimeError("缺少前端代码骨架：design/view-convention/patterns.md")
    pitfalls = VIEW_PITFALLS.read_text(encoding="utf-8") if VIEW_PITFALLS.is_file() else ""

    contracts_path = APPS_DIR / group / "_contracts.md"
    if not contracts_path.is_file():
        raise RuntimeError(f"缺少 app/{group}/_contracts.md，请先运行『契约冻结』（⑧，前端段依赖屏障）。")
    contracts = contracts_path.read_text(encoding="utf-8")

    dashboard_design_path = APPS_DIR / group / "前端详设" / "dashboard.md"
    if not dashboard_design_path.is_file():
        raise RuntimeError(f"缺少 app/{group}/前端详设/dashboard.md，请先运行『前端详设』（⑨）。")
    dashboard_design = dashboard_design_path.read_text(encoding="utf-8")

    group_dir = APPS_DIR / group
    all_apps = (sorted(d.name for d in group_dir.iterdir()
                       if d.is_dir() and (d / "前端详设.md").is_file()
                       and not d.name.startswith("."))
                if group_dir.is_dir() else [])
    targets = state.get("target_apps") or []
    apps = [a for a in targets if a in set(all_apps)] if targets else all_apps
    if not apps:
        raise RuntimeError(f"app/{group} 下没有任何含 前端详设.md 的应用（请先运行『前端详设』⑨）。")
    fdesign_map = {a: (group_dir / a / "前端详设.md").read_text(encoding="utf-8") for a in apps}

    node_note = "" if shutil.which("node") else " 注意：当前环境无 node，node --check 软检将跳过。"
    groupbuild_store.append_log(
        task_id, f"gather 完成：规格 {len(spec)} 字；契约 {len(contracts)} 字；"
                 f"目标应用 {len(apps)} 个 + 1 dashboard 单元。" + node_note)
    return {"spec": spec, "convention": convention, "patterns": patterns, "pitfalls": pitfalls,
            "contracts": contracts, "dashboard_design": dashboard_design,
            "fdesign_map": fdesign_map, "target_apps": apps}


def node_fcode_apps(state: FcodeState) -> dict:
    """单元 = 应用 + dashboard 同池摊平并发；单元内 js→html 两阶段串行（html 注入定稿 js），
    每阶段门禁 + 修复 ≤_FCODE_REPAIR 轮；js 失败 → 该单元失败（html 跳过）；失败记日志、全败 raise。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gen")
    spec, convention, patterns = state["spec"], state["convention"], state["patterns"]
    pitfalls, contracts = state.get("pitfalls") or "", state["contracts"]
    fdesign_map, dashboard_design = state["fdesign_map"], state["dashboard_design"]
    apps = list(fdesign_map.keys())
    groupbuild_store.append_log(
        task_id, f"gen：{len(apps)} 个应用单元 + 1 dashboard 单元摊平并发（单元内 js→html 两阶段）…")

    def _gen_stage(system: str, user: str, check, unit: str, stage: str):
        """单阶段生成 + 门禁修复回路（≤_FCODE_REPAIR 轮，usr_fix 尾追加式）。返回 (code, problems)。"""
        code = _chat(system, user)
        problems = check(code)
        retries = 0
        while problems and retries < _FCODE_REPAIR:
            retries += 1
            groupbuild_store.append_log(
                task_id, f"gen 门禁重出 {unit}/{stage}（第 {retries} 轮）：{'；'.join(problems)}")
            code = _chat(system, user +
                         f"\n\n【门禁反馈】上一版问题：{'；'.join(problems)}。请修正后输出完整文件。")
            problems = check(code)
        return code, problems

    def gen_unit(unit: str):
        """生成一个单元（app 或 'dashboard'）：先 js 后 html。返回 (unit, js, html, problems)。"""
        is_dash = unit == "dashboard"
        if is_dash:
            design = dashboard_design
            contract_block = f"## 契约全文（_contracts.md，各应用 svc 签名）\n{contracts}"
            check_js = lambda c: _check_fcode_js(c, unit, True)   # noqa: E731
        else:
            design = fdesign_map[unit]
            slice_ = _contracts_slice(contracts, unit)
            if not slice_:
                return unit, "", "", ["契约无本应用节（_contracts.md 缺 ## " + unit + "）"]
            contract_block = f"## 本应用契约（字段真相 · 复核详设字段）\n{slice_}"
            check_js = lambda c: _check_fcode_js(c, unit, False)  # noqa: E731
        fname_js = "dashboard.js" if is_dash else "view.js"
        fname_html = "dashboard.html" if is_dash else "view.html"
        target_cn = "组级首页看板（dashboard）" if is_dash else f"应用 {unit}"
        # ── 阶段 1：js ──
        system_js = (f"{_FCODE_PREAMBLE}\n\n===== 规格全文（design/前端编码.md）=====\n{spec}\n\n"
                     f"===== 前端视图约定正本（design/VIEW_CONVENTION.md）=====\n{convention}\n\n"
                     f"===== 前端代码骨架（design/view-convention/patterns.md）=====\n{patterns}\n\n"
                     f"===== 前端踩坑清单（design/view-convention/pitfalls.md，逐项对照）=====\n{pitfalls}")
        user_js = (f"# 为应用组 {group} 的{target_cn}生成 {fname_js}\n\n"
                   f"{contract_block}\n\n"
                   f"## 前端详设（主输入：PAGE_META / 区块构成 / svc 字面量清单 / 字段映射 / 交互要点）\n"
                   f"{design}\n\n"
                   f"只输出 {fname_js} 的完整代码（PAGE_META 取值照详设 §1 给定；默认导出工厂；"
                   f"Alpine.reactive 体）。")
        js, problems = _gen_stage(system_js, user_js, check_js, unit, "js")
        if problems:
            return unit, "", "", [f"js：{'；'.join(problems)}"]
        err = _node_check(js)
        if err:
            if err.startswith("node --check 执行异常") or shutil.which("node") is None:
                groupbuild_store.append_log(task_id, f"gen 提示 {unit}/js：{err}")
            else:
                # 语法错 → 再修一轮（不计入 _FCODE_REPAIR 门禁轮，属硬错补救）
                groupbuild_store.append_log(task_id, f"gen node --check 报错 {unit}/js：{err[:200]}")
                js2 = _chat(system_js, user_js +
                            f"\n\n【node --check 报错】{err}\n请修正语法后输出完整 view.js。")
                if not _check_fcode_js(js2, unit, is_dash) and not _node_check(js2):
                    js = js2
        # ── 阶段 2：html（注入定稿 js，字段/状态名严格对齐）──
        system_html = (f"{_FCODE_PREAMBLE}\n\n"
                       f"===== 前端视图约定正本（design/VIEW_CONVENTION.md）=====\n{convention}\n\n"
                       f"===== 前端代码骨架（design/view-convention/patterns.md）=====\n{patterns}")
        user_html = (f"# 为应用组 {group} 的{target_cn}生成 {fname_html}\n\n"
                     f"{contract_block}\n\n"
                     f"## 前端详设（区块构成 / 字段映射 / 交互要点）\n{design}\n\n"
                     f"## 定稿 {fname_js}（模板必须与其状态、方法、字段名严格对齐）\n"
                     f"```javascript\n{js}\n```\n\n"
                     f"只输出 {fname_html} 的完整代码（Alpine 模板片段：按详设 §2 落列表 / 详情模态 / 表单）。")
        html, problems = _gen_stage(system_html, user_html,
                                    lambda c: _check_fcode_html(c, is_dash), unit, "html")
        return unit, js, html, ([f"html：{'；'.join(problems)}"] if problems else [])

    js_map, html_map, dashboard_js, dashboard_html, failed = {}, {}, "", "", []
    jobs = apps + ["dashboard"]
    with ThreadPoolExecutor(max_workers=min(len(jobs), _FCODE_PARALLEL)) as ex:
        futs = {ex.submit(gen_unit, u): u for u in jobs}
        for fut in futs:
            unit = futs[fut]
            try:
                _u, js, html, problems = fut.result()
            except TaskCancelled:
                raise
            except Exception as e:
                failed.append(unit)
                groupbuild_store.append_log(task_id, f"gen 失败 {unit}：{str(e)[:200]}")
                continue
            if not js or not html or problems:
                failed.append(unit)
                groupbuild_store.append_log(
                    task_id, f"gen 不完整 {unit}：{'；'.join(problems)[:200]}")
                continue
            if unit == "dashboard":
                dashboard_js, dashboard_html = js, html
            else:
                js_map[unit], html_map[unit] = js, html
            groupbuild_store.append_log(
                task_id, f"gen 完成 {unit}（js {len(js.splitlines())} 行 / "
                         f"html {len(html.splitlines())} 行）。")
    if not js_map and not dashboard_js:
        raise RuntimeError("前端编码生成全部失败（详见日志）。")
    groupbuild_store.append_log(
        task_id, f"gen 汇总：应用 {len(js_map)}/{len(apps)} 单元 + dashboard "
                 f"{'1' if dashboard_js else '0'} 单元；失败：{', '.join(failed) if failed else '无'}。")
    return {"js_map": js_map, "html_map": html_map,
            "dashboard_js": dashboard_js, "dashboard_html": dashboard_html,
            "failed_apps": failed}


def node_write_fcode(state: FcodeState) -> dict:
    """落盘真实树：逐应用 app/<组>/<应用>/view.{js,html} + 组级 view/<组>/dashboard.{js,html}（零接线）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="write")
    written = []
    html_map = state.get("html_map") or {}
    for app, js in (state.get("js_map") or {}).items():
        base = APPS_DIR / group / app
        base.mkdir(parents=True, exist_ok=True)
        (base / "view.js").write_text(js, encoding="utf-8")
        (base / "view.html").write_text(html_map.get(app, ""), encoding="utf-8")
        written.append(f"{app}/view.*")
    if state.get("dashboard_js"):
        base = VIEW_DIR / group
        base.mkdir(parents=True, exist_ok=True)
        (base / "dashboard.js").write_text(state["dashboard_js"], encoding="utf-8")
        (base / "dashboard.html").write_text(state.get("dashboard_html") or "", encoding="utf-8")
        written.append(f"view/{group}/dashboard.*")
    failed = state.get("failed_apps") or []
    groupbuild_store.append_log(
        task_id, f"write：{len(written)} 个单元落盘（{', '.join(written)}）——文件落盘即进"
                 f"菜单/路由与授权清单（零接线，浏览器刷新生效）"
                 + (f"；失败跳过：{', '.join(failed)}" if failed else "") + "。")
    return {}


# ── ⑪前端测试用例（逐应用 + 组级补充；规格 design/前端测试.md）────

_FTEST_PREAMBLE = (
    "你是 FDE 平台的「前端测试用例生成」技能（九步法第⑧步），为应用组生成结构化前端视图测试用例。铁律：\n"
    "- **只生成用例（数据/文档），不生成脚本、不运行测试**——用例文件是第⑨步执行器的唯一接口；\n"
    "- 每条用例必含**五要素**：页面（`<组>:<页key>`）/ 前置造数（`应用.服务(参数)`，服务名参数名**以 _contracts.md 逐字为准**，不臆造）/ "
    "操作（浏览器动作序列）/ 断言（**可机器校验**：文本包含/计数/集合相等/0 报错，不写「页面正常显示」类模糊结论）/ 选择器注意（按需，照 pitfalls 规避）；\n"
    "- **六类断言按两级分派**：逐应用文件覆盖 §0 自足字典（含跨应用前置造数）/ §1 本页渲染（非看板页 `.kpi`==0 防粘滞）/ §2 造数后列表有数据"
    "（精确单号 has_text 定位）/ §3 模态全字段（详设 §2.2 字段标签逐项）/ §4 表单落库回显（详设 §2.3 可写集；无写服务的应用注明豁免）/ §6 本会话 0 报错红线；"
    "组级补充文件覆盖 §1 壳启动与菜单序（逐 key+order 写死序列）/ dashboard 页断言 / §5 受限用户菜单收敛（授权清单与页面集**逐字对应**，pitfalls #38）/ §6；\n"
    "- 用例编号：逐应用文件内 `VT-<段>-<序号>`（VT-ROUTE/VT-LIST/VT-MODAL/VT-FORM，文件作用域）；组级文件 `VT-SHELL-*`/`VT-DASH-*`/`VT-PERM-*`；\n"
    "- 造数走真实 REST（浏览器内 fetch，pitfalls #18），字典标识前后一致；**customer.list 返回 {rows}，其余应用 list 返回 {items}**（下拉映射据此）。\n"
    "输出要求：只输出结构化 Markdown 正文本身（数据用 markdown 表格），**不要用 ``` 代码围栏包裹整篇**；头部三行声明（产出技能/页面/输入与执行交接）。")


def _ftest_menu_meta(fdesign_map: dict, dashboard_design: str) -> str:
    """从各应用前端详设 §1 PAGE_META 提取 key/name/order，拼组级用例的菜单序总表依据。"""
    lines = []
    for app, doc in sorted(fdesign_map.items()):
        head = "\n".join(doc.splitlines()[:60])
        order_m = re.search(r"order\s*[=|:]\s*`?(\d+)", head)
        name_m = (re.search(r"name\s*[=|:]\s*`?([^`|\n]+?)`?\s*[\n|]", head)
                  or re.search(r"页面[^·\n]*·\s*([^\n（(]+)", head))
        order = order_m.group(1) if order_m else "?"
        name = (name_m.group(1).strip() if name_m else app)
        lines.append(f"- {app}：order={order}，菜单名={name}")
    if dashboard_design:
        head = "\n".join(dashboard_design.splitlines()[:60])
        order_m = re.search(r"order\s*[=|:]\s*`?(\d+)", head)
        lines.insert(0, f"- dashboard：order={order_m.group(1) if order_m else '10'}，菜单名=首页看板（组级看板，menu[0]）")
    return "\n".join(lines)


def _check_ftest_complete(doc: str, is_group: bool = False) -> list:
    """门禁：返回缺失项清单（空=通过）。逐应用查六类断言节 + VT 编号 + 五要素标记；
    组级补充查 VT-SHELL/VT-DASH/VT-PERM + 受限授权清单。整篇围栏包裹视为不合格。"""
    missing = []
    if doc.lstrip().startswith("```"):
        missing.append("整篇被代码围栏包裹（规格禁止）")
    if "VT-" not in doc:
        missing.append("缺 VT- 用例编号")
    if is_group:
        for kw in ("VT-SHELL", "VT-DASH", "VT-PERM"):
            if kw not in doc:
                missing.append(f"组级缺用例段「{kw}」")
        if "limited_role" not in doc:
            missing.append("组级缺受限角色授权清单（limited_role）")
        if "order" not in doc:
            missing.append("组级缺菜单序（order）断言")
    else:
        for kw in ("数据字典", "渲染", "列表", "模态"):
            if kw not in doc:
                missing.append(f"缺断言类「{kw}」")
        if "§6" not in doc and "0 报错" not in doc and "三零" not in doc:
            missing.append("缺 §6 0 报错红线")
        for kw in ("造数", "操作", "断言"):
            if kw not in doc:
                missing.append(f"五要素缺「{kw}」")
    return missing


def node_gather_ftest(state: FtestState) -> dict:
    """收集第⑪步输入：规格 + pitfalls + 契约（硬屏障）+ 逐目标前端详设（硬屏障）
    + 组级输入（前端详设/dashboard.md 必备 + 各 §1 PAGE_META 摘录）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gather")
    groupbuild_store.append_log(task_id, "gather：读取前端测试规格 / 选择器规则 / 契约 / 前端详设…")

    spec = FTEST_SPEC.read_text(encoding="utf-8") if FTEST_SPEC.is_file() else ""
    if not spec:
        raise RuntimeError("缺少技能规格文件：design/前端测试.md")
    pitfalls = VIEW_PITFALLS.read_text(encoding="utf-8") if VIEW_PITFALLS.is_file() else ""

    contracts_path = APPS_DIR / group / "_contracts.md"
    if not contracts_path.is_file():
        raise RuntimeError(f"缺少 app/{group}/_contracts.md，请先运行『契约冻结』（⑧，前端段依赖屏障）。")
    contracts = contracts_path.read_text(encoding="utf-8")

    dashboard_design_path = APPS_DIR / group / "前端详设" / "dashboard.md"
    if not dashboard_design_path.is_file():
        raise RuntimeError(f"缺少 app/{group}/前端详设/dashboard.md，请先运行『前端详设』（⑨，组级补充用例依赖）。")
    dashboard_design = dashboard_design_path.read_text(encoding="utf-8")

    group_dir = APPS_DIR / group
    all_apps = (sorted(d.name for d in group_dir.iterdir()
                       if d.is_dir() and (d / "前端详设.md").is_file()
                       and not d.name.startswith("."))
                if group_dir.is_dir() else [])
    targets = state.get("target_apps") or []
    apps = [a for a in targets if a in set(all_apps)] if targets else all_apps
    if not apps:
        raise RuntimeError(f"app/{group} 下没有任何含 前端详设.md 的应用（请先运行『前端详设』⑨）。")
    fdesign_map = {a: (group_dir / a / "前端详设.md").read_text(encoding="utf-8") for a in apps}

    menu_meta = _ftest_menu_meta(fdesign_map, dashboard_design)
    groupbuild_store.append_log(
        task_id, f"gather 完成：规格 {len(spec)} 字；契约 {len(contracts)} 字；"
                 f"目标应用 {len(apps)} 个 + 1 组级补充单元。")
    return {"spec": spec, "pitfalls": pitfalls, "contracts": contracts,
            "dashboard_design": dashboard_design, "menu_meta": menu_meta,
            "fdesign_map": fdesign_map, "target_apps": apps}


def node_ftest_apps(state: FtestState) -> dict:
    """N 个应用 job + 1 个组级补充 job 同池摊平并发；门禁不过 → 整份重出 ≤_FTEST_REPAIR 轮；
    失败单元跳过记日志、全败 raise。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gen")
    spec, pitfalls = state["spec"], state.get("pitfalls") or ""
    contracts = state["contracts"]
    dashboard_design, menu_meta = state["dashboard_design"], state.get("menu_meta") or ""
    fdesign_map = state["fdesign_map"]
    apps = list(fdesign_map.keys())
    groupbuild_store.append_log(task_id, f"gen：{len(apps)} 个应用 job + 1 组级补充 job 摊平并发…")

    def gen_one(app: str):
        """生成单份用例（app 或 '_group'），返回 (app, doc, problems)。"""
        is_group = app == "_group"
        system = (f"{_FTEST_PREAMBLE}\n\n===== 规格全文（design/前端测试.md）=====\n{spec}\n\n"
                  f"===== 选择器与红线规则（design/view-convention/pitfalls.md）=====\n{pitfalls}")
        if is_group:
            user = (f"# 为应用组 {group} 产出**组级补充**前端测试用例（app/{group}/前端测试用例.md）\n\n"
                    f"本文件只覆盖组级维度：壳启动与菜单序 / dashboard 页 / 受限用户菜单收敛 / 组级会话 0 报错；"
                    f"逐应用的渲染/列表/模态/表单断言在各自 app/{group}/<应用>/前端测试用例.md，**不要写进本文件**。\n\n"
                    f"## 全组 PAGE_META 菜单序总表（VT-SHELL 菜单序断言据此逐字写死）\n{menu_meta}\n\n"
                    f"## 组级看板前端详设（VT-DASH 断言依据）\n{dashboard_design}\n\n"
                    f"## 契约（组级字典最小集与受限页造数依据）\n{contracts[:6000]}\n\n"
                    f"按规格的组级骨架输出：§0 组级最小字典 / §1 VT-SHELL（品牌 + 菜单集合 + order 逐字序列）"
                    f"+ VT-DASH（看板区块断言）/ §5 VT-PERM 三连（授权清单 limited_role → [组:dashboard, 组:<选定应用页>, _platform:agent]，"
                    f"菜单收敛 + 直访回落菜单首项 + 隐式放行有数据）/ §6 三零红线（受限 403 豁免）。只输出文档。")
        else:
            slice_ = _contracts_slice(contracts, app)
            if not slice_:
                return app, "", ["契约无本应用节（_contracts.md 缺 ## " + app + "）"]
            user = (f"# 为应用组 {group} 的应用 {app} 产出前端测试用例（app/{group}/{app}/前端测试用例.md）\n\n"
                    f"## 本应用契约（造数服务名/参数名/返回形状·逐字为准）\n{slice_}\n\n"
                    f"## 本应用前端详设（主输入：§2 区块 / §2.2 详情字段 / §2.3 表单可写集 / §3 svc 清单 / §6 验收关注点）\n"
                    f"{fdesign_map[app]}\n\n"
                    f"按规格的逐应用骨架输出：头部三行 + §0 自足字典（含跨应用前置造数）+ §1 VT-ROUTE（防粘滞）"
                    f"+ §2 VT-LIST（造数后列表有数据 + 过滤抽样）+ §3 VT-MODAL（§2.2 字段标签逐项）"
                    f"+ §4 VT-FORM（§2.3 可写集；无写服务则注明豁免）+ §6 三零红线。只输出文档。")
        doc = _chat(system, user)
        problems = _check_ftest_complete(doc, is_group)
        retries = 0
        while problems and retries < _FTEST_REPAIR:
            retries += 1
            groupbuild_store.append_log(
                task_id, f"gen 门禁重出 {app}（第 {retries} 轮）：{'；'.join(problems)}")
            doc = _chat(system, user + f"\n\n【门禁反馈】上一版产出缺失：{'；'.join(problems)}。请补齐后输出完整文档。")
            problems = _check_ftest_complete(doc, is_group)
        return app, doc, problems

    ftest_docs, group_doc, failed = {}, "", []
    jobs = apps + ["_group"]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(len(jobs), _FTEST_PARALLEL)) as ex:
        futs = {ex.submit(gen_one, a): a for a in jobs}
        for fut in futs:
            app = futs[fut]
            try:
                _app, doc, problems = fut.result()
            except TaskCancelled:
                raise
            except Exception as e:
                failed.append(app)
                groupbuild_store.append_log(task_id, f"gen 失败 {app}：{str(e)[:200]}")
                continue
            if not doc or problems:
                failed.append(app)
                groupbuild_store.append_log(
                    task_id, f"gen 不完整 {app}：{'；'.join(problems)[:200]}")
                continue
            if app == "_group":
                group_doc = doc
            else:
                ftest_docs[app] = doc
            groupbuild_store.append_log(task_id, f"gen 完成 {app}（{len(doc.splitlines())} 行）。")
    if not ftest_docs and not group_doc:
        raise RuntimeError("前端测试用例生成全部失败（详见日志）。")
    groupbuild_store.append_log(
        task_id, f"gen 汇总：应用 {len(ftest_docs)}/{len(apps)} 份 + 组级补充 "
                 f"{'1' if group_doc else '0'} 份；失败：{', '.join(failed) if failed else '无'}。")
    return {"ftest_docs": ftest_docs, "group_doc": group_doc, "failed_apps": failed}


def node_write_ftest(state: FtestState) -> dict:
    """落盘真实树：逐应用 app/<组>/<应用>/前端测试用例.md + 组级补充 app/<组>/前端测试用例.md。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="write")
    written = []
    for app, doc in (state.get("ftest_docs") or {}).items():
        out = APPS_DIR / group / app / "前端测试用例.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc, encoding="utf-8")
        written.append(f"{app}/前端测试用例.md")
    if state.get("group_doc"):
        out = APPS_DIR / group / "前端测试用例.md"
        out.write_text(state["group_doc"], encoding="utf-8")
        written.append("前端测试用例.md（组级补充）")
    failed = state.get("failed_apps") or []
    groupbuild_store.append_log(
        task_id, f"write：{len(written)} 份落盘（{', '.join(written)}）"
                 + (f"；失败跳过：{', '.join(failed)}" if failed else "") + "。")
    return {}


# ── ⑫前端测试执行（用例 → playwright 脚本，串行真跑 + 逐脚本修复；规格 design/前端测试执行.md）────

_FVERIFY_PREAMBLE = (
    "你是 FDE 平台的「前端测试执行」技能（九步法第⑨步），把前端测试用例翻译成**可直接运行**的 playwright 验收脚本。铁律：\n"
    "- **基建段照抄范式**（路径锚定 ROOT / dbguard isolate_dbs().__enter__ + atexit 还原 / 动态空闲端口 subprocess 起 main.py / "
    "wait_up / 无头 chromium / admin 登录 form POST admin/admin / console·pageerror·response(≥400) 三收集器且 favicon 豁免）——"
    "与范式 `design/前端验收样板/verify_view_e2e.py` 逐段同构，只把业务断言换成本组用例；\n"
    "- 逐用例翻成 `step(\"VT-XXX 名称\")` 顺序执行；造数走浏览器内 `page.evaluate` fetch 真实 REST"
    "（`/api/apps/demo/<应用>/call/<服务>` 组限定路径；**customer.list 返回 {rows}，其余应用 list 返回 {items}**）；\n"
    "- 选择器规避照 pitfalls：隐藏≠不存在用 `:visible` 限定（原生 select 收起态 option 恒 hidden，等 attached 不等 visible）、"
    "多 `.modal-bd` 取 `.first`、`wait_modal` 轮询 `.loadbox` 消失、精确单号 `has_text`、`.collapse` 折叠用 `.open` 标记类判据（max-height 裁剪下 :visible 失效）；\n"
    "- 收尾 `assert` 三收集器为空后 `print(\"verify_view_<名> PASS —— …\")`；`__main__` 捕获 AssertionError → `print(f\"FAIL @ {STEP}: {e}\")` + `sys.exit(1)`；\n"
    "- **只写脚本、不改任何 app/view 代码**；断言忠实于用例，不弱化。若判断失败会来自真实前端/后端 bug 而非脚本错，保持忠实断言并在脚本头注释注明 TRIAGE 去向。\n"
    "输出要求：只输出一个完整 Python 脚本本身（可含必要注释），用单个 ```python 围栏包裹。")


def _view_script_name(group: str, unit: str) -> str:
    """单元脚本文件名：逐应用 verify_view_<组>_<应用>.py；组级 verify_view_<组>.py。"""
    return f"verify_view_{group}.py" if unit == "_group" else f"verify_view_{group}_{unit}.py"


def _check_fverify_script(code: str) -> list:
    """门禁：语法可编译 + 含 PASS 打印骨架 + 用了 dbguard 隔离 + 用了范式基建标记。"""
    missing = []
    try:
        ast.parse(code)
    except SyntaxError as e:
        return [f"语法错误（第 {e.lineno} 行：{e.msg}）"]
    if "PASS" not in code:
        missing.append("缺 PASS 打印骨架（收尾 print(\"verify_view_… PASS\")）")
    if "FAIL @" not in code:
        missing.append("缺 FAIL @ STEP 失败定位打印")
    if "isolate_dbs" not in code:
        missing.append("缺 dbguard isolate_dbs 隔离（运行会污染真实数据）")
    if "sync_playwright" not in code:
        missing.append("缺 playwright 启动（sync_playwright）")
    return missing


def node_gather_fverify(state: FverifyState) -> dict:
    """收集第⑫步输入：规格 + 范式 + pitfalls + 逐目标前端测试用例（硬屏障）+ 组级用例（硬屏障）
    + playwright 可导入探测（不可用 → 失败带安装命令）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gather")
    groupbuild_store.append_log(task_id, "gather：读取执行规格 / 范式 / 选择器规则 / 前端测试用例…")

    spec = FVERIFY_SPEC.read_text(encoding="utf-8") if FVERIFY_SPEC.is_file() else ""
    if not spec:
        raise RuntimeError("缺少技能规格文件：design/前端测试执行.md")
    paradigm = VIEW_VERIFY_PARADIGM.read_text(encoding="utf-8") if VIEW_VERIFY_PARADIGM.is_file() else ""
    if not paradigm:
        raise RuntimeError(f"缺少脚本范式：{VIEW_VERIFY_PARADIGM}（组级形态范式，基建段照抄依据）。")
    pitfalls = VIEW_PITFALLS.read_text(encoding="utf-8") if VIEW_PITFALLS.is_file() else ""

    try:
        import importlib
        importlib.import_module("playwright")
    except ImportError:
        raise RuntimeError("未安装 playwright：pip install playwright && python -m playwright install chromium")

    group_dir = APPS_DIR / group
    group_case_path = group_dir / "前端测试用例.md"
    if not group_case_path.is_file():
        raise RuntimeError(f"缺少组级补充用例 app/{group}/前端测试用例.md，请先运行『前端测试』（⑪）。")
    group_case = group_case_path.read_text(encoding="utf-8")

    all_apps = (sorted(d.name for d in group_dir.iterdir()
                       if d.is_dir() and (d / "前端测试用例.md").is_file()
                       and not d.name.startswith("."))
                if group_dir.is_dir() else [])
    targets = state.get("target_apps") or []
    apps = [a for a in targets if a in set(all_apps)] if targets else all_apps
    if not apps:
        raise RuntimeError(f"app/{group} 下没有任何含 前端测试用例.md 的应用（请先运行『前端测试』⑪）。")
    case_map = {a: (group_dir / a / "前端测试用例.md").read_text(encoding="utf-8") for a in apps}

    groupbuild_store.append_log(
        task_id, f"gather 完成：范式 {len(paradigm)} 字；目标应用 {len(apps)} 个 + 1 组级脚本；playwright 可用。")
    return {"spec": spec, "paradigm": paradigm, "pitfalls": pitfalls,
            "group_case": group_case, "case_map": case_map, "target_apps": apps}


def node_gen_fverify(state: FverifyState) -> dict:
    """N 个应用脚本 + 1 个组级脚本同池摊平生成；门禁（语法 + 骨架）不过 → 整份重出 ≤_FVERIFY_REPAIR 轮；
    失败单元跳过记日志、全败 raise。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gen")
    spec, paradigm, pitfalls = state["spec"], state["paradigm"], state.get("pitfalls") or ""
    case_map, group_case = state["case_map"], state["group_case"]
    units = list(case_map.keys())
    groupbuild_store.append_log(task_id, f"gen：{len(units)} 个应用脚本 + 1 组级脚本摊平生成…")

    def gen_one(unit: str):
        is_group = unit == "_group"
        script_name = _view_script_name(group, unit)
        case_text = group_case if is_group else case_map[unit]
        system = (f"{_FVERIFY_PREAMBLE}\n\n===== 执行规格要点（design/前端测试执行.md，摘要见下全文）=====\n{spec[:9000]}\n\n"
                  f"===== 脚本范式全文（design/前端验收样板/verify_view_e2e.py，基建段照抄）=====\n{paradigm}\n\n"
                  f"===== 选择器与红线规则（design/view-convention/pitfalls.md）=====\n{pitfalls}")
        kind_cn = "组级脚本（壳/菜单序/dashboard/受限用户/0报错）" if is_group else f"应用 {unit} 的逐页验收脚本"
        user = (f"# 为应用组 {group} 生成 {kind_cn}：app/{group}/tests/{script_name}\n\n"
                f"## 本脚本的测试用例（唯一测试设计来源，逐条翻成 step 断言）\n{case_text}\n\n"
                f"脚本自包含：dbguard 隔离 + 动态端口起平台子进程 + admin 登录 + 造数 + 逐用例断言 + 三收集器 0 报错收尾；"
                f"PASS 打印文案用 `verify_view_{group}{'' if is_group else '_' + unit} PASS`。只输出脚本。")

        def gen_split(fix_note: str = "") -> str:
            """两段分段生成（每段流长减半，规避网关超长流空响应；同第③步分段先例）。
            1/2 = 头部 + 基建 + 造数（止于造数）；2/2 = 步骤断言 + main + 入口（给定前半续写）。"""
            a = _strip_code_fences(_chat(system, user + fix_note +
                "\n\n【分段生成 1/2】只输出脚本**前半**：import / 常量 / 基建段（隔离 / 动态端口起平台子进程 / "
                "登录 / 三收集器 / step 与各 helper）/ 造数段。**造数段写完即止**——不要输出任何用例步骤断言，"
                "不要输出 main() 与 __main__ 入口。"))
            b = _strip_code_fences(_chat(system, user + fix_note +
                "\n\n【分段生成 2/2】前半已生成（附后）。**只输出剩余部分**：各用例 step 断言 + main() + "
                "__main__ 失败入口（FAIL @ + exit(1)）。不要重复 import / 常量 / 基建函数 / 造数段，"
                f"直接从步骤部分开始续写。\n\n===== 前半（勿重复，自此之后续写）=====\n```python\n{a}\n```"))
            return a + "\n\n" + b

        code = gen_split()
        problems = _check_fverify_script(code)
        retries = 0
        while problems and retries < _FVERIFY_REPAIR:
            retries += 1
            groupbuild_store.append_log(
                task_id, f"gen 门禁重出 {unit}（第 {retries} 轮）：{'；'.join(problems)}")
            code = gen_split(fix_note=f"\n\n【门禁反馈】上一版脚本问题：{'；'.join(problems)}。请修正后输出。")
            problems = _check_fverify_script(code)
        return unit, code, problems

    script_map, failed = {}, []
    jobs = units + ["_group"]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(len(jobs), _FVERIFY_PARALLEL)) as ex:
        futs = {ex.submit(gen_one, u): u for u in jobs}
        for fut in futs:
            unit = futs[fut]
            try:
                _u, code, problems = fut.result()
            except TaskCancelled:
                raise
            except Exception as e:
                failed.append(unit)
                groupbuild_store.append_log(task_id, f"gen 失败 {unit}：{str(e)[:200]}")
                continue
            if not code or problems:
                failed.append(unit)
                groupbuild_store.append_log(
                    task_id, f"gen 未过门禁 {unit}：{'；'.join(problems)[:200]}")
                continue
            script_map[unit] = code
            groupbuild_store.append_log(task_id, f"gen 完成 {unit}（{len(code.splitlines())} 行）。")
    if not script_map:
        raise RuntimeError("前端测试脚本生成全部失败（详见日志）。")
    groupbuild_store.append_log(
        task_id, f"gen 汇总：{len(script_map)}/{len(jobs)} 个脚本过门禁；失败：{', '.join(failed) if failed else '无'}。")
    return {"script_map": script_map, "failed_apps": failed}


def _persist_view_scripts(group: str, script_map: dict) -> None:
    """脚本落盘 app/<组>/tests/（每轮运行前先落，含修复后版本）。"""
    tests_dir = APPS_DIR / group / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    for unit, code in script_map.items():
        (tests_dir / _view_script_name(group, unit)).write_text(code, encoding="utf-8")


def _run_view_script(group: str, unit: str) -> dict:
    """真实树 subprocess 直跑视图验收脚本（动态端口子进程 + dbguard 隔离由脚本自理）。
    verdict：rc==0 且输出含 PASS → PASS；否则 FAIL（failed_step 取 FAIL @/ERROR @ 行）。"""
    script = (APPS_DIR / group / "tests" / _view_script_name(group, unit)).resolve()
    env = dict(os.environ)
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "SAP_BASE_URL", "MOM_BASE_URL",
              "WMS_BASE_URL", "MDM_BASE_URL", "APS_BASE_URL", "CTCT_BASE_URL"):
        env.pop(k, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # 脚本自起的平台子进程不得启 groupbuild worker（否则续跑本任务、与主 worker 并行执行同一任务）；
    # 经脚本 env 传播到其内部 main.py 子进程（register() 的 FDE_NO_WORKER 守卫消费）。
    env["FDE_NO_WORKER"] = "1"
    try:
        proc = subprocess.Popen([sys.executable, str(script)], cwd=str(PROJECT_ROOT), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
    except Exception as e:
        return {"verdict": "FAIL", "rc": 1, "timed_out": False,
                "failed_step": f"脚本启动失败：{e}", "output_tail": str(e)}
    buf = []

    def _reader():
        for line in proc.stdout:
            buf.append(line)

    rt = threading.Thread(target=_reader, daemon=True)
    rt.start()
    start = time.time()
    timed_out = False
    while proc.poll() is None:
        if _cancel_flagged():
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
            rt.join(timeout=5)
            raise TaskCancelled("任务已被用户终止（视图验收运行中止）")
        if time.time() - start > _FVERIFY_RUN_TIMEOUT:
            proc.kill()
            timed_out = True
            break
        time.sleep(1)
    rt.join(timeout=5)
    out = "".join(buf)
    if timed_out:
        out += f"\n（运行超时，已终止（>{_FVERIFY_RUN_TIMEOUT}s））"
    rc = proc.returncode if proc.returncode is not None else 1
    verdict = "PASS" if (rc == 0 and "PASS" in out) else "FAIL"
    fs = re.search(r"(?:FAIL|ERROR) @ (.+)", out)
    return {"verdict": verdict, "rc": rc, "timed_out": timed_out,
            "failed_step": fs.group(1).strip()[:200] if fs else "",
            "output_tail": out[-_TESTEXEC_OUTPUT_TAIL:]}


def node_run_fverify(state: FverifyState) -> dict:
    """脚本落盘 app/<组>/tests/ → 逐脚本**串行**真跑（dbguard 锁天然互斥）；单脚本失败 → LLM 修脚本重跑
    ≤_FVERIFY_REPAIR 轮（错误签名去重提前终止）；单脚本失败不阻断后续（partial 入报告），全败 raise。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="run")
    script_map = dict(state.get("script_map") or {})
    if not script_map:
        raise RuntimeError("无可运行脚本：gen 未产出")
    case_map, group_case = state.get("case_map") or {}, state.get("group_case") or ""
    pitfalls = state.get("pitfalls") or ""
    paradigm = state.get("paradigm") or ""
    # 运行序：逐应用先（主链序）、组级后
    units = [u for u in script_map if u != "_group"] + (["_group"] if "_group" in script_map else [])
    results = {}
    for unit in units:
        _check_cancel(task_id)
        script_name = _view_script_name(group, unit)
        case_text = group_case if unit == "_group" else case_map.get(unit, "")
        last_sig, verdict = None, "FAIL"
        for attempt in range(_FVERIFY_REPAIR + 1):
            _check_cancel(task_id)
            _persist_view_scripts(group, {unit: script_map[unit]})
            res = _run_view_script(group, unit)
            verdict = res["verdict"]
            groupbuild_store.append_log(
                task_id, f"run {script_name} 第 {attempt + 1} 轮：{verdict}"
                         + (f" @ {res['failed_step']}" if res["failed_step"] else ""))
            results[unit] = {"verdict": verdict, "rounds": attempt + 1,
                             "failed_step": res["failed_step"], "output_tail": res["output_tail"]}
            if verdict == "PASS" or attempt >= _FVERIFY_REPAIR:
                break
            sig = (res["failed_step"], res["output_tail"][-300:])
            if sig == last_sig:
                groupbuild_store.append_log(task_id, f"run {script_name} 修复终止：连续两轮错误签名相同。")
                break
            last_sig = sig
            fix_note = ("\n\n【修复上下文】上一版脚本运行失败（多为脚本级问题：选择器/时机/造数入参形态；"
                        "若你判断是真实前端/后端 bug，请保持忠实断言并在头注释注明 TRIAGE 去向，不要弱化断言强过）。\n"
                        f"失败步：{res['failed_step'] or '（未定位）'}\n"
                        f"运行输出（尾部）：\n```\n{res['output_tail']}\n```\n"
                        f"请对照用例 + 范式 + pitfalls 修复脚本后输出完整脚本。")
            groupbuild_store.append_log(task_id, f"run {script_name} LLM 修复重生成…")
            try:
                system = (f"{_FVERIFY_PREAMBLE}\n\n===== 脚本范式全文 =====\n{paradigm}\n\n"
                          f"===== pitfalls =====\n{pitfalls}")
                user = (f"# 修复应用组 {group} 的验收脚本 app/{group}/tests/{script_name}\n\n"
                        f"## 对应用例\n{case_text[:12000]}\n\n## 当前脚本\n```python\n{script_map[unit]}\n```"
                        + fix_note)
                new_code = _strip_code_fences(_chat(system, user))
            except Exception as e:
                groupbuild_store.append_log(task_id, f"run {script_name} 修复重生成失败：{str(e)[:200]}")
                break
            probs = _check_fverify_script(new_code)
            if probs:
                groupbuild_store.append_log(
                    task_id, f"run {script_name} 修复终止：重生成仍未过门禁：{'；'.join(probs)[:200]}")
                break
            if new_code == script_map[unit]:
                groupbuild_store.append_log(task_id, f"run {script_name} 修复终止：输出与原脚本一致。")
                break
            script_map[unit] = new_code
    _persist_view_scripts(group, script_map)
    passed = [u for u, r in results.items() if r["verdict"] == "PASS"]
    if not passed:
        raise RuntimeError("前端测试执行全部脚本失败（详见日志与报告）。")
    groupbuild_store.append_log(
        task_id, f"run 汇总：{len(passed)}/{len(units)} 个脚本 PASS"
                 + (f"；未绿：{', '.join(u for u in units if results[u]['verdict'] != 'PASS')}"
                    if len(passed) < len(units) else "（全绿）"))
    return {"script_map": script_map, "results": results}


def _render_fverify_report(group: str, name_cn: str, results: dict) -> str:
    """拼装 app/<组>/tests/前端测试报告.md（逐脚本 verdict + 失败定位 + triage 去向）。"""
    from datetime import datetime
    units = [u for u in results if u != "_group"] + (["_group"] if "_group" in results else [])
    n_pass = sum(1 for u in units if results[u]["verdict"] == "PASS")
    all_pass = n_pass == len(units)
    lines = [
        f"# 应用组 `{group}` 前端测试执行报告{('（' + name_cn + '）') if name_cn else ''}",
        "",
        "> 产出技能：前端测试执行（第⑨步，规格 `design/前端测试执行.md`，平台自动化任务 kind=fverify）。",
        f"> 脚本：`app/{group}/tests/verify_view_{group}_<应用>.py`（逐应用）+ `app/{group}/tests/verify_view_{group}.py`（组级），可手动重跑。",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- **最终判据**：{'✅ 全部脚本 PASS ∧ 各会话 0 报错' if all_pass else f'⚠️ {n_pass}/{len(units)} 个脚本 PASS（未绿脚本见下表，失败已 triage 定位）'}",
        "- **隔离语义**：dbguard 移走真实库运行、退出还原——用户数据零污染。",
        "",
        "## 逐脚本结果", "",
        "| 脚本 | 结果 | 轮数 | 失败步 / 备注 |", "|---|---|---|---|",
    ]
    for u in units:
        r = results[u]
        name = _view_script_name(group, u)
        verdict = "✅ PASS" if r["verdict"] == "PASS" else "❌ FAIL"
        note = r.get("failed_step") or "—"
        lines.append(f"| `{name}` | {verdict} | {r.get('rounds', 1)} | {note[:120]} |")
    failed_units = [u for u in units if results[u]["verdict"] != "PASS"]
    if failed_units:
        lines += ["", "## 未绿脚本失败尾摘（triage：脚本错已自动修 ≤2 轮；前端/后端 bug 需回 ⑦/③ 步修复后重跑）", ""]
        for u in failed_units:
            lines += [f"### {_view_script_name(group, u)}", "",
                      "```", (results[u].get('output_tail') or '')[-1500:], "```", ""]
    return "\n".join(lines) + "\n"


def node_write_fverify(state: FverifyState) -> dict:
    """落盘报告 app/<组>/tests/前端测试报告.md（脚本已在 run 段落盘 app/<组>/tests/）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="write")
    results = state.get("results") or {}
    if not results:
        raise RuntimeError("无运行结果：run 未产出")
    report = _render_fverify_report(group, state.get("name_cn") or "", results)
    out_dir = APPS_DIR / group / "tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "前端测试报告.md"
    out.write_text(report, encoding="utf-8")
    n_pass = sum(1 for r in results.values() if r["verdict"] == "PASS")
    groupbuild_store.append_log(
        task_id, f"write 完成 → app/{group}/tests/verify_view_{group}_*.py + app/{group}/tests/前端测试报告.md"
                 f"（{n_pass}/{len(results)} PASS）。")
    return {}


# ── 第⑤步回路：BUG 修复（提案 → 批准 → 应用 → 重测对账）────
# 铁律：LLM 只提案（old→new 精确替换对），人批准后平台才落码；可改范围仅 app/<组>/ 下文件。

_BUGFIX_PREAMBLE = (
    "你是 FDE 平台的「BUG 修复」技能（第⑤步测试执行的回路步），负责对联通测试的失败用例**逐条** "
    "triage 归类并**提出**最小修复方案（本技能只提案；落地须经人工批准）。铁律：\n"
    "- triage 三分类：**app_bug**（应用代码真实缺陷：校验缺失 / 状态机错 / 跨应用契约不符）→ 对目标应用 "
    "`.py` 提出 old→new 替换；**case_calibration**（测试用例的数据 / 步骤 / 期望措辞与应用真实契约不符）"
    "→ 对《测试用例.md》提出回填替换；**design_issue**（设计层缺陷，非单文件可修）→ 不出 old/new，"
    "rationale 说明需人工修订详设；\n"
    "- **跨应用契约不符一律改调用方**（被调方签名是冻结契约，不让被调方迁就调用方）；\n"
    "- 修改必须是**最小单处**；old 必须从给出的当前文件内容里**逐字拷贝**（含缩进 / 换行 / 中文标点），"
    "严禁整文件重写、严禁臆造不存在的片段；\n"
    "- 改应用代码依据给出的数据契约（建表必填列）与服务签名，不猜字段名；\n"
    "- 严格输出**单个 JSON 对象**（不要 ``` 围栏、不要解释文字）："
    "{\"category\": \"app_bug|case_calibration|design_issue\", "
    "\"target_file\": \"<应用>/<应用>.py 或 测试用例.md（design_issue 留空）\", "
    "\"old\": \"原文\", \"new\": \"新文\", \"rationale\": \"根因 + 方案\", \"risk\": \"一行风险注记\"}。\n"
)


# 提案任务状态
class BugfixState(TypedDict, total=False):
    task_id: int
    group: str
    name_cn: str
    spec: str               # design/BUG修复.md 规格全文
    entries: list           # 失败例 [{tc, note, ctx}]（ctx = 用例块 + 相关应用当前代码摘录）
    signatures: str         # 服务签名摘要
    contracts_digest: str   # 数据契约摘要
    proposed_count: int
    error: str


# 应用任务状态
class BugfixApplyState(TypedDict, total=False):
    task_id: int
    group: str
    name_cn: str
    applied_ids: list       # 落码成功的提案 id
    retest_task_id: int     # 自动派生的重测 testexec 任务 id
    error: str


def _report_failed_entries(report_md: str) -> list:
    """从 测试报告.md 的逐例结果表抽未通过用例 [{tc, note}]（表头/分隔行天然不匹配）。"""
    out = []
    for m in re.finditer(r"^\|\s*(.+?)\s*\|\s*✗\s*\|\s*(.*?)\s*\|\s*$", report_md, re.M):
        tc = m.group(1).strip()
        if tc in ("用例", "") or set(tc) <= set("-: "):
            continue
        out.append({"tc": tc, "note": m.group(2).strip()})
    return out


def _testcase_block(testcase_md: str, tc_id: str) -> str:
    """取《测试用例.md》中指定 TC 编号的用例块（到下一条用例 / 章节标题为止）。"""
    lines = testcase_md.split("\n")
    out, cap = [], False
    for ln in lines:
        if ln.lstrip().startswith("- **"):
            if cap:
                break
            cap = tc_id in ln
        elif cap and re.match(r"^#{1,3}\s", ln):
            break
        if cap:
            out.append(ln)
    return "\n".join(out).strip()


def _entry_apps(block: str) -> list:
    """从用例块推断涉及的应用名（`call(\"app\",...)` 与 `app.service(...)` 两种写法）。"""
    apps = set(re.findall(r'call\(\s*"([A-Za-z_][\w/]*)"', block))
    apps |= set(re.findall(r"(?<![.\w])([a-z][a-z0-9_]*)\.[a-z][a-z0-9_]*\(", block))
    apps -= {"call", "self", "expect_err", "lambda", "print", "str", "dict", "len",
             "step", "record", "assert", "get", "items"}
    return sorted(apps)


def _parse_proposal_json(text: str) -> dict:
    """解析 LLM 提案输出（容忍偶发 ``` 围栏与前后缀文字，取首尾大括号间 JSON）。"""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("未找到 JSON 对象")
    return json.loads(t[start:end + 1])


def node_gather_bugfix(state: BugfixState) -> dict:
    """收集失败例 + 逐例上下文（用例块 + 涉及应用当前代码 + 签名 / 数据契约）。
    无未通过用例 → 无需修复（失败退出并说明）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="gather")
    groupbuild_store.append_log(task_id, "gather：读取测试报告失败例与相关应用代码 / 契约…")

    spec = BUGFIX_SPEC.read_text(encoding="utf-8") if BUGFIX_SPEC.is_file() else ""
    if not spec:
        raise RuntimeError("缺少技能规格文件：design/BUG修复.md")

    report_path = APPS_DIR / group / "tests" / f"测试报告_{group}.md"
    if not report_path.is_file():
        raise RuntimeError(f"缺少 app/{group}/tests/测试报告_{group}.md，请先运行『测试执行』（第⑤步）。")
    failed = _report_failed_entries(report_path.read_text(encoding="utf-8"))
    if not failed:
        raise RuntimeError("测试报告无未通过用例——无需生成修复提案。")

    tc_path = APPS_DIR / group / "测试用例.md"
    testcase_md = tc_path.read_text(encoding="utf-8") if tc_path.is_file() else ""
    group_dir = APPS_DIR / group
    present = (sorted(d.name for d in group_dir.iterdir()
                      if d.is_dir() and (d / f"{d.name}.py").is_file())
               if group_dir.is_dir() else [])

    entries = []
    for f in failed:
        tc_id = f["tc"].split()[0]
        block = _testcase_block(testcase_md, tc_id) if testcase_md else ""
        apps_in = [a for a in _entry_apps(block or (f["tc"] + " " + f["note"])) if a in present]
        src_parts = []
        for a in apps_in:
            src = (group_dir / a / f"{a}.py").read_text(encoding="utf-8")
            src_parts.append(f"### 应用 {a} 当前代码（`{a}/{a}.py`）\n```python\n{src[:12000]}\n```")
        ctx = (f"## 失败用例：{f['tc']}\n测试报告备注：{f['note']}\n\n"
               f"## 《测试用例.md》对应用例块\n{block or '（未找到）'}\n\n"
               + "\n\n".join(src_parts))
        entries.append({"tc": f["tc"], "note": f["note"], "apps": apps_in, "ctx": ctx})

    name_cn = state.get("name_cn") or ""
    if not name_cn:
        g = groupbuild_store.get_group(group)
        name_cn = (g or {}).get("name_cn", "") if g else ""

    groupbuild_store.append_log(
        task_id, f"gather 完成：失败例 {len(entries)} 条，涉及应用 "
                 f"{sorted({a for e in entries for a in e['apps']}) or '（未识别）'}。")
    return {"spec": spec, "entries": entries, "name_cn": name_cn,
            "signatures": _signatures_digest(group, present),
            "contracts_digest": _app_data_contracts(group, present)}


def node_propose_bugfix(state: BugfixState) -> dict:
    """逐失败例 LLM 提案（并发 ≤_BUGFIX_PARALLEL）→ 落 bugfix_proposals 表（pending 待批准）。
    只提案、不碰任何代码文件。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="propose")
    entries = state.get("entries") or []
    spec = state.get("spec") or ""
    shared = (f"## 数据契约（各应用建表字段；（必填）列必须随写入提供）\n"
              f"{state.get('contracts_digest') or '（无）'}\n\n"
              f"## 各应用服务签名\n{state.get('signatures') or '（无）'}")
    groupbuild_store.append_log(
        task_id, f"propose：逐例生成修复提案（{len(entries)} 条失败例，并发≤{_BUGFIX_PARALLEL}）…")

    def one(entry):
        user = (f"应用组：{group}（{state.get('name_cn') or ''}）\n\n## 共享上下文\n{shared}\n\n"
                f"{entry['ctx']}\n\n请对该失败例 triage 并输出提案 JSON。")
        try:
            raw = _chat(_BUGFIX_PREAMBLE + "\n\n===== 规格（design/BUG修复.md）=====\n" + spec, user)
            return entry["tc"], _parse_proposal_json(raw), None
        except Exception as e:
            return entry["tc"], None, str(e)[:200]

    n_ok = 0
    workers = max(1, min(len(entries), _BUGFIX_PARALLEL))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for tc, obj, err in ex.map(one, entries):
            _check_cancel(task_id)
            if err:
                groupbuild_store.append_log(task_id, f"提案 {tc} 生成失败：{err}")
                continue
            cat = obj.get("category")
            if cat not in ("app_bug", "case_calibration", "design_issue"):
                groupbuild_store.append_log(
                    task_id, f"提案 {tc} 类别未知（{cat}），按 design_issue 记录")
                cat = "design_issue"
            pid = groupbuild_store.add_proposal(
                task_id, group, tc, cat,
                target_file=(obj.get("target_file") or "") if cat != "design_issue" else "",
                old_text=obj.get("old") or "", new_text=obj.get("new") or "",
                rationale=obj.get("rationale") or "", risk=obj.get("risk") or "")
            n_ok += 1
            groupbuild_store.append_log(
                task_id, f"提案 #{pid} ← {tc} [{cat}] → "
                         f"{obj.get('target_file') or '（设计层，需人工）'}")
    if n_ok == 0:
        raise RuntimeError("全部修复提案生成失败")
    groupbuild_store.append_log(task_id, f"propose 完成：{n_ok} 条提案待批准。")
    return {"proposed_count": n_ok}


def node_write_bugfix(state: BugfixState) -> dict:
    """渲染 app/<组>/test/修复提案.md（本任务产生的全部提案，供页面批准 / 人工审阅）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="write")
    props = [p for p in groupbuild_store.list_proposals(group) if p["task_id"] == task_id]
    lines = [f"# 应用组 `{group}` BUG 修复提案", "",
             "> 产出：第⑤步回路「BUG 修复」（规格 `design/BUG修复.md`）。**仅提案**——在 /groupbuild "
             "页面⑦测试执行块逐条批准后，由「应用已批准并重测」落码并自动重测。", ""]
    for p in props:
        lines += [f"## 提案 #{p['id']} · {p['entry_ref']} · `{p['category']}`", "",
                  f"- **目标文件**：`{p['target_file'] or '（设计层问题，需人工修订详设）'}`",
                  f"- **根因 / 方案**：{p['rationale'] or '—'}",
                  f"- **风险**：{p['risk'] or '—'}", ""]
        if p["old_text"]:
            lines += ["原文：", "```", p["old_text"], "```", "新文：", "```",
                      p["new_text"], "```", ""]
    out = APPS_DIR / group / "tests"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"修复提案_{group}.md").write_text("\n".join(lines), encoding="utf-8")
    groupbuild_store.append_log(task_id, f"write 完成 → app/{group}/tests/修复提案_{group}.md（{len(props)} 条）。")
    return {}


def _safe_target(group: str, target_file: str):
    """target_file 解析到 app/<组>/ 内的现存文件；越界 / 不存在 → None。"""
    base = (APPS_DIR / group).resolve()
    t = (base / (target_file or "")).resolve()
    if not t.is_relative_to(base) or not t.is_file():
        return None
    return t


def node_apply_bugfix(state: BugfixApplyState) -> dict:
    """落码已批准提案：白名单校验 + 备份 + 逐字精确替换 + .py 语法门（不过即失败、原文件不动）。
    备份在 app/<组>/.bugfix_backup/<时间戳>/（人工可还原）。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="apply")
    props = groupbuild_store.list_proposals(group, status="approved")
    if not props:
        raise RuntimeError("没有已批准的提案——请先在页面逐条批准。")
    # design_issue = 设计层问题、无可应用代码：转「待人工处理」（不计应用失败；
    # 正常路径在批准时即转 manual，此处兜底历史遗留的 approved design_issue）
    design = [p for p in props if p["category"] == "design_issue"]
    for p in design:
        groupbuild_store.set_proposal_status(p["id"], "manual")
        groupbuild_store.append_log(
            task_id, f"#{p['id']}（{p['entry_ref']}）为设计层问题（design_issue），无可应用代码 → 转待人工处理")
    props = [p for p in props if p["category"] != "design_issue"]
    if not props:
        groupbuild_store.append_log(
            task_id, "已批准提案均为设计层问题（已转待人工处理）；未改码、不派生重测。")
        return {"applied_ids": []}
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak_dir = APPS_DIR / group / ".bugfix_backup" / ts
    applied, failed = [], []
    for p in props:
        _check_cancel(task_id)
        t = _safe_target(group, p["target_file"])
        if t is None:
            groupbuild_store.set_proposal_status(p["id"], "failed")
            failed.append(p["id"])
            groupbuild_store.append_log(
                task_id, f"#{p['id']} 应用失败：目标文件越界或不存在（{p['target_file']}）")
            continue
        src = t.read_text(encoding="utf-8")
        if p["old_text"] not in src:
            groupbuild_store.set_proposal_status(p["id"], "failed")
            failed.append(p["id"])
            groupbuild_store.append_log(
                task_id, f"#{p['id']} 应用失败：原文未逐字匹配（文件或已变化），请重新生成提案")
            continue
        rel = t.relative_to(APPS_DIR / group)
        bp = bak_dir / rel
        bp.parent.mkdir(parents=True, exist_ok=True)
        if not bp.exists():
            bp.write_text(src, encoding="utf-8")   # 备份（每文件一次）
        new_src = src.replace(p["old_text"], p["new_text"], 1)
        if t.suffix == ".py":
            try:
                ast.parse(new_src)
            except SyntaxError as e:
                groupbuild_store.set_proposal_status(p["id"], "failed")
                failed.append(p["id"])
                groupbuild_store.append_log(
                    task_id, f"#{p['id']} 应用失败：替换后语法错（{e.msg} @ 行 {e.lineno}），原文件未动")
                continue
        t.write_text(new_src, encoding="utf-8")
        groupbuild_store.set_proposal_status(p["id"], "applied")
        applied.append(p["id"])
        groupbuild_store.append_log(task_id, f"#{p['id']} 已应用 → {p['target_file']}")
    if applied:
        try:
            proc = subprocess.run([sys.executable, "-m", "fde_platform.scanner"],
                                  cwd=str(PROJECT_ROOT), capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=120)
            tail = ((proc.stdout or "") + (proc.stderr or ""))[-300:].strip()
            groupbuild_store.append_log(
                task_id, f"scanner {'通过' if proc.returncode == 0 else '警告（跨应用调用检查报问题，请核实）'}"
                         + (f"：{tail}" if tail else ""))
        except Exception as e:
            groupbuild_store.append_log(task_id, f"scanner 运行失败（忽略）：{e}")
    if not applied:
        raise RuntimeError(f"全部提案应用失败（提案 id：{failed}）")
    groupbuild_store.append_log(
        task_id, f"apply 完成：应用 {len(applied)} 条、失败 {len(failed)} 条；原文件备份于 {bak_dir}")
    return {"applied_ids": applied}


def node_spawn_retest(state: BugfixApplyState) -> dict:
    """派生一次 testexec 重测任务（worker 串行，本任务结束后自动运行）。未改码则跳过。"""
    task_id, group = state["task_id"], state["group"]
    groupbuild_store.update_task(task_id, current_step="retest")
    if not state.get("applied_ids"):
        groupbuild_store.append_log(task_id, "无已应用提案（未改码），跳过重测。")
        return {}
    tid = groupbuild_store.create_task(group, created_by="bugfix-apply", kind="testexec")
    enqueue(tid)
    groupbuild_store.append_log(
        task_id, f"已派生重测任务 #{tid}（测试执行：重新生成脚本并运行，跑完自动对账消项）。")
    return {"retest_task_id": tid}


def _tick_bugs_md(path: Path, toks: list) -> None:
    """BUGS.md 里命中的失败条目行打 ✅（已修复）。"""
    if not path.is_file():
        return
    out = []
    for ln in path.read_text(encoding="utf-8").split("\n"):
        hit = (ln.lstrip().startswith("- ") and not ln.lstrip().startswith("- ✅")
               and any(t in ln for t in toks))
        out.append(ln.replace("- ", "- ✅ ", 1) if hit else ln)
    path.write_text("\n".join(out), encoding="utf-8")


def _build_bugfix_graph() -> StateGraph:
    """⑤回路·提案任务图：gather → propose → write。"""
    g = StateGraph(BugfixState)
    for n, fn in [("gather", node_gather_bugfix), ("propose", node_propose_bugfix),
                  ("write", node_write_bugfix)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "gather")
    g.add_edge("gather", "propose")
    g.add_edge("propose", "write")
    g.add_edge("write", END)
    return g


def _build_bugfix_apply_graph() -> StateGraph:
    """⑤回路·应用任务图：apply → retest（派生 testexec 重测）。"""
    g = StateGraph(BugfixApplyState)
    for n, fn in [("apply", node_apply_bugfix), ("retest", node_spawn_retest)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "apply")
    g.add_edge("apply", "retest")
    g.add_edge("retest", END)
    return g


# ── 文本解析 / 校验辅助 ─────────────────────────────────

def _strip_fences(text: str) -> str:
    """剥离模型偶发把整篇包进 ``` / ```markdown / ```md 的外壳围栏。

    仅当首行恰是裸 ``` 或 markdown/md 外壳时才剥；```mermaid 等**语义围栏**保留。
    """
    t = text.strip()
    first = t.split("\n", 1)[0].strip() if t else ""
    if first in ("```", "```markdown", "```md"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _strip_dup_relation_heading(md: str) -> str:
    """node_assemble 已给③段套了 `## 聚合关系图` 外层标题；若模型又自带一个含
    『关系图』的开篇标题，剥掉它（及其后空行），避免大纲出现重复的 `## 聚合关系图`。
    仅剥**首个**标题，且仅当其文本含『关系图』——关键设计决策 / 待确认等正常标题保留。"""
    lines = md.strip().splitlines()
    if lines:
        m = _HEADING.match(lines[0].strip())
        if m and "关系图" in m.group(2):
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines = lines[1:]
    return "\n".join(lines).strip()


_APP_NAME_CELL = re.compile(r"`([a-z][a-z0-9_]*)`")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _normalize_card(card: str) -> str:
    """归一单张卡的标题层级，确保嵌进文档后大纲干净：

    - 卡内**第一个**标题 → 强制三级 `###`（卡主标题）；
    - 其余标题若低于四级（# / ## / ###）→ 提为四级 `####`；已 ≥#### 的保留。
    这样卡内小节绝不会与文档顶层 `## ①②③` 冲突。
    """
    out, titled = [], False
    for line in card.splitlines():
        m = _HEADING.match(line)
        if not m:
            out.append(line)
            continue
        level, text = len(m.group(1)), m.group(2)
        if not titled:
            out.append(f"### {text}")
            titled = True
        else:
            out.append(f"{'#' * max(level, 4)} {text}")
    return "\n".join(out)


def _table_app_names(doc: str) -> list:
    """从聚合根清单总表（markdown 表格，第 3 列=应用名）抽出所有英文应用名（保序、去重）。"""
    names = []
    for line in doc.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        m = _APP_NAME_CELL.fullmatch(cells[2])   # 第 3 列须恰为 `snake_case`
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return names


_H2 = re.compile(r"^##\s+(.*)$")


def _table_rows(arch_md: str) -> list:
    """从聚合根清单总表解析各行：{app, name_cn, cls, id, is_master}（第3列应用名须为 `snake_case`）。

    is_master 取第 7 列『是否主数据』（缺列视为非主数据）；表头行因第 3 列非 snake_case 自动跳过。"""
    rows = []
    for line in arch_md.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 6:
            continue
        m = _APP_NAME_CELL.fullmatch(cells[2])
        if not m:
            continue
        master_cell = cells[6] if len(cells) > 6 else ""
        rows.append({"app": m.group(1), "name_cn": cells[1],
                     "cls": cells[3].strip("`"), "defn": cells[4], "id": cells[5].strip("`"),
                     "is_master": any(k in master_cell for k in ("是", "主", "✓", "√", "✅", "☑", "Y", "y"))})
    return rows


def arch_app_names(group: str) -> list:
    """读 app/<组>/architecture.md 总表，返回聚合根应用名清单（架构缺失/无总表 → 空）。"""
    p = APPS_DIR / group / "architecture.md"
    if not p.is_file():
        return []
    try:
        return [r["app"] for r in _table_rows(p.read_text(encoding="utf-8"))]
    except Exception:
        return []


def _arch_section(arch_md: str, title_kw: str) -> str:
    """取标题含 title_kw 的 ## 节正文（到下一个 ## 之前）。"""
    out, cap = [], False
    for line in arch_md.splitlines():
        m = _H2.match(line)
        if m:
            if cap:
                break
            cap = title_kw in m.group(1)
            continue
        if cap:
            out.append(line)
    return "\n".join(out).strip()


def _split_arch_cards(arch_md: str, app_names: list) -> dict:
    """从『② 聚合根卡』区按 ### 切块，并按应用名归类（标题命中优先，其次正文）。"""
    section = _arch_section(arch_md, "聚合根卡")
    chunks, cur = [], None
    for line in section.splitlines():
        if line.startswith("### "):
            if cur is not None:
                chunks.append(cur)
            cur = [line]
        elif cur is not None:
            cur.append(line)
    if cur is not None:
        chunks.append(cur)
    chunks = ["\n".join(c) for c in chunks]
    cards = {}
    for app in app_names:
        best, best_score = None, 0
        pat = re.compile(rf"(?<![a-z0-9_]){re.escape(app)}(?![a-z0-9_])")
        for ch in chunks:
            head = ch.splitlines()[0] if ch else ""
            score = 0
            if app in head:
                score += 3
            if f"`{app}`" in ch:
                score += 2
            if pat.search(ch):
                score += 1
            if score > best_score:
                best_score, best = score, ch
        if best and best_score > 0:
            cards[app] = best
    return cards


def _build_shared(arch_md: str) -> str:
    """抽取全组共享上下文：总表 / 关系图 / 关键设计决策 / 待确认。"""
    def sec(kw, title):
        body = _arch_section(arch_md, kw)
        return f"## {title}\n{body}" if body else ""
    parts = [sec("聚合根清单总表", "全组聚合根清单总表"),
             sec("聚合关系图", "聚合关系图"),
             sec("关键设计决策", "关键设计决策"),
             sec("待确认", "待确认")]
    return "\n\n".join(p for p in parts if p)


def _extract_section(md: str, keyword: str, cap: int = 0) -> str:
    """抽取标题含 keyword 的**首个**小节正文（含其标题），到下一个同级/上级标题为止。

    按标题关键词匹配（不依赖章节编号），容忍 LLM 生成详设的编号/格式波动；cap>0 时截断。"""
    lines = md.splitlines()
    out, cap_level = [], None
    for line in lines:
        m = _HEADING.match(line)
        if m:
            level, text = len(m.group(1)), m.group(2)
            if cap_level is not None and level <= cap_level:
                break                      # 下一同级/上级标题 → 本节结束
            if cap_level is None and keyword in text:
                cap_level = level
                out.append(line)
                continue
        if cap_level is not None:
            out.append(line)
    sec = "\n".join(out).strip()
    return sec[:cap] if cap and len(sec) > cap else sec


def _detail_test_digest(detail_md: str, include_func: bool, sec_cap: int = 3500) -> str:
    """从一份应用详设抽取**测试相关段**（BR / 状态机 / [功能] / 外部依赖），丢弃用例用不到的
    prose（需求概览 / 用户故事 / 权限 / 验收 / 参考）——既瘦身又提高信噪比。

    include_func=True 时含功能描述（服务名 + 字段表；主数据应用或无 _contracts.md 时需要）；
    有 _contracts.md 的非主数据应用可省功能段（签名以契约为准）。抽不到任何段 → 回退截断全文保底。"""
    parts = []
    for kw in ("业务规则", "状态机"):
        sec = _extract_section(detail_md, kw, cap=sec_cap)
        if sec:
            parts.append(sec)
    if include_func:
        func = (_extract_section(detail_md, "功能描述", cap=sec_cap)
                or _extract_section(detail_md, "功能清单", cap=sec_cap))
        if func:
            parts.append(func)
    ext = _extract_section(detail_md, "外部依赖", cap=1500)
    if ext:
        parts.append(ext)
    digest = "\n\n".join(parts).strip()
    return digest or detail_md[:_DETAIL_EXCERPT]


def _check_completeness(doc: str) -> list:
    """产出完整性闸门：返回缺失项清单（空=合格）。对应规格输出结构 ①②③。"""
    missing = []
    if "关系图" not in doc and "```mermaid" not in doc:
        missing.append("聚合关系图")
    for name in _table_app_names(doc):
        if doc.count(f"`{name}`") < 2:   # 总表 1 次 + 卡至少 1 次；缺卡则仅 1 次
            missing.append(name)
    return missing


def _build_graph() -> StateGraph:
    g = StateGraph(GroupBuildState)
    for n, fn in [("gather", node_gather), ("outline", node_outline), ("cards", node_cards),
                  ("relations", node_relations), ("assemble", node_assemble), ("write", node_write)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "gather")
    for a, b in [("gather", "outline"), ("outline", "cards"), ("cards", "relations"),
                 ("relations", "assemble"), ("assemble", "write")]:
        g.add_edge(a, b)
    g.add_edge("write", END)
    return g


def _build_design_graph() -> StateGraph:
    """第②步图：gather → design → write（逐聚合根分段详设）。"""
    g = StateGraph(DesignState)
    for n, fn in [("gather", node_gather_design), ("design", node_design_apps), ("write", node_write_design)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "gather")
    g.add_edge("gather", "design")
    g.add_edge("design", "write")
    g.add_edge("write", END)
    return g


def _build_code_graph() -> StateGraph:
    """第③步图：gather → code → write（逐聚合根分段编码 + 静态门禁）。"""
    g = StateGraph(CodeState)
    for n, fn in [("gather", node_gather_code), ("code", node_code_apps), ("write", node_write_code)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "gather")
    g.add_edge("gather", "code")
    g.add_edge("code", "write")
    g.add_edge("write", END)
    return g


def _build_testcase_graph() -> StateGraph:
    """第④步图：gather → gen → write（整组测试用例：数据字典先行 + 主链/分支并发）。"""
    g = StateGraph(TestCaseState)
    for n, fn in [("gather", node_gather_testcase), ("gen", node_gen_testcase), ("write", node_write_testcase)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "gather")
    g.add_edge("gather", "gen")
    g.add_edge("gen", "write")
    g.add_edge("write", END)
    return g


def _build_testexec_graph() -> StateGraph:
    """第⑤步图：gather → gen → run → write（脚本生成 → 真实树运行 + 修复回路 → 报告）。"""
    g = StateGraph(TestExecState)
    for n, fn in [("gather", node_gather_testexec), ("gen", node_gen_testexec),
                  ("run", node_run_testexec), ("write", node_write_testexec)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "gather")
    g.add_edge("gather", "gen")
    g.add_edge("gen", "run")
    g.add_edge("run", "write")
    g.add_edge("write", END)
    return g


def _build_contracts_graph() -> StateGraph:
    """⑧契约冻结图：gather → run → write（沙箱 dump，无 LLM、无修复回路）。"""
    g = StateGraph(ContractsState)
    for n, fn in [("gather", node_gather_contracts), ("run", node_run_contracts),
                  ("write", node_write_contracts)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "gather")
    g.add_edge("gather", "run")
    g.add_edge("run", "write")
    g.add_edge("write", END)
    return g


def _build_fdesign_graph() -> StateGraph:
    """⑨前端详设图：gather → gen → write（逐应用扇出 + dashboard job + 门禁重生成）。"""
    g = StateGraph(FdesignState)
    for n, fn in [("gather", node_gather_fdesign), ("gen", node_fdesign_apps),
                  ("write", node_write_fdesign)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "gather")
    g.add_edge("gather", "gen")
    g.add_edge("gen", "write")
    g.add_edge("write", END)
    return g


def _build_fcode_graph() -> StateGraph:
    """⑩前端编码图：gather → gen → write（单元 js→html 两阶段 + 确定性门禁）。"""
    g = StateGraph(FcodeState)
    for n, fn in [("gather", node_gather_fcode), ("gen", node_fcode_apps),
                  ("write", node_write_fcode)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "gather")
    g.add_edge("gather", "gen")
    g.add_edge("gen", "write")
    g.add_edge("write", END)
    return g


def _build_ftest_graph() -> StateGraph:
    """⑪前端测试用例图：gather → gen → write（逐应用 + 组级补充摊平 + 门禁重生成）。"""
    g = StateGraph(FtestState)
    for n, fn in [("gather", node_gather_ftest), ("gen", node_ftest_apps),
                  ("write", node_write_ftest)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "gather")
    g.add_edge("gather", "gen")
    g.add_edge("gen", "write")
    g.add_edge("write", END)
    return g


def _build_fverify_graph() -> StateGraph:
    """⑫前端测试执行图：gather → gen → run → write（生成 + 串行真跑 + 逐脚本修复 + 报告）。"""
    g = StateGraph(FverifyState)
    for n, fn in [("gather", node_gather_fverify), ("gen", node_gen_fverify),
                  ("run", node_run_fverify), ("write", node_write_fverify)]:
        g.add_node(n, _cancel_guard(fn))
    g.add_edge(START, "gather")
    g.add_edge("gather", "gen")
    g.add_edge("gen", "run")
    g.add_edge("run", "write")
    g.add_edge("write", END)
    return g


# ── 后台 worker（单线程串行；断点续跑）──────────────────

_graph = None
_design_graph = None
_code_graph = None
_testcase_graph = None
_testexec_graph = None
_bugfix_graph = None
_bugfix_apply_graph = None
_contracts_graph = None
_fdesign_graph = None
_fcode_graph = None
_ftest_graph = None
_fverify_graph = None
_queue: "queue.Queue[int]" = queue.Queue()
_started = False
_lock = threading.Lock()


def _get_graph():
    global _graph
    if _graph is None:
        conn = sqlite3.connect(str(GRAPH_DB), check_same_thread=False)
        _graph = _build_graph().compile(checkpointer=SqliteSaver(conn))
    return _graph


def _get_design_graph():
    global _design_graph
    if _design_graph is None:
        conn = sqlite3.connect(str(GRAPH_DB_DESIGN), check_same_thread=False)
        _design_graph = _build_design_graph().compile(checkpointer=SqliteSaver(conn))
    return _design_graph


def _get_code_graph():
    global _code_graph
    if _code_graph is None:
        conn = sqlite3.connect(str(GRAPH_DB_CODE), check_same_thread=False)
        _code_graph = _build_code_graph().compile(checkpointer=SqliteSaver(conn))
    return _code_graph


def _get_testcase_graph():
    global _testcase_graph
    if _testcase_graph is None:
        conn = sqlite3.connect(str(GRAPH_DB_TESTCASE), check_same_thread=False)
        _testcase_graph = _build_testcase_graph().compile(checkpointer=SqliteSaver(conn))
    return _testcase_graph


def _get_testexec_graph():
    global _testexec_graph
    if _testexec_graph is None:
        conn = sqlite3.connect(str(GRAPH_DB_TESTEXEC), check_same_thread=False)
        _testexec_graph = _build_testexec_graph().compile(checkpointer=SqliteSaver(conn))
    return _testexec_graph


def _get_bugfix_graph():
    global _bugfix_graph
    if _bugfix_graph is None:
        conn = sqlite3.connect(str(GRAPH_DB_BUGFIX), check_same_thread=False)
        _bugfix_graph = _build_bugfix_graph().compile(checkpointer=SqliteSaver(conn))
    return _bugfix_graph


def _get_bugfix_apply_graph():
    global _bugfix_apply_graph
    if _bugfix_apply_graph is None:
        conn = sqlite3.connect(str(GRAPH_DB_BUGFIX_APPLY), check_same_thread=False)
        _bugfix_apply_graph = _build_bugfix_apply_graph().compile(checkpointer=SqliteSaver(conn))
    return _bugfix_apply_graph


def _get_contracts_graph():
    global _contracts_graph
    if _contracts_graph is None:
        # 0 字节断点库自愈：sqlite3.connect 建文件即返回，若首次初始化中途中断，
        # 会留下无表结构的空库文件，此后每次建图都失败——检测到即删掉重建。
        if GRAPH_DB_CONTRACTS.is_file() and GRAPH_DB_CONTRACTS.stat().st_size == 0:
            GRAPH_DB_CONTRACTS.unlink()
        conn = sqlite3.connect(str(GRAPH_DB_CONTRACTS), check_same_thread=False)
        _contracts_graph = _build_contracts_graph().compile(checkpointer=SqliteSaver(conn))
    return _contracts_graph


def _get_fdesign_graph():
    global _fdesign_graph
    if _fdesign_graph is None:
        if GRAPH_DB_FDESIGN.is_file() and GRAPH_DB_FDESIGN.stat().st_size == 0:
            GRAPH_DB_FDESIGN.unlink()
        conn = sqlite3.connect(str(GRAPH_DB_FDESIGN), check_same_thread=False)
        _fdesign_graph = _build_fdesign_graph().compile(checkpointer=SqliteSaver(conn))
    return _fdesign_graph


def _get_fcode_graph():
    global _fcode_graph
    if _fcode_graph is None:
        if GRAPH_DB_FCODE.is_file() and GRAPH_DB_FCODE.stat().st_size == 0:
            GRAPH_DB_FCODE.unlink()
        conn = sqlite3.connect(str(GRAPH_DB_FCODE), check_same_thread=False)
        _fcode_graph = _build_fcode_graph().compile(checkpointer=SqliteSaver(conn))
    return _fcode_graph


def _get_ftest_graph():
    global _ftest_graph
    if _ftest_graph is None:
        if GRAPH_DB_FTEST.is_file() and GRAPH_DB_FTEST.stat().st_size == 0:
            GRAPH_DB_FTEST.unlink()
        conn = sqlite3.connect(str(GRAPH_DB_FTEST), check_same_thread=False)
        _ftest_graph = _build_ftest_graph().compile(checkpointer=SqliteSaver(conn))
    return _ftest_graph


def _get_fverify_graph():
    global _fverify_graph
    if _fverify_graph is None:
        if GRAPH_DB_FVERIFY.is_file() and GRAPH_DB_FVERIFY.stat().st_size == 0:
            GRAPH_DB_FVERIFY.unlink()
        conn = sqlite3.connect(str(GRAPH_DB_FVERIFY), check_same_thread=False)
        _fverify_graph = _build_fverify_graph().compile(checkpointer=SqliteSaver(conn))
    return _fverify_graph


def _parse_target_apps(s: str) -> list:
    """target_apps 入库为逗号分隔字符串 → 列表。"""
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def run_task(task_id: int) -> None:
    task = groupbuild_store.get_task(task_id)
    if not task:
        return
    _CANCEL_LOCAL.tid = task_id
    try:
        if task.get("cancel_requested"):      # 入队后被请求终止 → 不再执行
            groupbuild_store.update_task(task_id, status="cancelled")
            groupbuild_store.append_log(task_id, f"任务 #{task_id} 执行前已终止（用户取消）。")
            return
        kind = task.get("kind") or "arch"
        try:                                        # 图构建失败也要落 failed（勿逃逸成静默 queued）
            if kind == "detail":                          # 第②步：逐聚合根应用详设
                thread_id = f"groupbuild-design-{task_id}"
                graph = _get_design_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"],
                                "target_apps": _parse_target_apps(task.get("target_apps", ""))}
                done_msg = f"任务 #{task_id} 完成 → app/{task['group_name']}/<应用名>/应用详设.md"
            elif kind == "code":                          # 第③步：逐聚合根应用编码
                thread_id = f"groupbuild-code-{task_id}"
                graph = _get_code_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"],
                                "target_apps": _parse_target_apps(task.get("target_apps", ""))}
                done_msg = f"任务 #{task_id} 完成 → app/{task['group_name']}/<应用名>/<应用名>.py + README.md"
            elif kind == "testcase":                      # 第④步：整组测试用例生成
                thread_id = f"groupbuild-testcase-{task_id}"
                graph = _get_testcase_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"]}
                done_msg = f"任务 #{task_id} 完成 → app/{task['group_name']}/测试用例.md"
            elif kind == "testexec":                      # 第⑤步：测试脚本生成 + 真实树运行 + 修复回路
                thread_id = f"groupbuild-testexec-{task_id}"
                graph = _get_testexec_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"]}
                done_msg = (f"任务 #{task_id} 完成 → app/{task['group_name']}/test/"
                            f"verify_chain_{task['group_name']}.py + 测试报告.md")
            elif kind == "bugfix":                        # 第⑤步回路：BUG 修复提案（只提案不落码）
                thread_id = f"groupbuild-bugfix-{task_id}"
                graph = _get_bugfix_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"]}
                done_msg = f"任务 #{task_id} 完成 → app/{task['group_name']}/test/修复提案.md（待页面批准）"
            elif kind == "bugfix-apply":                  # 第⑤步回路：应用已批准提案 + 派生重测
                thread_id = f"groupbuild-bugfixapply-{task_id}"
                graph = _get_bugfix_apply_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"]}
                done_msg = f"任务 #{task_id} 完成 → 已应用批准提案并派生重测任务"
            elif kind == "contracts":                     # ⑧契约冻结：沙箱 dump _contracts.md
                thread_id = f"groupbuild-contracts-{task_id}"
                graph = _get_contracts_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"]}
                done_msg = (f"任务 #{task_id} 完成 → app/{task['group_name']}/_contracts.md"
                            f"（契约冻结：前端详设第⑥步的依赖屏障）")
            elif kind == "fdesign":                       # ⑨前端详设：逐应用扇出 + dashboard
                thread_id = f"groupbuild-fdesign-{task_id}"
                graph = _get_fdesign_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"],
                                "target_apps": _parse_target_apps(task.get("target_apps", ""))}
                done_msg = (f"任务 #{task_id} 完成 → app/{task['group_name']}/<应用名>/前端详设.md"
                            f" + 前端详设/dashboard.md")
            elif kind == "fcode":                         # ⑩前端编码：单元 js→html 两阶段
                thread_id = f"groupbuild-fcode-{task_id}"
                graph = _get_fcode_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"],
                                "target_apps": _parse_target_apps(task.get("target_apps", ""))}
                done_msg = (f"任务 #{task_id} 完成 → app/{task['group_name']}/<应用名>/view.{{js,html}}"
                            f" + view/{task['group_name']}/dashboard.*")
            elif kind == "ftest":                         # ⑪前端测试用例：逐应用 + 组级补充
                thread_id = f"groupbuild-ftest-{task_id}"
                graph = _get_ftest_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"],
                                "target_apps": _parse_target_apps(task.get("target_apps", ""))}
                done_msg = (f"任务 #{task_id} 完成 → app/{task['group_name']}/<应用名>/前端测试用例.md"
                            f" + app/{task['group_name']}/前端测试用例.md（组级补充）")
            elif kind == "fverify":                       # ⑫前端测试执行：生成 + 串行真跑 + 修复
                thread_id = f"groupbuild-fverify-{task_id}"
                graph = _get_fverify_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"],
                                "target_apps": _parse_target_apps(task.get("target_apps", ""))}
                done_msg = (f"任务 #{task_id} 完成 → app/{task['group_name']}/tests/verify_view_{task['group_name']}_*.py"
                            f" + app/{task['group_name']}/tests/前端测试报告.md")
            else:                                         # 第①步：生成架构
                thread_id = f"groupbuild-{task_id}"
                graph = _get_graph()
                invoke_input = {"task_id": task_id, "group": task["group_name"],
                                "business_text": task.get("business_text", "")}
                done_msg = f"任务 #{task_id} 完成 → app/{task['group_name']}/architecture.md"
        except Exception as e:
            groupbuild_store.update_task(task_id, status="failed", error=f"任务图构建失败：{e}")
            groupbuild_store.append_log(
                task_id, f"任务 #{task_id} 图构建失败：{e}\n{traceback.format_exc()}")
            return
        cfg = {"configurable": {"thread_id": thread_id}}
        groupbuild_store.update_task(task_id, status="running", error=None, thread_id=thread_id)
        try:
            snap = graph.get_state(cfg)
            if not snap.values:                       # 全新任务 → 从头跑
                groupbuild_store.append_log(task_id, f"任务 #{task_id} 开始（{kind}，组={task['group_name']}）")
                graph.invoke(invoke_input, cfg)
            elif snap.next:                           # 中断态 → 从断点续跑
                groupbuild_store.append_log(task_id, f"任务 #{task_id} 自 {snap.next} 续跑")
                graph.invoke(None, cfg)
            else:                                     # 已完成 → 跳过
                groupbuild_store.append_log(task_id, f"任务 #{task_id} 已完成，无需重跑")
            groupbuild_store.update_task(task_id, status="done", current_step="完成")
            groupbuild_store.append_log(task_id, done_msg)
        except TaskCancelled as e:
            groupbuild_store.update_task(task_id, status="cancelled", current_step="已终止")
            groupbuild_store.append_log(task_id, f"任务 #{task_id} 已终止：{e}")
        except Exception as e:
            groupbuild_store.update_task(task_id, status="failed", error=str(e))
            groupbuild_store.append_log(task_id, f"任务 #{task_id} 失败：{e}\n{traceback.format_exc()}")
    finally:
        _CANCEL_FLAGS.discard(task_id)
        _CANCEL_LOCAL.tid = None


def _worker_loop() -> None:
    while True:
        task_id = _queue.get()
        try:
            run_task(task_id)
        except Exception as e:  # 兜底：单任务异常不影响 worker（打印成因备查，勿静默）
            print(f"[groupbuild-worker] 任务 #{task_id} 异常逃逸：{e}\n{traceback.format_exc()}",
                  flush=True)
        finally:
            _queue.task_done()


def _ensure_worker_thread() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
        threading.Thread(target=_worker_loop, name="groupbuild-worker", daemon=True).start()


def start_worker() -> None:
    """平台启动时调用：起 worker 线程，并把重启前未完成任务重新入队（断点续跑）。"""
    _ensure_worker_thread()
    groupbuild_store.init_schema()
    for task in groupbuild_store.list_tasks(limit=200):
        if task["status"] in ("queued", "running"):
            if task.get("cancel_requested"):   # 重启前被请求终止 → 落 cancelled，不再续跑
                groupbuild_store.update_task(task["id"], status="cancelled", current_step="已终止")
                groupbuild_store.append_log(task["id"], f"任务 #{task['id']} 续跑前已终止（用户取消）。")
                continue
            groupbuild_store.update_task(task["id"], status="queued")
            _queue.put(task["id"])


def enqueue(task_id: int) -> None:
    """新建任务入队执行。"""
    _ensure_worker_thread()
    groupbuild_store.update_task(task_id, status="queued")
    _queue.put(task_id)
