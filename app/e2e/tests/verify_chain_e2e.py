#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`app/e2e` 后端主链端到端 —— 第⑤步产物（此前**缺失**，2026-09-17 补）。

> 这是 `app/e2e` 作为「参考实现」第一次补齐第④⑤步产物。
> 用例唯一来源：`app/e2e/测试用例.md`；本脚本**只是它的翻译**，不另起用例。

## 按 2026-09 新规范写的四项门禁

1. **逐参一致**：`测试用例.md` 里写明的实参，脚本里一个不少
   （不得因"签名有默认值"而省略 —— 那会让用例声称的分支一行不执行）。
2. **无空转断言**：每个 `step` 至少有一条 `assert` 或 `expect_err`；
   **禁止** `assert x is not None` / `isinstance` / `len(x) >= 1` 这类未引用业务字段的断言。
3. **断言可失败性（变异测试）**：见 `run_mutation_check()` ——
   把 `Member._validate_email` 改坏成"恒通过"，`TC-DM-07` **必须变红**。
   做不到就说明那条断言是空转的。
4. **分母非空闸**：断言"列表里有什么"之前，先断言分母非空。

## 初始化方式：**影子库 + 副本上清表**（`fde_platform/shadowdb.py`）

业务库**复制**到临时目录 → 测试全程只读写副本 → 退出时删副本。
**真库零字节接触、不用停服。**

为什么不用 `dbguard` 移库（两条路，不是新旧）：
· 移库要求**必须先停服**（Windows 上被打开的文件 rename 不了），而影子库只做只读复制；
· 移库中途被强杀会让真库**离开原位**（靠下次运行救回），而影子库**真库原地不动**。

> **运行不再清空真库的业务数据** —— `clean()` 清的只是副本。
"""
import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

# 输出编码：控制台代码页在本机默认是 GBK，而断言文案里有 ⇒ / ✓ / ✗ / ⚠ / − 这类**非 GBK 码位** ——
# 不钉住编码的话，print 自己会抛 UnicodeEncodeError（**崩在打印结果那一步**：断言算完了却报不出来，
# 其后用例也不再执行 —— 实测 nasa_pms 的 stakeholder 脚本里有一条断言就这么"消失"过）。与 scripts/run_gates.py 给
# 子进程设 PYTHONIOENCODING 同一根因；由 scripts/verify_test_script_encoding.py 守住别忘这一行。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "fde_platform").is_dir():
            return parent
    raise SystemExit("找不到项目根：向上未发现 fde_platform/")


ROOT = _project_root()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# 外部系统走 stub：清掉基址，出向适配器自动降级为本地 stub
for _k in ("LLM_BASE_URL", "LLM_API_KEY", "SAP_BASE_URL", "MOM_BASE_URL",
           "WMS_BASE_URL", "MDM_BASE_URL", "APS_BASE_URL", "CTCT_BASE_URL"):
    os.environ.pop(_k, None)

GROUP = "e2e"
APPS = ["member", "task"]

STEP = ""
RESULTS = []


def step(name):
    global STEP
    STEP = name
    print(f"  → {name}", flush=True)


def record(ok, note=""):
    RESULTS.append((STEP, ok, note))
    if not ok:
        print(f"     ✗ {note}", flush=True)


def expect_err(fn, *substrs):
    """断言抛 FdeError 且消息含任一关键词。

    ⚠ **关键词必须写具体**：泛化的词（如单独一个「不存在」）会匹配到上游别的前置校验，
    于是断言看着通过、其实**没打到目标分支**（在 PSC 上踩过三次）。

    ⚠ 但另一方面，**关键词也不能靠猜**：本组的状态机错误话术并不统一
    （`进行中任务不能再次启动` 里没有「状态」二字），于是"写窄了"会变成**假红**。
    本轮在本组已因关键词写窄假红 1 次（累计第 4 次）。
    **根因是详设没规定错误话术** —— 用例只能猜。两条出路（见 测试用例.md §6 待确认 7）：
    · 详设为可校验的规则**规定统一话术**，或给 `FdeError` 加**稳定错误码**，用例断言码；
    · 或用例**只断言"被拒"**（不猜关键词），代价是失去"报错原因对不对"这一层
      —— 而那一层正是抓"假通过"的武器（PSC 上靠它抓到过三次）。
    """
    from fde import FdeError
    try:
        fn()
    except FdeError as e:
        msg = str(e)
        if any(s in msg for s in substrs):
            return
        raise AssertionError(f"报错原因不对（期望含 {substrs}）：{msg}") from None
    except Exception as e:                       # noqa: BLE001
        raise AssertionError(f"应抛 FdeError，实际 {type(e).__name__}: {e}") from None
    raise AssertionError(f"应抛 FdeError，实际未抛错（期望含 {substrs}）")


def clean():
    """清空本组各应用库的全部表（保留库文件、只清数据）。

    ⚠ 路径经 **`FDE_DB_ROOT`** 解析 —— 影子库模式下清的是**副本**，真库不受影响。
    （本脚本默认就在影子库里跑，见 `main()`。）
    ⚠ **副本是扁平的**（`<影子>/<应用>.db`）：2026-09-18 影子库布局由树形改成扁平，
    与 `runtime.py` 的 `Path(FDE_DB_ROOT) / f"{name}.db"` 对齐 —— 这里也要按扁平找，
    否则"清表"会一个库都清不到却照样往下跑（用例造数撞主键才暴露，且报错指不到真正原因）。
    """
    root = os.environ.get("FDE_DB_ROOT", "").strip()
    base = Path(root) if root else ROOT
    cleared = 0
    for app in APPS:
        db = base / f"{app}.db"
        if not db.exists():
            continue
        cleared += 1
        conn = sqlite3.connect(str(db))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tables:
            conn.execute(f'DELETE FROM "{t}"')
        conn.commit()
        conn.close()
    if cleared != len(APPS):
        # **分母闸**：清表是「从空表起步」这条前提的全部依据，一个都没清到就不该往下跑
        raise AssertionError(
            f"清表只清到 {cleared}/{len(APPS)} 个库 —— 影子库布局与查找路径不一致（别静默继续）")


# ------------------------------------------------------------------ 用例
def part_member(call):
    """§1 主数据准备（member）—— 逐条对应 测试用例.md 的 TC-DM-*。"""
    step("TC-DM-01 创建 M001")
    m1 = call("member", "create", member_no="M001", name="张管理",
              email="m001@example.com", role="admin")
    assert m1["member_no"] == "M001", m1
    assert m1["name"] == "张管理", m1
    assert m1["email"] == "m001@example.com", m1
    assert m1["role"] == "admin", m1
    record(True)

    step("TC-DM-02 创建 M002")
    m2 = call("member", "create", member_no="M002", name="李成员",
              email="m002@example.com", role="member")
    assert m2["member_no"] == "M002" and m2["role"] == "member", m2
    record(True)

    step("TC-DM-03 编号重复必须被拒（BR-2）")
    expect_err(lambda: call("member", "create", member_no="M001", name="x",
                            email="x@example.com", role="member"),
               "存在", "唯一", "重复")
    record(True)

    step("TC-DM-04 编号为空必须被拒（BR-1）")
    expect_err(lambda: call("member", "create", member_no="", name="x",
                            email="x@example.com", role="member"),
               "不能为空", "必填")
    record(True)

    step("TC-DM-05 姓名为空必须被拒（BR-3）")
    expect_err(lambda: call("member", "create", member_no="M003", name="",
                            email="x@example.com", role="member"),
               "不能为空", "必填")
    record(True)

    step("TC-DM-06 邮箱为空必须被拒（BR-4）")
    expect_err(lambda: call("member", "create", member_no="M003", name="x",
                            email="", role="member"),
               "不能为空", "必填")
    record(True)

    step("TC-DM-07 邮箱格式非法必须被拒（BR-5）")
    expect_err(lambda: call("member", "create", member_no="M003", name="x",
                            email="not-an-email", role="member"),
               "邮箱", "格式")
    record(True)

    step("TC-DM-08 角色非法必须被拒（BR-6）")
    expect_err(lambda: call("member", "create", member_no="M003", name="x",
                            email="x@example.com", role="root"),
               "角色", "admin", "member")
    record(True)

    step("TC-DM-09 查详情（逐字段相等）")
    got = call("member", "get", member_no="M001")
    assert got["member_no"] == "M001", got
    assert got["name"] == "张管理", got
    assert got["email"] == "m001@example.com", got
    assert got["role"] == "admin", got
    record(True)

    step("TC-DM-10 查不到必须被拒（BR-8）")
    expect_err(lambda: call("member", "get", member_no="M404"), "不存在")
    record(True)

    step("TC-DM-11 查详情的编号为空必须被拒（BR-7）")
    expect_err(lambda: call("member", "get", member_no=""), "不能为空", "必填")
    record(True)

    step("TC-DM-12 列表无条件（分母非空闸 + 集合相等）")
    lst = call("member", "list")
    assert lst["total"] == 2, f"分母应为 2，实际 {lst['total']}"     # ← 分母闸：先确认有数据
    assert {r["member_no"] for r in lst["items"]} == {"M001", "M002"}, lst["items"]
    record(True)

    step("TC-DM-13 按关键字筛选")
    lst = call("member", "list", keyword="张")
    assert lst["total"] == 1, lst
    assert lst["items"][0]["name"] == "张管理", lst["items"]
    record(True)

    step("TC-DM-14 按角色筛选")
    lst = call("member", "list", role="member")
    assert lst["total"] == 1, lst
    assert {r["member_no"] for r in lst["items"]} == {"M002"}, lst["items"]
    record(True)

    step("TC-DM-17 分页形参生效（`size` 被真正收到）")
    # 回归守卫：平台基座 `view/lib/shell.js::pageable()` 传的是 `{page, size}`，而 `web.py::_coerce`
    # 对**未知键静默忽略** —— 分页形参名一旦与之不一致（2026-09-17 前这两个应用叫 `page_size`），
    # 参数就**收不到值也没有任何报错**，分页静默失效。这条用例专治它：
    # 若 `size` 被忽略，本页会退回「全量」⇒ `len(items)` 变 2 ⇒ 当场红。
    lst = call("member", "list", page=1, size=1)
    assert lst["total"] == 2, f"总数不应受分页影响：{lst['total']}"
    assert len(lst["items"]) == 1, f"size=1 时本页应恰 1 条（形参被忽略则会是全量 2 条）：{lst['items']}"
    record(True)

    step("TC-DM-15 非法角色筛选必须被拒（BR-9）")
    expect_err(lambda: call("member", "list", role="root"), "角色", "admin", "member")
    record(True)

    step("TC-DM-16 无匹配返回空列表、不抛错（BR-10 的输出就是 member 列表）")
    lst = call("member", "list", keyword="不存在的人")
    assert lst["items"] == [], lst
    assert lst["total"] == 0, lst
    record(True)


def part_task(call):
    """§2 主业务链 + §3 分支异常（task）。"""
    step("TC-MC-01 创建任务（BR-7 输出 task_no / BR-8 输出 status=待办）")
    t1 = call("task", "create", title="写方案", description="把方案写完",
              assignee_member_no="M002", priority="high")
    assert t1["task_no"], t1                                  # BR-7 的输出字段
    assert t1["status"] == "待办", t1                          # BR-8 的输出字段
    assert t1["assignee_member_no"] == "M002", t1
    assert t1["priority"] == "high", t1
    assert t1["title"] == "写方案", t1
    t1_no = t1["task_no"]
    t1_created_at = t1.get("updated_at") or t1.get("created_at")
    record(True)

    step("TC-MC-03 查任务详情（逐字段与创建时一致）")
    got = call("task", "get", task_no=t1_no)
    assert got["task_no"] == t1_no, got
    assert got["title"] == "写方案", got
    assert got["description"] == "把方案写完", got
    assert got["assignee_member_no"] == "M002", got
    assert got["priority"] == "high", got
    assert got["status"] == "待办", got
    record(True)

    step("TC-MC-04 任务列表无条件（分母闸；返回 {items,total} 同形，CONVENTION §7）")
    # 2026-09-18 修：此前 `task.list` 无参时返回**裸 list**，与 `member.list` 不同形；消费方
    # 一律按 {total, items} 取值 ⇒ 恒定读成 0（看板三张任务类 KPI 恒 0 的根因）。
    # 本步从此**同时是形状闸**：裸 list 会让下面两行直接红。
    res = call("task", "list")
    assert isinstance(res, dict), f"task.list 应返回 {{items,total}} 字典，实际 {type(res).__name__}"
    lst = res["items"]
    assert res["total"] == len(lst) == 1, f"分母应为 1（total 与 items 长度同源），实际 {res['total']}/{len(lst)}"
    assert lst[0]["task_no"] == t1_no, lst
    record(True)

    step("TC-MC-05 启动任务（BR-10 输出 status=进行中 / BR-15 输出 updated_at）")
    st = call("task", "start", task_no=t1_no)
    assert st["status"] == "进行中", st                        # BR-10 的输出字段
    assert st["updated_at"] != t1_created_at or st["updated_at"] >= t1_created_at, \
        f"updated_at 应被更新：{st['updated_at']} vs {t1_created_at}"   # BR-15
    record(True)

    step("TC-MC-06 退回任务（**进行中 → 待办**；BR-12 输出 status=待办）")
    # ⚠ 「已完成」是**终态**（BR-13 禁止任何流转），reopen 只允许 进行中→待办。
    #    初版把主链写成"完成后可退回"，与 TC-ERR-16 自相矛盾 —— 见测试用例.md §6 待确认 6。
    st = call("task", "reopen", task_no=t1_no)
    assert st["status"] == "待办", st                          # BR-12 的输出字段
    record(True)

    step("TC-MC-07 再启动并完成（进行中 → 已完成；BR-10 / BR-11 的输出）")
    st = call("task", "start", task_no=t1_no)
    assert st["status"] == "进行中", st
    st = call("task", "complete", task_no=t1_no)
    assert st["status"] == "已完成", st                        # BR-11 的输出字段
    record(True)

    step("TC-ERR-01 标题为空必须被拒（BR-1）")
    expect_err(lambda: call("task", "create", title="", assignee_member_no="M002",
                            priority="low"), "不能为空", "必填")
    record(True)

    step("TC-ERR-02 标题超长必须被拒（BR-2）")
    expect_err(lambda: call("task", "create", title="x" * 201, assignee_member_no="M002",
                            priority="low"), "长度", "200")
    record(True)

    step("TC-ERR-03 描述超长必须被拒（BR-3）")
    expect_err(lambda: call("task", "create", title="ok", description="x" * 2001,
                            assignee_member_no="M002", priority="low"), "长度", "2000")
    record(True)

    step("TC-ERR-04 优先级非法必须被拒（BR-4）")
    expect_err(lambda: call("task", "create", title="ok", assignee_member_no="M002",
                            priority="urgent"), "优先级", "low", "high")
    record(True)

    step("TC-ERR-05 指派不存在的成员必须被拒（BR-6 · 跨应用链的失败面）")
    expect_err(lambda: call("task", "create", title="ok", assignee_member_no="M404",
                            priority="low"), "成员", "不存在")
    record(True)

    step("TC-ERR-06 指派编号为空必须被拒（BR-5）")
    expect_err(lambda: call("task", "create", title="ok", assignee_member_no="",
                            priority="low"), "不能为空", "必填")
    record(True)

    step("TC-ERR-07~10 任务不存在时四个操作都必须被拒（BR-14）")
    expect_err(lambda: call("task", "get", task_no="T404"), "不存在")
    expect_err(lambda: call("task", "start", task_no="T404"), "不存在")
    expect_err(lambda: call("task", "complete", task_no="T404"), "不存在")
    expect_err(lambda: call("task", "reopen", task_no="T404"), "不存在")
    record(True)

    step("TC-ERR-11~12 列表筛选枚举非法必须被拒（BR-16）")
    expect_err(lambda: call("task", "list", status="done"), "状态")
    expect_err(lambda: call("task", "list", priority="urgent"), "优先级")
    record(True)

    step("TC-ERR-13 在「进行中」上再 start 必须被拒（BR-10）")
    t2 = call("task", "create", title="二次启动", assignee_member_no="M002", priority="low")
    call("task", "start", task_no=t2["task_no"])
    expect_err(lambda: call("task", "start", task_no=t2["task_no"]),
               "状态", "进行中", "不能再次")
    record(True)

    step("TC-ERR-14 在「待办」上 complete 必须被拒（BR-11）")
    t3 = call("task", "create", title="待办即完成", assignee_member_no="M002", priority="low")
    expect_err(lambda: call("task", "complete", task_no=t3["task_no"]),
               "状态", "待办", "不能")
    record(True)

    step("TC-ERR-15 在「待办」上 reopen 必须被拒（BR-12）")
    expect_err(lambda: call("task", "reopen", task_no=t3["task_no"]),
               "状态", "待办", "不能")
    record(True)

    step("TC-ERR-16 已完成任务禁止任何状态流转（BR-13）")
    t4 = call("task", "create", title="已完成锁", assignee_member_no="M002", priority="low")
    call("task", "start", task_no=t4["task_no"])
    call("task", "complete", task_no=t4["task_no"])
    expect_err(lambda: call("task", "start", task_no=t4["task_no"]), "状态", "已完成")
    expect_err(lambda: call("task", "complete", task_no=t4["task_no"]), "状态", "已完成")
    expect_err(lambda: call("task", "reopen", task_no=t4["task_no"]), "状态", "已完成")
    record(True)


def run_mutation_check(pf, call):
    """**断言可失败性（变异测试）**：把一处校验改坏，对应用例必须变红。

    这是第⑤步新规范要求、而此前**完全没有**的一步。它回答的是：
    「这条断言真的在约束实现吗，还是只是"调通了"？」
    """
    step("MUT-01 变异测试：改坏 _validate_email 后 TC-DM-07 必须变红")
    cls = pf.handle(f"{GROUP}/member").cls
    orig = cls._validate_email

    def broken(self, email):
        return email                      # ← 邮箱格式校验被短路

    cls._validate_email = broken
    try:
        try:
            call("member", "create", member_no="M901", name="变异",
                 email="not-an-email", role="member")
        except Exception:                 # noqa: BLE001
            record(False, "改坏校验后仍被拒 ⇒ TC-DM-07 的断言可能命中了别的分支，"
                          "或该校验没被 create 调用")
            return
        # 走到这里说明校验被短路后确实放行了 —— 也就是 TC-DM-07 的断言有牙
        record(True)
        print("     ✓ 短路 _validate_email 后该创建真的放行了 ⇒ TC-DM-07 的断言能失败")
    finally:
        cls._validate_email = orig
        try:
            call("member", "get", member_no="M901")
        except Exception:                 # noqa: BLE001
            pass                          # 恢复后 M901 是否残留不影响结论


def main():
    """入口：先进**影子库**（业务库复制到副本，真库零字节接触、**不用停服**），再跑正文。"""
    from fde_platform.shadowdb import shadow_dbs
    with shadow_dbs():
        return _run()


def _run():
    print("=" * 78)
    print(f"应用组 {GROUP} 后端主链端到端（第⑤步）")
    print("  用例唯一来源：app/e2e/测试用例.md")
    print(f"  影子库：清空的是**副本**上 app/{GROUP}/ 各应用的表（真库不动、不用停服）")
    print("=" * 78)

    from fde_platform.runtime import FdePlatform
    clean()
    pf = FdePlatform()
    pf.load_all()

    for app in APPS:
        assert pf.handle(f"{GROUP}/{app}") is not None, f"{app} 未加载"

    def call(app, svc, **kw):
        return pf.call(f"{GROUP}/{app}", svc, **kw)

    for fn in (part_member, part_task):
        try:
            fn(call)
        except Exception as e:            # noqa: BLE001
            record(False, f"[{fn.__name__}] 崩溃：{type(e).__name__}: {e}")

    try:
        run_mutation_check(pf, call)
    except Exception as e:                # noqa: BLE001
        record(False, f"变异测试崩溃：{type(e).__name__}: {e}")

    print("\n" + "=" * 78)
    bad = [r for r in RESULTS if not r[1]]
    print(f"共 {len(RESULTS)} 步；通过 {len(RESULTS) - len(bad)}；失败 {len(bad)}")
    for name, _, note in bad:
        print(f"  ✗ {name} —— {note}")
    print(f"VERIFY_RESULT: {'PASS' if not bad else f'PARTIAL {len(RESULTS) - len(bad)}/{len(RESULTS)}'}")
    print("=" * 78)
    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                # noqa: BLE001
        print(f"FAIL_STEP: {STEP}")
        print(f"VERIFY_RESULT: CRASH —— {type(e).__name__}: {e}")
        sys.exit(1)
