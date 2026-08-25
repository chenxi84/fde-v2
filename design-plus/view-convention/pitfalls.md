# 踩坑清单（Pitfalls）

视图构建中真实踩过的坑，新模块务必绕开。

> **条目编号是稳定 ID**（被 `design-plus/` 九步法各规格 / 本目录 `architecture.md` 按号引用），瘦身合并后留有**空号**，不重排——引用方按号直达，新增坑续用空号或往后追加。纯"架构事实"（系统当前如何工作，无反直觉踩坑点）已归入 `architecture.md` / `patterns.md`，见文末速查，不再当坑记录。

## Alpine / 前端

1. **Alpine 启动时序（历史警示）**：早期用 cdn 自启动构建（cdn.min.js）+ defer，会在壳组件注册**之前**启动 → 全屏空白；改同步加载又被 Alpine 拒绝。✅ 唯一正解已固化为平台壳 `bootShell` 的 ESM 异步链（`lib/alpine.esm.js` + 组件注册完显式 `Alpine.start()`），架构见 `architecture.md`——业务页不碰启动逻辑。
2. **挂载粘滞：x-if 恒真不随 :key 重建（2026-07-30 重构实测）**：单一挂载点写成 `<template x-if="route" :key="route">` 时，条件恒为真，`x-if` **只在条件真假翻转时重建子树，完全不理会 :key** → 切换路由后主区永远停在首次挂载的页面（且顶栏标题正常变化，极难察觉；测试里"页面有卡片"的断言还会假过，因为首页看板到处是卡片）。✅ 唯一正解：`x-for` 单元素数组 + `:key`——
   ```html
   <template x-for="r in [route]" :key="r">
     <div class="page-in" x-data="mount()" x-html="tpl"></div>
   </template>
   ```
   route 变 → key 变 → x-for 按 key diff 销毁重建。测试要加防粘滞守卫：非看板页断言 `pg.locator(".kpi").count() == 0`（看板特征元素）。
3. **响应式绕过**：页面工厂若用裸对象（`const self = {...}`），方法里 `self.x = v` **不触发重渲染**（数据变了画面不动）。✅ 必须 `Alpine.reactive({...})`。
4. **x-html 前提**：模板片段经 `x-html="tpl"` 注入，Alpine 会初始化其中指令——这是整套"js+html 分文件"方案成立的基础，勿改成 innerHTML 手拼。
5. **模板/模块抓取一律 import.meta.url + 绝对路径**：`fetch("pages/x.html")` 是**文档相对**（相对浏览器地址栏的 `/view/<组>/`），页面文件一旦搬移就 404；页面迁进 `app/<组>/<应用>/` 后，旧的 `../../lib/api.js` 相对路径深度变了也解析错（原 #29 并入）。✅ 模板用 `fetch(new URL("view.html", import.meta.url))`（模块相对）；import 公共基座一律**绝对路径** `import "/view/lib/api.js"`（与文件所在深度彻底解耦，组级页同理）。
6. **hash 导航不重载页面**：`goto` 同 URL 只改 hash，SPA 状态保留——调试/测试要强制刷新（`pg.reload()`）才能回到初始态。新写页面后测试里也要 `pg.reload()`（注册表 mtime 缓存，刷新即重扫）。

## 权限 / 菜单

8. **svc 字面量是隐式放行的命脉**：后端 `view_registry` 靠扫描页面源码里的 `svc("app", "service")` **字面量**派生"页→服务"边——角色获授页面即隐式放行这些服务。变量拼名（`svc(appVar, ...)`）**扫不到 → 受限用户该调用 403**（dashboard 主链管道曾因此踩雷：`defs.map(([, app]) => svc(app, "list"))`，改成每列一个 `svc: () => svc("settlement", "list", …)` 字面量闭包才好）。✅ 规则：服务调用一律字面量（可闭包逐项写）；三元拼服务名也不行（`svc("approval", ok ? "approve" : "reject")` → 拆成 if/else 两条字面量）。变量拼名**只许服务台用**（它仅 admin 可见、不参与派生）。
9. **X-Fde-Page 头不用管也不能滥用**：`lib/api.js` 的 `svc()` 自动注入当前页上下文（shell 在 `syncRoute` 时写 `window.__fdePage`）。页面代码不要手工设/改这个头；也不要假设"带头就能调"——放行还要求该页确属调用者角色（伪造无升级空间）。无头请求（curl/MCP/Agent）不享受隐式放行。
10. **恒显探测用 quiet**：看板等聚合页的初始加载一律 `svc(app, svc, params, {quiet: true})` + `.catch` 零值兜底——即使派生放行覆盖不全，也不给受限用户喷错误 toast（用户主动操作仍保持非静默）。

## 字段 / 契约

11. **详情字段 ≠ 创建参数**：`get()` 展示的很多字段来自快照/推导（如 SO 抬头的组织、联系人），`create` 并不接受。✅ 表单字段必须读 create/update **源码**或 dump `/api/apps/<名>/services` 契约，逐参数对应。
12. **枚举值要对齐后端校验**：如 trading_entity 后端只收 股份/重庆/普恩/上海贸易，表单 select 给错值会吃业务错误。
13. **必填联动**：如 SO 行项目在外销时贸易 6 字段必填（BR-03）——表单按 `domestic_export === '外销'` 显示红星提示，后端仍会兜底报错。

## Playwright 测试（verify_view 系列）

14. **x-show 隐藏 ≠ 不存在**：隐藏页签的表格/按钮仍在 DOM，`pg.locator(...).first` 会命中**隐藏元素**并卡在等待可见。✅ 用 `:visible` 限定（`button:visible:has-text(...)`）或按可见卡片 scope（`.card:visible table.tbl tr.data`）。
15. **一个模态多个 .modal-bd**：详情 + 内嵌编辑区各有一个 `.modal-bd`，直接 `.inner_text()` 触发 strict mode 超时。✅ `.modal-bd").first.inner_text()`；读页脚按钮文案时读整个 `.modal-mask:visible`。
16. **模态加载态抢跑**：点开模态后 `docno` 先是占位文案（如「销售订单」），数据到达才换成单号。✅ `wait_modal()`：轮询 `.modal-mask:visible .loadbox` 消失再断言。
17. **列表顺序不假设**：多单号时 `.first` 可能命中新单（列表按新到旧）。✅ 用精确单号定位：`has_text=r["so"]`。
18. **造数走真实 REST**：在 `pg.evaluate` 里 fetch `/api/apps/.../call/...`（带会话 Cookie），别绕平台直连 DB——保证与真实链路一致。

## 工程细节

20. **Windows CRLF + sed**：被 sed 改过的文件行尾可能是 CRLF，后续 Edit 的 old_string 要先 Read 取真实文本再匹配。
21. **node --check**：每个页面 js 写完先 `node --check`，语法错误比运行时错误便宜得多。注意它查不出"漏了 `export default`"（见 #26）。
22. **样式单一共享（规范表是 fde.css，styles.css 只是别名）**：设计系统规范表唯一一份 = `fde_platform/static/fde.css`（登录页等鉴权前页面须经 `/static/` 可达）；`view/lib/styles.css` 已降级为一行 `@import url("/static/fde.css")` 的**别名**（自注"勿在此扩写"）。✅ 新增组件类一律追加在**规范表 fde.css**（向用户说明），**不要**往 `styles.css` 别名或模板内联样式里扩写——2026-08 前旧文档说"追加在 styles.css 末尾"已作废。业务生成不得为模块复制样式文件。

## 动态加载与自描述页面

25. **`window.Alpine` 必须先于页面工厂执行置好**：通用壳在 `bootShell` 之前 `window.Alpine = Alpine`。页面工厂体内用 `Alpine.reactive` 无碍（挂载时全局已就位），但顶层即触碰 Alpine 的代码会挂——约定页面只在工厂体内用 Alpine。
26. **工厂必须默认导出**：`bootShell` 读 `mod.default` 注册。漏了 `default`（仍用命名导出 `export function pageXxx`）→ 该页 `mod.default` 为 undefined，菜单有项但点了是空实例且不报错（静默）。`node --check` 查不出这个，需确保 `export default function`。
27. **`PAGE_META.order` 必须显式给**：不给则该页排到所有有 order 的页之后（按 key 兜底排序），菜单顺序失控。以 10 为步长（10/20/30…）预留插入空隙。`order` 是扫描解析的数字字段，写错成字符串会被当缺失处理。

## 前后端同文件夹

35. **应用页模板固定名 `view.html`**：`view.js` 抓 `new URL("view.html", import.meta.url)`，serve 于 `/app/<名>/view.html`。别把模板叫回 `<应用>.html`——端点只认 `view.html`。组级页例外：模板与页面同名（`dashboard.html`），走 `/app/<组>/` 静态。

## 模块构建（2026-08 e2e 模块实测新增）

36. **每个模块必须有 dashboard 组级页（最致命的静默崩溃）**：平台壳 `shell.js` 的默认路由写死 `route: "dashboard"`（`view/lib/shell.js`）。模块若没有 `app/<组>/dashboard.{js,html}`，授权集到达**之前**的预渲染窗口与受限用户回落都会把空 `{}` 挂到默认路由上 → 模板里 `x-html="tpl"` 对 `undefined` 求值，连同看板要引用的 `list.items` 等一起喷一片 console error。2026-08 给 e2e 模块只建了应用页、漏了看板，verify_view 首屏即 5 个报错。✅ 规则：**新建模块 = 必产 `app/<组>/dashboard.{js,html}`**（key="dashboard"、PAGE_META.order 给最小、quiet 探测 + 零值兜底，照抄 `app/e2e/dashboard.*`）；它不是"可选聚合页"，是壳能正常启动的前提。
37. **reactive 状态必须同步建好，再 await**：页面工厂的 `init()` 若先 `await`（如 `await loadMembers()`）再创建某个 `Alpine.reactive` 子对象（如 `self.list = pageable(...)`），`self.tpl` 一旦赋值 Alpine 即注入模板并求值 `list.items/total/page`，此刻 `list` 仍是 `null` → 「reading 'items' of null」。2026-08 task 页 init 先 await 成员映射、后建 list，首屏喷 4 个 null 错。✅ 规则：工厂体内**一切会被模板引用的 reactive 状态，必须在第一个 `await` 之前同步初始化**（list 先 `pageable(...)` 建好含空 `items:[]`，再 `await loadMembers()`，最后 `await self.list.load()`）——对标 e2e 范式。
38. **加页面 = 同步更新 verify 受限用户断言（耦合极易漏）**：模块新增页面（尤其看板）后，`app/<组>/tests/verify_view_<组>.py` 里两处必须跟着改，否则受限阶段误报 403 / 回落断言失败：① 受限角色的授权清单要加上新页（如 `users.set_role_page_grants("limited_role", ["<组>:dashboard", "<组>:member", "_platform:agent"])`）——新页进菜单后预渲染窗口会带 `X-Fde-Page="<组>:<新页>"` 发 svc，未授权即 403；② 直访无授权路由的**回落断言**要改成菜单首项（看板成 menu[0] 后回落目标由「某应用」变成「首页看板」）。2026-08 e2e 加看板后这两处没同步，多出 2 个 403。✅ 规则：改完页面把 `verify_view_<组>.py` 的 `limited_role` 授权清单与回落断言逐字对一遍（照 `verify_view_e2e.py` 范式）。
39. **dbguard 隔离 + 平台配置库随清单演进（2026-07-30 洗库事故 / 2026-08 补 llm.db）**：① 一切测试必走 `fde_platform/dbguard.isolate_dbs()`：进入时移走全部应用库/平台库，退出（含断言失败，经 atexit）原样还回——**用户数据分毫不丢**；并行跑多个 verify 会互踩共享暂存洗掉用户库（2026-07-30 事故），故守卫持跨进程独占锁 `fde_platform/.dbguard.lock`，第二个并发进程干净拒绝（原 #19 并入）。② `dbguard._CONFIG_DBS` 枚举 `config/` 下的平台库，**新增任何 `config/*.db`（2026-08 前漏了 `llm.db`）必须同步加进清单**，否则用户真实配置泄漏进测试、使"未配置降级"类断言失准。③ 测试里逼 LLM 降级路径用 `FDE_LLM_RETRIES=1`/`FDE_LLM_BACKOFF=0` 压短重试（`fde_platform/llm.py` 读取，默认 3/8），连接拒绝即秒回，避免默认退避拖超测试超时。

## 架构事实速查（不是坑，详见 architecture.md / patterns.md）

以下曾是清单条目，实属"系统当前如何工作"的架构事实（无反直觉踩坑点），已归入 `architecture.md`，此处仅列主题防重复记录：

- 页面零鉴权 / 菜单按角色页面授权渲染、直访无授权路由回落首授权页（原 #7）
- 通用壳是平台模板 `view_shell.html`，模块内无 `index.html`/`app.js`（原 #24）
- 新页面落盘后浏览器刷新进菜单、注册表 mtime 缓存（原 #28）
- 动态 `import()` 的绝对 / 模块相对 URL（原 #29，抓取规则见 #5）
- `bootShell` 对清单 404 / import 报错渲染错误面板兜底（原 #30）
- 应用前端只经写死端点 `/app/<名>/view.{js,html}` serve、`.py`/`.db` 绝不暴露（原 #32，红线见 README §测试与验收红线）
- `/app/<名>/view.*` 端点豁免应用可见性校验（原 #33）
- dashboard 是无后端应用的组级页、住 `app/<组>/`（原 #34）
- favicon 由平台统一提供、各模块不单独配（原 #23）
