#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证门禁跑手 —— 一条命令跑完所有检查，输出统一 verdict。

## 为什么要有它

本轮（2026-09-15）体检挖出的 4 个缺陷，**全是靠人手动跑出来的**；没人跑就没人知道坏了。
更要紧的是本轮暴露的缺陷模式：**同一件事只修了一半** ——
速度对冲只修了批量路径（单行路径仍不可达）、静默降级只修了推移表（`build_gross` 仍静默成功）、
BR-15 只实现了四个分支的一部分。**"同一件事的所有路径"只能由校验器守住，靠人记得是靠不住的。**

## 分层（按代价从低到高，默认只跑前两层）

| 层 | 内容 | 需要 | 会不会动数据 |
|---|---|---|---|
| `static` | `scanner`（跨应用契约静态扫描）、`verify_ddl_reconcile`、`verify_agent_tools` | 无 | **不会**（临时库/纯扫描） |
| `oracle` | `verify_psc_oracles --scenario`（对账 + 不变式 + 静态探针 + 影子库全链/穿透/注入） | 无（**dev server 可以开着**） | **不会**（影子库是副本） |
| `chain` | `app/psc/tests/verify_chain_psc.py`（后端主链端到端） | playwright 无关；**dev server 可以开着** | **不会**（影子库是副本，见下） |
| `view` | `app/psc/tests/verify_view_psc*.py`（前端逐页 e2e，19 个） | playwright；**dev server 可以开着** | **不会**（影子库 + `env=True` 穿透子进程） |

> **⚠ 2026-09-17 订正两处过时警示**（本条本身就是一次"文档与实现漂移"）：
> `chain` / `view` 两层曾分别写「**必须先停 dev server**」「**会清空 PSC 全部业务数据**」——
> 那说的是 `dbguard` 移库那条路。改用 `fde_platform/shadowdb.py` 之后，两层都只读写
> **副本**（`verify_chain_psc.py` 是 `shadow_dbs()` + 副本上 `shadow_clear`；
> `verify_view_psc*.py` 是 `shadow_dbs(env=True, inprocess=False, config=True)`，
> 环境变量穿透 `subprocess.Popen([python, main.py])`）⇒ **真库零字节接触，也不占用库文件**，
> 所以**不用停服**。实测依据见 CLAUDE.md「测试与验收红线」：服务在跑的同时跑链测试与 view e2e 均 PASS，
> 真库 18 个文件哈希与 mtime 全未变。
> 剩下的**真实代价只有一个**：`chain`/`view` 与平台**不能同时写同一份数据**（各写各的副本，
> 互不干扰，但你看到的数与测试算的数可能不同步）。
> 把过时警示留着是有代价的 —— 它会让人**不敢跑这两层**，而闸的价值全在于有人跑。

## 门禁口径（这条最要紧）

闸只卡**不变量**：不越权、不改业务数据、不泄漏未授权信息、平台链算得对、
同一件事的不同路径给出同一答案。**"答得好不好"（`verify_agent_quality.py` 的 B 类开放题）
作为报告项，不卡闸** —— 那类本来就会波动，拿它当闸会天天红，红久了人就无视红灯。

## 用法

    python scripts/run_gates.py                    # static + oracle（安全，随时可跑）
    python scripts/run_gates.py --tier chain       # 加后端主链（危险，会清数据）
    python scripts/run_gates.py --all              # 全部四层
    python scripts/run_gates.py --list             # 只列将要跑什么
    python scripts/run_gates.py -g e2e             # 换一个应用组（结构检查随组走；
                                                   # oracle 层是 PSC 专属，非 psc 时自动跳过）
"""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "fde_platform").is_dir():
            return parent
    raise SystemExit("找不到项目根：向上未发现 fde_platform/")


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

PY = sys.executable
GROUP = os.environ.get("FDE_GATE_GROUP", "psc")   # 由 main() 按 --group 覆盖

# tier -> [(名称, 命令, 是否动数据)]
# ⚠ **必须是函数**：模块级常量在 import 时就把 GROUP 定死了（那时还没解析 --group），
# 于是 `--group e2e` 会照样跑 psc 的命令 —— 2026-09-17 接入 e2e 时踩到。
def _tiers(group):
        return {
        "static": [
            ("契约静态扫描", [PY, "-m", "fde_platform.scanner"], False),
            ("DDL 列对账", [PY, "scripts/verify_ddl_reconcile.py"], False),
            # **PG 方言改写层**（2026-09-20 加）：本地全程 SQLite、根本不走 `_PgConnection.execute`
            # 那条路径，于是它的错本地一律发现不了 —— 2026-09-20 一天之内在那里连撞四个
            # 只会在真 PG 上现形的缺陷（字面量 `%` 未转义 ⇒ 所有模糊搜索全崩；审计注入的
            # 占位符又被那次转义吃掉 ⇒ 所有 UPDATE 全崩）。纯 Python、不起库、<1s，
            # 两条断言都用突变验过「能失败」。
            # 2026-09-26 扩成**两条路都覆盖**：A 段钉死 legacy（字符串手术）验既有行为，
            # B 段验编译层（`sqlc.py`，sqlglot AST 改写：占位符按**词法顺序**改名、审计注入
            # 到每一行/投影、`%` 只对 %-插值驱动且只在会插值时转义、mysql 按驱动改写、
            # PG 追加 RETURNING、边界明确报错、缓存不缓存参数）。
            ("SQL 方言编译层", [PY, "scripts/verify_pg_translate.py"], False),
            # **多方言渲染**（2026-09-20 加）：把 app/**/schema.sql 逐个渲染成
            # postgres / mysql / tsql / oracle，检查产物里有没有留下源方言（SQLite）
            # 专有的写法。**不需要安装任何数据库** —— 建表 DDL 的生成是纯函数，
            # 断言它的输出不必连着那个库。加一个方言 = 在脚本的 DIALECTS 里加一个字符串。
            # 起因：当天把 `datetime()` 的归一化只写成「仅 postgres」，一渲染才发现
            # mysql/tsql/oracle 三个方言**一模一样地残留**——只修脚下那个等于只做一半。
            ("多方言渲染", [PY, "scripts/verify_dialect_render.py"], False),
            # **隔离机制自检**（2026-09-18 加）：四条判据 —— 副本按运行期规则可解析 / 副本内容 ==
            # 真库 / env 路径下 db_path 全在影子目录内 / 真库 mtime+size 全程不变。
            # 它是别的检查的**前提**（底座不成立时，其余检查的"没碰真库"结论也不可信），
            # 而且快（不起服务、不写盘）。由它守着的那个偏差见 `shadowdb._copy_all` 注释。
            ("影子库隔离自检", [PY, "scripts/verify_shadow_isolation.py"], False),
            ("智能体工具面结构", [PY, "scripts/verify_agent_tools.py"], False),
            # **应用组数据隔离**（2026-09-26 加）：AI管家的 SKILL / 告警 / 运转动态三块此前
            # **数据本身就不带组**（三张表都没有组字段），于是 A 组的页面会列出 B 组的数据；
            # 而"库存预警"那条来源还硬编码直调 psc/inventory_projection。
            # 这类缺陷**没有任何测试会红**（端点 200、页面正常、数字还挺丰富），故单独对账：
            # 组视角 = 本组 ∪ 平台级 / 平台视角 = 全量 / 写入带归属 / 前端取数带 group。
            # 全程在临时 config 根里跑，真库零接触。
            ("应用组数据隔离", [PY, "scripts/verify_group_isolation.py"], False),
            # **跨应用边对账**（2026-09-25 加）：架构声明的边 ↔ 代码里真实存在的边
            # （后端 `self.fde.call` + 前端页面 `svc(...)` 字面量）。架构声明是第①步的产物、
            # 下游全照它推，而"声明与实现不一致"**没有任何测试会红** —— 所以单独对账。
            # 缺声明表的组：明示 SKIP（不是通过）。
            ("跨应用边对账", [PY, "scripts/verify_app_edges.py", "--group", GROUP], False),
            # **测试脚本输出编码**（2026-09-25 加）：抓「断言算完了、却崩在打印结果那一步」的脚本。
            # 实测症状：`verify_view_nasa_pms_stakeholder.py` 在 GBK 控制台下崩在 print 上 ⇒
            # FE-32 的断言结果**无人知晓**、其后用例**根本没跑**，而报出来的是 traceback（像断言失败）。
            # 判据：`print/assert/raise` 的字符串里含**代码页编不出**的字符（GBK 现算：⇒ ✓ ✗ ⚠ − 编不出，
            # 而 ≥ ≤ × → 在 GBK 里有码位 —— 硬编码符号清单会大面积误报）且文件未钉 `reconfigure(utf-8)`。
            ("测试脚本输出编码", [PY, "scripts/verify_test_script_encoding.py"], False),
            # 结构检查：抓「参数被当 None 判定条件、但全部生产调用点都省略它 ⇒ 分支永不可达」。
            # 实测抓到 B-08（BR-06 富余档在生产上永不生效）—— 89 条用例全过、没有一条会红。
            # `--expect 0`：B-08 接线补齐后，「敏感参数全部调用点缺省」的命中数从 1 变 0。
            # 这条断言是防「判据静默塌成空集」的 —— 命中数一变就必须跟着改，
            # 否则要么假红（还写着 1），要么在判据被改窄时无声通过。
            # ⚠ `--expect` 是**按组校准**的（PSC=0）；别的组没校准过，就不给该参数
            # （漏斗照打，只是少了「命中数与预期相符」那条断言）。
            ("结构检查（不可达分支）",
             [PY, "scripts/scan_structure.py", "-g", GROUP] +
             (["--expect", "0"] if GROUP == "psc" else []), False),
        ],
        "oracle": [
            # ⚠ `verify_psc_oracles.py` **是 PSC 专属的**（应用清单、业务口径都写死；见
            # `design-plus/验证门禁.md` §九「推广到其他应用组要做什么」）。别的组不能拿它冒充 ——
            # 那不是"这个组也体检过了"，而是"体检了另一个组"。故非 psc 时这一层直接跳过并说明。
            ("对账体检（含场景/穿透/注入）", [PY, "scripts/verify_psc_oracles.py", "--scenario"], False),
        ] if GROUP == "psc" else [],
        "chain": _chain_gates(),
        "view": [],          # 运行时按 glob 填充
    }


ORDER = ["static", "oracle", "chain", "view"]
DEFAULT_TIERS = ["static", "oracle"]

# 每层单条命令的超时（秒）。参考量级：static 单条 <5s、oracle ~12s、chain ~2s、view 单脚本 20~40s；
# 留 5~10 倍余量即够。**挂住的脚本要在几分钟内现形**，而不是拖满半小时。
TIER_TIMEOUT = {"static": 300, "oracle": 900, "chain": 600, "view": 300}


def _chain_gates():
    """后端链测试：优先跑**编排器** `verify_chain_<组>.py`（一个入口跑全组）；
    没有编排器时退化为逐个跑**分片** `verify_chain_<组>_<应用>.py`。

    ⚠ 2026-09-25 加：此前这里是**精确名**判断（`verify_chain_<组>.py` 存在才有这一层），
    而 nasa_pms 的产物是 11 个逐应用分片、**没有编排器** ⇒ `--tier chain --group nasa_pms`
    取到**空层**，报告却照样显示"通过"（**判据静默塌成空集**）。同一天两处都补了：
    编排器落地（`app/.../verify_chain_nasa_pms.py`，它自己也不是空集 —— 跑 0 分片会报错退出），
    且这里放宽成"编排器优先、分片兜底"。
    ⚠ `_part*.py` **排除**：那种片段没有模块级 import、靠父脚本 `exec` 进同一进程（PSC 形态），
    单独跑必然崩 —— 它们由各自的编排器带。
    """
    d = ROOT / f"app/{GROUP}/tests"
    orch = d / f"verify_chain_{GROUP}.py"
    # dirty=False：脚本内 `shadow_dbs()` + 副本上清表，真库零字节接触（见文件头订正）；
    # `-u` 同理（挂住被强杀时不丢最后一屏输出，见 `_view_gates` 的注释）
    if orch.exists():
        return [("后端主链端到端（编排器 · 全组）", [PY, "-u", str(orch.relative_to(ROOT))], False)]
    out = []
    for p in sorted(d.glob(f"verify_chain_{GROUP}_*.py")):
        if p.stem.endswith("_part") or re.search(r"_part\d+$", p.stem):
            continue
        app = p.stem[len(f"verify_chain_{GROUP}_"):]
        out.append((f"后端主链端到端 · {app}", [PY, "-u", str(p.relative_to(ROOT))], False))
    return out


def _view_gates(group=None):
    """前端逐页 e2e：按文件 glob，新增页面自动纳入（不写死清单）。

    dirty=False：`shadow_dbs(env=True, inprocess=False, config=True)` —— 业务库与 config/
    都影子化，且**环境变量穿透** `subprocess.Popen([python, main.py])`，真库零字节接触。
    """
    out = []
    for p in sorted((ROOT / f"app/{GROUP}/tests").glob(f"verify_view_{GROUP}*.py")):
        out.append((f"前端 e2e · {p.stem.replace(f'verify_view_{GROUP}_', '').replace(f'verify_view_{GROUP}', '组级')}",
                    # `-u`（无缓冲）**必须加**：这些脚本被管道接住时 stdout 是块缓冲的，
                    # 一旦脚本**挂住**被跑手强杀，缓冲区里最后那些行（往往正是死因，
                    # 如 `Page crashed` / `Target crashed`）会**一起丢掉** ——
                    # 2026-09-18 实测：因为丢了这行，`run_gates` 的崩溃重试判据没能触发，
                    # 表现成"第二次也是失败"，而其实是"第一次的死因没被看到"。
                    [PY, "-u", str(p.relative_to(ROOT))], False))
    return out


def _kill_tree(pid: int) -> None:
    """杀掉整棵进程树（Windows 用 `taskkill /T /F`，其它平台退回 `killpg`/`kill`）。

    为什么必须按树杀（2026-09-18）：`view`/`chain` 层每个脚本都会 `subprocess.Popen([python, main.py])`
    起一个平台进程，playwright 还会起 chromium 及其子进程。脚本挂住被强杀时，
    **只杀直接子进程会把这些孙子全留下** —— 它们继续占内存/句柄/端口，一轮下来能攒出好几个，
    而"间歇崩溃"的失败恰好都扎堆出现在残留累积之后（见 `app/psc/BUGS_psc_2026-09-15.md` §6）。
    """
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=30)
        else:                                            # pragma: no cover - 本仓跑在 Windows
            try:
                os.killpg(os.getpgid(pid), 9)
            except Exception:                            # noqa: BLE001
                os.kill(pid, 9)
    except Exception:                                    # noqa: BLE001
        pass                                             # 清理失败不该盖住真正的失败原因


def _port_up(port: int) -> bool:
    import socket
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    # Windows 控制台默认 GBK：本脚本与各子检查都打印 ✓/✗/⚠，不转码会
    # `UnicodeEncodeError` **把跑手本身打挂**（失败明细变成异常、看不到真实结果）。
    # 实测：2026-09-25 有一轮 4 个并行开发各自撞到，都只能靠外层 PYTHONIOENCODING 绕。
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="验证门禁跑手")
    ap.add_argument("--tier", action="append", choices=ORDER,
                    help="只跑指定层（可重复）；默认 static+oracle")
    ap.add_argument("--all", action="store_true", help="跑全部四层（含危险层）")
    ap.add_argument("--list", action="store_true", help="只列将要跑什么")
    ap.add_argument("--tail", type=int, default=12, help="失败时回显输出尾部行数")
    ap.add_argument("-g", "--group", default="psc", help="应用组（默认 psc）")
    args = ap.parse_args()

    global GROUP
    GROUP = args.group
    TIERS = _tiers(GROUP)
    TIERS["view"] = _view_gates()
    tiers = ORDER if args.all else (args.tier or DEFAULT_TIERS)
    gates = [(t, name, cmd, dirty) for t in tiers for name, cmd, dirty in TIERS[t]]
    # **空层必须出声**（2026-09-25 加）：选了某一层，却一个检查项都没匹配到 ——
    # 那不是"通过"，是**判据塌成了空集**（实测：`--tier chain --group nasa_pms` 曾取到 0 项
    # 却报 PASS，因为该组当时只有逐应用分片、没有 `verify_chain_<组>.py`）。
    # ⚠ 但**有些层按设计就是空的**（不是判据塌了）—— 那种要**说明**，不能一起判失败，
    #   否则会把"设计如此"误报成红灯（本闸门自己也栽在"分不清空的原因"上）。
    INTENTIONAL_EMPTY = {
        "oracle": "本层是 PSC 专属（见 `_tiers` 注释：`verify_psc_oracles.py` 的应用清单与业务口径写死）"
                  "—— 非 psc 组**按设计**没有它，空是预期的",
    }
    empty_all = [t for t in tiers if not TIERS[t]]
    empty_intentional = [t for t in empty_all if t in INTENTIONAL_EMPTY]
    empty_tiers = [t for t in empty_all if t not in INTENTIONAL_EMPTY]

    if args.list:
        for t in tiers:
            print(f"[{t}]")
            for name, cmd, dirty in TIERS[t]:
                print(f"  {'⚠ 会清业务数据  ' if dirty else '  安全        '}{name}")
        return 0

    dirty = [g for g in gates if g[3]]
    if dirty:
        print("=" * 78)
        print(f"⚠ 选中了 {len(dirty)} 项**会清空 PSC 全部业务数据**的检查（测试环境初始化语义）。")
        print("  跑完请用 `python 宣传/demo_build.py` 重建演示环境。")
        for t, name, cmd, _ in dirty[:3]:
            print(f"    · {name}")
        if len(dirty) > 3:
            print(f"    · …另 {len(dirty) - 3} 项")
        # 目前没有任何一层是 dirty（chain/view 已改影子库），这段是给**将来**可能加的
        # 「移库/清表」类检查留的闸口 —— 那种才真的要求停服（Windows 下库文件被占用就移不动）。
        if _port_up(4000):
            print("  ⚠ dev server(:4000) 正在运行 —— 这些检查用 dbguard 移库，**必须先停服**。")
        print("=" * 78)

    results = []
    for tier, name, cmd, is_dirty in gates:
        print(f"\n--- [{tier}] {name} ---", flush=True)
        t0 = time.time()
        limit = TIER_TIMEOUT.get(tier, 1800)
        rc, out, retried = None, "", False
        for attempt in (1, 2):
            # ⚠ `encoding="utf-8"` 只管**父进程怎么解码**；子进程默认按控制台码页（Windows GBK）
            # 编码自己的 stdout ⇒ 子脚本打印 ✓/✗/⇒ 时**自身崩掉**，失败原因还被异常盖住
            # （实测 2026-09-25：三个子检查都这么崩，一路靠外层 PYTHONIOENCODING 绕）。
            # 这里把 `PYTHONIOENCODING` 传给子进程，与上面的 `encoding="utf-8"` 对齐。
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace",
                                 env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            try:
                out, _ = p.communicate(timeout=limit)
                rc = p.returncode
            except subprocess.TimeoutExpired:
                # ⚠ 超时**必须按层给**：`view` 层单个脚本正常 20~40 秒，用统一的 1800s 会让
                # 「某个脚本挂死」以 30 分钟的形式呈现（2026-09-18 实测：PSC 组级 view 脚本挂住
                # 25 分钟还没到点，整层跑不完、也没有任何输出能定位到是哪一支）。
                # ⚠ **必须按进程树杀**：这些脚本自己会 `Popen` 起平台（还有 chromium 孙进程），
                # 只杀直接子进程会留下一堆**孤儿**继续占内存/句柄/端口 ——
                # 2026-09-18 实测：一轮下来攒了 5 个孤儿 python，而「间歇崩」的失败恰好都扎堆
                # 出现在残留累积之后（见台账 §6）。杀完再收一次管道，拿到超时前已产出的输出
                # （那段里往往写着真正的死因，如 `Page crashed` —— 也是崩溃重试的判据）。
                _kill_tree(p.pid)
                try:
                    out, _ = p.communicate(timeout=20)
                except Exception:                       # noqa: BLE001
                    out = ""
                rc = 124
                out = (f"TIMEOUT（{limit}s）—— 该脚本挂住了（已按进程树清理）；"
                       f"单独重跑它看卡在哪一步\n--- 超时前已产出的输出（尾部）---\n{out or ''}")
            # **只在「渲染进程崩溃」这一种情况下重试一次，且必须响亮地记下来**
            # （2026-09-18）：`strategy_fitting` 的 §4 批量拟合 那一步会**间歇**把 chromium
            # 渲染进程搞崩，崩溃后脚本卡在崩溃页上逐个 wait 超时（表现为整脚本"挂住"）。
            # 实测：约 1/3 的跑次触发、连跑两次一次崩一次过、**内存曲线全程平稳**（不是内存压力）、
            # 且**平台侧很快**（同一步在进程内直调：首次 1.8s、其后 0.1s）—— 排除服务端挂住。
            # 崩的是浏览器进程，业务动作已完成（toast 已出、落表断言在崩溃点之前）。
            #
            # 判据用**两种拼写**（playwright 在不同调用点给的措辞不同，只认一种会漏：
            # 实测 `wait_for_timeout` 报 `Page crashed`、`locator.count()` 报 `Target crashed`）。
            # 断言失败 / 超时 / 业务报错 / 连不上服务一律**不重试** —— 不会掩盖真缺陷。
            crashed = ("Page crashed" in out) or ("Target crashed" in out)
            if attempt == 1 and rc != 0 and crashed and not retried:
                retried = True
                print("  ⚠ 第 1 次跑遇到渲染进程崩溃（Page/Target crashed）—— 重试一次；"
                      "若第 2 次仍崩，按 FAIL 处理", flush=True)
                continue
            break
        dt = time.time() - t0
        ok = rc == 0
        if retried and ok:
            print("  ⚠ 本次结果来自**重试**（第 1 次 Page crashed）—— 计数照记，别当成一次干净通过")
        # 子检查可以输出 `VERIFY_NOTE: …` 声明自己的**覆盖范围/跳过原因** —— 带进表格，
        # 否则"检查 PASS 但其实没覆盖本组"会静默（与 #45 的空层同一族）。
        note = ""
        for ln in (out or "").splitlines():
            if ln.startswith("VERIFY_NOTE:"):
                note = ln.split(":", 1)[1].strip()
        results.append((tier, name, ok, dt, out, is_dirty, note))
        print(f"  {'✓ PASS' if ok else '✗ FAIL'}  {dt:.1f}s  (rc={rc})")
        if not ok:
            # 卡住类失败**要能被一眼认出来**：view 脚本的 watchdog 一旦报过现场，
            # 这条失败多半是前台/环境抖动（页面冻住，后端数据正常）—— 台账 §8/§9 有取证。
            # 单独打一行提示，是为了不让人把它和"断言失败"混为一谈：
            # 混为一谈的后果是要么去修没毛病的产品代码，要么对红灯脱敏。
            if "[watchdog]" in out:
                print("      ⚠ 本次失败伴随 watchdog 卡住现场（页面冻住，非断言失败）——"
                      " 见 app/psc/BUGS_psc_2026-09-15.md §8/§9；后端数据正常。", flush=True)
            tail = [ln for ln in out.strip().splitlines() if ln.strip()][-args.tail:]
            for ln in tail:
                print(f"      │ {ln[:150]}")

    print("\n" + "=" * 78)
    print("门禁结果")
    print("=" * 78)
    for row in results:
        tier, name, ok, dt, _out, _dirty, note = row
        extra = f"   ⚠ {note}" if note else ""
        print(f"  {'✓' if ok else '✗'} [{tier:7s}] {dt:7.1f}s  {name}{extra}")
    bad = [r for r in results if not r[2]]
    if empty_intentional:
        for t in empty_intentional:
            print(f"\n· [{t}] 0 项 —— {INTENTIONAL_EMPTY[t]}")
    if empty_tiers:
        print(f"\n⚠ 空层 {len(empty_tiers)} 个（选了这一层，却一个检查项都没匹配到 —— **空集不算通过**）：")
        for t in empty_tiers:
            print(f"  ⚠ [{t}] 0 项 —— 该组确实没有这类产物？还是 glob 与产物命名不一致？")
    print(f"\n通过 {len(results) - len(bad)}/{len(results)}" + (f"（另有 {len(empty_tiers)} 个空层）" if empty_tiers else ""))
    print(f"VERIFY_RESULT: {'PASS' if not bad and not empty_tiers else 'FAIL'}")
    if bad:
        print("\n失败的检查：")
        for row in bad:
            name, dirty = row[1], row[5]
            print(f"  · {name}" + ("（该层会清业务数据，跑完记得重建演示环境）" if dirty else ""))
    return 0 if not bad and not empty_tiers else 1


if __name__ == "__main__":
    sys.exit(main())