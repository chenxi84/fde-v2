# 架构（Architecture）

FDE 视图 = **Flask 同源静态托管 + Alpine 3 ESM + 原生 ES Modules**，零构建、零外网依赖（Alpine 已入库）。

## 三层结构（公共基座 / 平台公共页 / 业务模块）

```
app/<组>/<应用>/              业务应用（前后端同文件夹）
├── <应用>.py · .db · README.md · resource/    后端（design-plus/CONVENTION.md）
└── view.js · view.html       前端页面（自描述 PAGE_META + 默认导出工厂）
app/<组>/_contracts.md        组级服务契约 dump（生成依据）
view/                         仅平台级与组级（非逐应用）内容
├── lib/                      公共基座（平台级，业务生成只读）
│   ├── alpine.esm.js         # Alpine 3 ESM 构建
│   ├── api.js                # fetch 层（svc/get/post/del）+ 展示工具 + toast
│   ├── shell.js              # bootShell + createShell：动态装配 / hash 路由 / 菜单 / 单一挂载 / pageable
│   ├── styles.css            # 设计系统（全局唯一一份）
│   └── icon.svg              # 平台 favicon 源
├── pages/                    平台公共页（shell 自动挂进每个模块菜单，模块不声明）
│   ├── agent.{js,html}       # 平台 Agent（/api/agent/*，跨应用对话编排）
│   └── console.{js,html}     # 通用服务台（/api/apps + 服务契约自动建表，仅 admin）
└── <组>/                     组级页（可选）：无后端应用的聚合页 <页>.{js,html}，如 dashboard.*
```

**应用前端与后端同文件夹**：模块内没有 `index.html` / `app.js`，也没有独立的
`view/<组>/pages/` 树——应用页就在 `app/<组>/<应用>/view.{js,html}`。通用壳由平台
`fde_platform/templates/view_shell.html` 统一渲染，页面清单与品牌由平台扫描
`app/<组>/<应用>/view.js` 与组级页 `app/<组>/*.js` 约定推导（见下「启动时序」）。

依赖方向单向：业务页 → `/view/lib/`（绝对 import）；平台壳 `view_shell.html` →
`lib/shell.js` 的 `bootShell` →（运行期动态 `import()`）应用页（`/app/<名>/view.js`）
与组级页（`/app/<组>/<页>.js`）；`shell.js` → 平台公共页。业务页之间不互相依赖。

## 部署拓扑

```
浏览器 ──同源── Flask(127.0.0.1:4000)
                 ├── /view/<组>/           组根 → 渲染平台通用壳 view_shell.html（组有视图页面即渲染）
                 ├── /view/<目录>/<文件>    静态放行 view/ 子文件（lib/ · pages/ · 组级页 <组>/<页>.{js,html}）
                 ├── /app/<名>/view.js     应用前端页面（写死端点，text/javascript；同目录 .py/.db 绝不 serve）
                 ├── /app/<名>/view.html   应用前端模板片段（写死端点）
                 ├── /view/                模块清单页（仅列有视图页面的组 → lib/、pages/ 不入清单）
                 ├── /favicon.ico          → view/lib/icon.svg
                 ├── /api/apps/<名>/call/<服务>   服务调用（RPC 风格；X-Fde-Page 头触发页面隐式放行）
                 ├── /api/apps · /api/groups · /api/me · /api/apps/<名>/services
                 ├── /api/my_pages               当前用户页面授权集（shell 菜单渲染源）
                 ├── /api/view_boot?module=<组>  壳启动清单（brand 约定推导 + 有序 pages，任意登录用户）
                 ├── /api/view_registry · /api/view_registry/rescan   页面注册表（admin，扫描 app/ + view/ 动态生成）
                 └── /login · /auth/…      会话鉴权（Flask session Cookie）
```

- **同源** → 无 CORS；fetch 默认携带 Cookie；`/view/`、`/app/<名>/view.*` 不在鉴权白名单（`auth.py WHITELIST_PREFIXES` 仅 `/static/`）→ 未登录访问 302 到 `/login`，fetch 收 401 由 `lib/api.js` 自行跳 `/login?next=<当前路径>`。`/app/<名>/view.{js,html}` 是**前端资源**：需登录，但豁免应用可见性校验（任何登录用户可加载，菜单按页面授权过滤、数据按服务闸门收口）；端点只 serve 写死文件名，同目录 `.py`/`.db` 永不暴露。
- 新增模块**不需要改平台**：建 `app/<组>/` 组、在应用目录放入 `view.{js,html}` 即自动获得托管、清单条目与启动装配（品牌由组名约定推导）。

## 启动时序（关键，勿改）

平台通用壳 `view_shell.html`（`/view/<组>/` 渲染，组名经 `module` 参数注入）的
`<script type="module">` 仅四条语句：

```js
import Alpine from "../lib/alpine.esm.js";
import { bootShell } from "../lib/shell.js";
window.Alpine = Alpine;          // 先置全局：页面工厂体内用到 Alpine.reactive
bootShell("{{ module }}");
```

`bootShell(module)` 的异步装配链（`lib/shell.js`）：

1. `get("/api/view_boot?module=<组>")` 拉启动清单 `{module, brand, pages}`（服务端扫描 `app/<组>/<应用>/view.js` 与组级页 `app/<组>/*.js`，按 `PAGE_META.order` 升序；品牌约定推导）。
2. `Promise.all(pages.map(p => import(p.url)))` **并行动态加载**各页工厂（应用页 `p.url = /app/<应用>/view.js`，组级页 `p.url = /app/<组>/<页>.js`）。
3. 逐页 `Alpine.data(key, mod.default)` 注册（**约定：工厂为默认导出**）并登记 `components`。
4. `Alpine.data("shell", () => createShell({module, brand, pages, components}))` 注册壳组件。
5. **显式 `Alpine.start()`**。
   - ❌ 不要用 cdn 自启动构建（`cdn.min.js`）：defer 执行时 Alpine 会**早于模块**启动 → `shell` 未注册全屏空白。
   - ✅ ESM + `bootShell` 完成注册后显式 start，时序完全确定。
6. 任一步失败（清单 404 / import 报错）→ `bootShell` 渲染错误面板（含返回链接），**不白屏**；401 由 api 层先行跳登录。

`shell.js` 被导入时顺带挂好 x-html 模板所需的 window 全局助手（`dash`/`fmtTime`/`tryParse`——Alpine 表达式对未绑定标识符回落 window）。

> **新页面落盘即生效**：启动清单源自从 `app/<组>/<应用>/view.js` 与 `app/<组>/*.js`
> 的动态扫描（`view_registry` mtime 缓存——被扫描文件 mtime 变化即重扫），故新增/修改
> 页面无需改任何框架文件，浏览器刷新后菜单与授权清单自动更新；管理页「重新扫描」可立即刷新。

## 菜单与挂载（shell.js 的四项平台行为，业务零感知）

1. **菜单合成**：`menu = 启动清单 pages（业务，按页面授权过滤，order 升序）+ 平台页（Agent 按页面授权；服务台仅 admin）`。平台页自动追加在尾部——业务页面**不声明**它们。
2. **按页面授权渲染**：init 拉 `/api/my_pages`（角色页面授权集，见 users.py `role_page_grants`；admin → `is_admin=true` 全通）→ 业务项按 `<模块>:<页key>` 过滤。授权集到达前菜单为**空**（杜绝短暂暴露）；直访无授权 hash 路由经 `syncRoute` 回落首个授权页。**数据闸门在后端，菜单只是展示层收口——页面不做任何权限判断。**
3. **页面上下文（隐式放行的钥匙）**：`syncRoute` 时写 `window.__fdePage`（业务页 = `<模块>:<key>`，平台页 = `_platform:<key>`）；`lib/api.js` 的 `svc()` 据此注入 `X-Fde-Page` 请求头。后端闸门：角色获授该页 ∧ `view_registry` 派生表含 `(app, service)` 边 → 放行（无需显式服务授权）。派生表由扫描页面源码 `svc()` 字面量得来——故**页面调服务必须字面量**（变量拼名只许服务台用）。伪造头无升级空间：声明的页仍要过角色授权校验。
4. **单一挂载点**：平台通用壳 `view_shell.html` 主区固定为

   ```html
   <template x-for="r in [route]" :key="r">
     <div class="page-in" x-data="mount()" x-html="tpl"></div>
   </template>
   ```

   - `x-for` 单元素数组 + `:key=route`：route 变 → key 变 → **销毁旧页、重建新实例**（新 `init()` 拉最新数据，正是所需）。
   - ❌ 不能写成 `x-if="route"`：条件恒真，`x-if` 不随 `:key` 重建 → 所有路由粘滞在首页（详见 pitfalls #2）。
   - `mount()` 按 route 查注册表（模块 `components` + 平台页内置组件）返回页面工厂实例；`x-html` 注入的模板片段 **Alpine 会自动初始化其中指令**（x-html 内部 initTree）——这是「js + html 分文件」方案成立的前提。

## API 契约（lib/api.js 已封装）

- 调服务：`svc(app, service, params, opts)` → `POST /api/apps/<app>/call/<service>`（业务页上下文且 `app` 为短名时，api.js 按 `window.__fdePage` **组内解析**，实际请求改写为 `/api/apps/<组>/<应用>/call/<服务>` 的 qualname 路径——页面代码只写短名，无感知）；`opts = {quiet: true}` 静默（仅抑制错误 toast 与 throw，**不抑制 401 跳登录**——调用方自行处理错误；看板对受限用户的探测性加载必用）。自动注入 `X-Fde-Page` 头（页面授权隐式放行依据；见上节第 3 条）。
- 响应归一：`{status:"ok", data}` / `{status:"error", kind:"business|params|system", message}`；`request()` 统一：
  - 401 → `location.href = /login?next=<location.pathname>`
  - 403 / 404 / 业务 error → `toast(message, "err")` 并 throw（quiet 除外）
- 只读接口直接 `get(path)`：`/api/apps`（应用清单：name/group/services，即当前用户授权集）、`/api/apps/<名>/services`（服务契约：参数 required/default/json_type）、`/api/groups`、`/api/me`（登录用户：username/role/role_label/is_admin）。
- 列表服务惯例返回 `{total, items, page}`；单号生成形如 `SO-YYYYMMDD-NNNN`。

## 鉴权语义（视图必须遵守）

- 视图**不做**认证、**不做**授权实现：未登录 → 登录页；菜单按**角色页面授权**渲染（shell 统一负责，授权在管理页按角色配置，选项由 `view_registry` 扫描 `view/` 动态生成）；页面内不判断"我有没有权限"，一切调用以后端返回为准。
- **有效服务访问 = 显式服务授权 ∪ ⋃派生(角色已授权页面)**。派生 = 页面源码 `svc()` 字面量扫描结果；隐式放行仅对携带 `X-Fde-Page` 的调用生效，无头请求（MCP/Agent/CLI）仍按显式授权。
- 服务台（console）仅 admin 可见、不可授权（动态调用不可派生，授权它 ≈ 放行全部服务）。
- 看板等聚合页对探测性加载用 `quiet` + `.catch` 零值兜底；用户主动操作保持非静默（失败要可见反馈）。

## 验证体系

- Playwright + Chromium 无头实测（`pip install playwright && python -m playwright install chromium`）。
- `fde_platform/dbguard.py isolate_dbs()`：测试前移走全部应用库/平台库，结束原样还回——**测试绝不污染用户数据**；守卫带跨进程互斥锁（`fde_platform/.dbguard.lock`），**并行跑测试会被干净拒绝**（2026-07-30 并行踩踏曾洗掉用户库，勿绕）。
- 范式模板：`design-plus/前端验收样板/verify_view_e2e.py`（登录 → 壳断言 → 逐路由渲染含挂载防粘滞守卫 → 浏览器内造数 → 逐模态字段断言 → 受限用户菜单过滤断言含 403 豁免 → 0 console error）。
