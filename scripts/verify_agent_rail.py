# -*- coding: utf-8 -*-
"""右栏「长回合」验收：**跑着不能发、跑完必须看到完整答案**。

## 为什么需要它（2026-09-27 加）

用户报的现象是「管家还没执行完就跳去看别的了」——查下来是两个真问题叠在一起：

1. **解禁过早**：`sending` 原来在流的 `finally` 里无条件清掉，而这条流会因为任何原因
   提前结束（前端收敛判据 / 客户端断连 / 平台收尾 / 超时）。流一断、按钮就亮 ⇒
   「活还在跑、发送按钮却亮了」，用户能往同一个会话里塞第二条指令（平台侧对
   「会话在跑又来一条」没有定义）。
2. **对账落空**：解禁之后紧接着那次"拿服务端历史对账"，会在答案**还没落盘**时跑，
   守卫看到"历史比本地短"就放弃采纳 ⇒ 右栏永远停在半截，**得手动刷新才补上**。

修法：两件事共用一个判据 —— **会话说 idle 才解禁、才去对账**（`agent_rail.js::waitTurnSettled`，
与 `streamUntilIdle` 同款、同一个 `/api/agent2/sessions` 接口）。本脚本就是它的验收：
直接**真跑一条 5–8 分钟的流程**（长回合的最坏情形），全程盯着按钮与答案。

## 跑法（要先起平台与 agent_service，并配好 LLM）

    python -m fde_platform.agent_service        # :4100（另开一个终端）
    python main.py                              # :4000（另开一个终端）
    python scripts/verify_agent_rail.py

⚠ **前置：演示数据必须是"发射前夜"**（发射活动链不存在）—— 那条流程的活动名唯一（BR-06），
   链已存在时流程会**秒失败**，本脚本就退化成"验了个短回合"。脚本会自己查一次并在缺前置时
   给出重建命令（`python app/nasa_pms/demo/demo_build.py`）。
⚠ 会**真的写业务数据**（流程会建 4 条活动并基线）—— 跑完想再演一遍，先重建演示数据。
⚠ 不在 `run_gates.py` 里：它需要 LLM + 跑 5–8 分钟，属"按需验收"，与 `verify_agent_quality.py` 同档。
"""
import json
import pathlib
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:4000"
GROUP = "nasa_pms"
FLOW_NAME = "发射链排程 → 体检 → 基线 → 回填实绩"

PASS, FAIL = [], []


def ck(ok, note):
    print(f"  {'✓' if ok else '✗'} {note}", flush=True)
    (PASS if ok else FAIL).append(note)


def _api(path):
    """平台 API（用登录后的 Cookie 会在 Playwright 里做；这里只做无鉴权的探活）。"""
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def _port_open(port):
    import socket
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:                                       # noqa: BLE001
        return False
    finally:
        s.close()


def main() -> int:
    print("右栏长回合验收（跑一条真流程，盯着按钮与答案）")
    print("-" * 62)
    if not _port_open(4000):
        print("  ⚠ SKIP：平台没在跑（python main.py）")
        return 0
    if not _port_open(4100):
        print("  ⚠ SKIP：agent_service 没在跑（python -m fde_platform.agent_service）")
        return 0

    from playwright.sync_api import sync_playwright

    t0 = time.time()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(viewport={"width": 1920, "height": 1080}).new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:140]))
        pg.goto(f"{BASE}/login")
        pg.fill('input[name="username"]', "admin")
        pg.fill('input[name="password"]', "admin")
        pg.click('button[type="submit"]')
        pg.wait_for_url("**/", timeout=15000)
        pg.goto(f"{BASE}/view/{GROUP}/")
        pg.wait_for_selector(".rail, .menu, nav", timeout=15000)
        pg.evaluate("location.hash = '#/process'")
        pg.wait_for_timeout(2500)

        SEND = "aside.agent-rail .agent-rail-actions button.b-pri"
        NEW = "aside.agent-rail button:has-text('＋ 新')"

        # ① 前置：发射链必须**不存在**（否则流程秒失败，验不出长回合）
        act = pg.evaluate("""async () => {
          const r = await fetch('/api/apps/nasa_pms/activity/call/list', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
          const j = await r.json();
          const items = (j.data && j.data.items) || [];
          return items.filter(a => String(a.wbs_no || '').startsWith('400000.04.01')).length;
        }""")
        if act:
            print(f"  ⚠ SKIP：发射链已存在（{act} 条挂在 400000.04.01）——流程会因活动名唯一"
                  f"（BR-06）秒失败，验不出长回合。\n"
                  f"       先重建演示数据：python app/nasa_pms/demo/demo_build.py")
            b.close()
            return 0
        ck(True, "前置：发射链不存在（这一轮会是真·长回合）")

        # ② 开一个新会话（不吃上一次的残留），点流程行的「让 AI 管家跑」
        pg.locator(NEW).first.click()
        pg.wait_for_timeout(1500)
        pg.locator('[data-role="flows"] tr:has-text("发射链") button').first.click()
        pg.wait_for_timeout(4000)

        # ③ **跑动期间：发送按钮必须禁用**（这条就是"能不能发第二条"的判据）
        dis_now = pg.locator(SEND).is_disabled()
        ck(dis_now, "刚发出去：发送按钮已禁用（发不出第二条）")

        # ④ **跑动期间采样 `sending`**（不是按钮的 disabled）：
        #   ⚠ 按钮是 `:disabled="sending || !input.trim()"` —— **输入框空着它本来就禁用** ✗
        #     第一版就是这么写错的：采样 14/14"禁用"，其实测的全是"输入框为空"（假通过）。
        #     先把输入框填上字，再断言，才等价于"发不出第二条"。
        SENDING = ("() => window.Alpine.$data(document.querySelector('.agent-rail-inner')).sending")
        pg.fill(".agent-rail-input textarea", "（验收脚本占位，不会发送）")
        pg.wait_for_timeout(300)
        d0 = pg.locator(SEND).is_disabled()
        ck(d0, "跑动中：输入框有字、发送按钮仍禁用（= 发不出第二条）")
        samples, t_sample = [], time.time()
        while time.time() - t_sample < 210:          # 采 3.5 分钟（覆盖流程主体）
            samples.append(pg.evaluate(SENDING))
            pg.wait_for_timeout(15000)
        ck(all(samples) and bool(samples),
           f"跑动期间 sending 全程为 true（采样 {len(samples)} 次：{sum(1 for x in samples if x)} 次）")

        # ⑤ 等**会话真正 idle**（= 这一轮结束）。⚠ 判据不能用 `/api/flow-runs` 的状态：
        #   它读的是**历史表**（只记已完成的），跑动中那条在 `flow_runs` 里、历史里还没有。
        t_idle, deadline = None, time.time() + 720
        while time.time() < deadline:
            st = pg.evaluate("""async () => {
              // ⚠ 别写 `j.data || j` 那种"兼容"取法：接口出错时它会**静默回退**成非数组，
              //   然后在 `.find` 上抛 TypeError（第三轮就是这么崩的，还看不出原因）。
              const j = await (await fetch('/api/agent2/sessions?group=nasa_pms')).json();
              if (j.status === 'error') return 'ERR:' + (j.message || '');
              const d = window.Alpine.$data(document.querySelector('.agent-rail-inner'));
              const me = (Array.isArray(j.data) ? j.data : [])
                           .find(s => s.session_id === d.sid);
              return me ? me.status : 'MISSING'; }""")
            if st not in ("running", "idle", "awaiting_permission"):
                print(f"      （会话状态探测：{st}）", flush=True)
            if st == "idle":
                t_idle = time.time()
                break
            pg.wait_for_timeout(2000)
        ck(t_idle is not None, f"会话已回到 idle（这一轮结束，用时约 {int(time.time() - t0)} 秒）")

        # ⑥ **从 idle 起 5 秒内**：解禁 + 右栏已能看到**完整**总结（口径见 docstring）
        if t_idle:
            freed = False
            while time.time() - t_idle < 5:
                if not pg.evaluate(SENDING):
                    freed = True
                    break
                pg.wait_for_timeout(300)
            ck(freed, f"idle 后 {round(time.time() - t_idle, 1)} 秒内解禁（sending → false）")
            pg.wait_for_timeout(500)
            ck(not pg.locator(SEND).is_disabled(), "解禁后发送按钮确实可点（输入框里有字）")

        srv = pg.evaluate("""async () => {
          const d = window.Alpine.$data(document.querySelector('.agent-rail-inner'));
          const r = await fetch('/api/agent2/sessions/' + encodeURIComponent(d.sid)
                                + '/messages?group=nasa_pms');
          const j = await r.json();
          const ms = Array.isArray(j.data) ? j.data : [];        // ⚠ j.data **直接就是数组**
          return String(((ms[ms.length - 1] || {}).content) || ''); }""")
        ui = pg.locator('.agent-rail-chat').inner_text()
        srv_txt = (srv or "").strip()
        ck(bool(srv_txt) and (srv_txt[-120:] in ui or len(ui) >= len(srv_txt) * 0.9),
           f"右栏文本 == 服务端会话历史（服务端 {len(srv_txt)} 字 / 界面 {len(ui)} 字）")
        ck(("业务影响" in ui) or ("ACT-04" in ui),
           "右栏内容确实是**落库结论**那一版（不是开头那两句）")

        ck(len(errs) == 0, f"0 pageerror（实际 {len(errs)}）")
        for e in errs[:3]:
            print("      ✗", e)
        b.close()

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：")
        for f in FAIL:
            print("  ✗", f)
        print("  VERIFY_RESULT: FAIL")
        return 1
    print(f"  VERIFY_RESULT: PASS（{len(PASS)} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
