# FDE 前端视图约定（VIEW_CONVENTION v1）— 正本

> 本文件是 FDE v2 **前端视图约定的唯一正本**，与 [`design-plus/CONVENTION.md`](CONVENTION.md)（后端应用约定正本）并列。
> 九步法前端段各规格（`design-plus/前端设计.md` / `前端编码.md` / `前端测试.md` / `前端测试执行.md`，第⑥–⑨步）均以本正本为准。
> 配套参考资料见同目录 **`design-plus/view-convention/`**：`architecture.md`（三层托管 / 启动时序 / 菜单与挂载 / API 契约）、`patterns.md`（页面工厂 / 列表 / 模态 / 表单）、`design-system.md`（设计令牌与组件目录）、`pitfalls.md`（历次踩坑清单，条目编号为稳定 ID）。

为 FDE v2 平台某个应用模块（`app/<组>/` 下的应用集合）生成浏览器工作台。

## 三层结构与生成边界（核心，先读这个）

```
app/<组>/<应用>/                 业务应用（前后端同文件夹，本规范的生成目标）
├── <应用>.py · <应用>.db · README.md · resource/    后端（design-plus/CONVENTION.md 约定）
└── view.js · view.html                              前端页面（自描述 PAGE_META + 模板片段）
app/<组>/<页>.{js,html}          组级页（可选，无后端应用的聚合页）：<页>.{js,html}，如 dashboard.*
app/<组>/_contracts.md           组级服务契约 dump（生成依据）
view/                            仅平台级内容（业务生成不得修改）
├── lib/        公共基座（全模块共享，平台所有）：alpine.esm.js · api.js · shell.js · styles.css · icon.svg
└── pages/      平台公共页（每个模块自动获得）：agent.* · console.*
```

前端与后端**完全同构且同文件夹**——约定优于配置、扫描即发现、零登记，且**一个应用的
前后端住在同一个文件夹里**：`app/<组>/<应用>/` 既有后端 `<应用>.py`，也有前端
`view.js`/`view.html`——一次生成、整文件夹交付，丢进平台即可用。组 = `app/<组>/` 一级
目录（后端约定），品牌 / 壳 / 菜单 / 路由全部由平台约定推导，**无任何框架文件、无配置
文件**。平台通用壳 `view_shell.html` 在 `/view/<组>/` 根渲染，`bootShell(组名)` 拉
`/api/view_boot` 页面清单（平台扫描 `app/<组>/<应用>/view.js` 与组级页 `app/<组>/*.js`
合并得出）、动态 `import()` 各页工厂、注册 Alpine 组件后启动。

- **生成发生在应用文件夹内**：前端页面 `view.js`/`view.html` 直接写进该应用的后端目录 `app/<组>/<应用>/`。`view/lib/` 与 `view/pages/`（平台公共页）是平台级基础设施：规范只记载其 API 契约供页面调用，**业务生成不得修改**（公共能力的演进是平台任务，不是视图生成任务）。
- 由此：**新增一个应用的前端 = 在 `app/<组>/<应用>/` 下只写 2 个文件**（`view.js` + `view.html`，页面自描述）——**零接线**，放进目录即出现在菜单。**新建模块 = 建 `app/<组>/` 组并放应用**（前端随后逐应用补 view 文件；无脚手架文件，品牌由组名推导：`FDE·<组名大写>`，脚标 `<组名> 组 · N 页面`）。`view/lib/`、`view/pages/` 与平台零改动。
- **授权同样零接线**：新页面文件落盘即被平台注册表（`view_registry` 扫描）自动纳入角色授权清单（管理页「用户与角色管理」→ 角色 → 前端页面授权）；页面源码里的 `svc()` 字面量调用被扫描为"页→服务"派生边，角色获授该页即**隐式放行**这些服务，无需再逐个授服务。
- **业务页代码范式一律以 `design-plus/view-convention/patterns.md` 为准**（范式成文化，参考实现 = `app/e2e/<应用>/view.*` + `app/e2e/dashboard.*`，按现行约定实测的模块）：页面工厂、模态、列表、表单照抄范式结构、不发明新架构。

## 开工前必读（每次）

1. **代码范式（唯一例行范式输入）**：`design-plus/view-convention/patterns.md` —— 页面工厂 / 列表 / 模态 / 表单 / 模块装配的逐块骨架，照抄结构换业务字段。范式经**参考实现 `app/e2e/`**（member/task 两应用页：`view.js` 自描述 PAGE_META + 默认导出工厂、`view.html` 模板片段，与后端同文件夹）+ `view/e2e/dashboard.*`（组级看板）实测；新模块照此起步。patterns 未覆盖的特殊页面形态（网关 / 变更单 / 审批型等）按 §工作流第 3 步⑤ 的文字描述设计。`app/e2e/_contracts.md` 可作契约速查样例。
2. **公共基座 API**（`view/lib/`，只读环境前提）：
   - `api.js` —— `svc/get/post/del` + `hue/fmt/dash/fmtTime/tryParse/plusDays/liveStatus` + `toast`（svc 在业务页上下文自动把短名改写为 `/api/apps/<组>/<应用>/call/<服务>` qualname 路径；quiet 仅抑 toast，不抑 401 跳登录——详见 `architecture.md` API 契约节）
   - `shell.js` —— `bootShell(module)`（平台壳调用：拉启动清单 → 动态 import 各页 → 装配菜单 → 启动 → `watchSortableTables()` 列表排序 + 自定义显示列自动装饰）、`createShell({module, brand, pages, components})`（路由 / 页面授权菜单 / 平台页追加 / 页面上下文头 / 单一挂载）、`pageable()`（分页 + 排序态 `sortBy/sortIcon`）；自定义显示列经 `/api/prefs/cols:<页>` per-user 持久化
3. **本正本参考资料**（`design-plus/view-convention/`）：
   - `architecture.md` —— 三层托管 / 启动时序（bootShell）/ 菜单与挂载机制 / API 契约
   - `patterns.md` —— 页面工厂（PAGE_META + 默认导出）/ 列表 / 模态 / 表单
   - `design-system.md` —— 设计令牌与组件目录（`view/lib/styles.css`）
   - `pitfalls.md` —— 历次踩坑清单（异步启动、PAGE_META.order、挂载重建、选择器陷阱等）
4. **平台现状**：组 = `app/<组>/` 一级目录；某组只要有视图页面（任一应用含 `view.js`，或 `app/<组>/` 有组级页松散文件）即成模块——`/view/<组>/` 渲染平台通用壳，模块清单页（`/view/`）只列这些组，故 `view/lib/`、`view/pages/` 天然不进清单。**应用页经写死端点 `/app/<名>/view.{js,html}` serve**（只认这两个文件名，同目录 `.py`/`.db` 绝不暴露）；**组级页经 `/app/<组>/<页>.{js,html}` serve**；`view/lib/`、`view/pages/` 经 `/view/…` 静态放行。**新模块无需改平台任何代码**。
5. **菜单与授权机制（shell + 平台统一负责，生成物零感知）**：
   - 菜单按**角色页面授权**渲染：shell 拉 `/api/my_pages`（角色获授的页面集，admin 全通），业务项按 `<模块>:<页key>` 过滤；授权集到达前菜单为空（不暴露）。
   - 平台公共页：Agent 可按页面授权；**服务台（console）仅 admin 可见、不进授权清单**（其服务调用是动态的、不可派生）。
   - **页面授权隐式放行服务**：平台扫描页面源码的 `svc("app","svc")` 字面量得"页→服务"派生边；`lib/api.js` 的 svc() 自动带 `X-Fde-Page` 头，闸门对"已授权页 ∧ 派生边命中"的调用放行——**角色只需授页面，不必逐个授服务**。
   - 直访无授权 hash 路由回落首个授权页。**页面不做任何鉴权逻辑**。
6. **页面自描述 + 动态装配**：每个页面文件自带 `PAGE_META`（key/name/ic/title/crumb/order），平台扫描得启动清单，壳经 `import()` 动态加载默认导出工厂。**菜单顺序由 `PAGE_META.order` 决定**（升序）——这是唯一需要精心编排的字段。

## 页面规划原则（先于一切设计）

1. **菜单与 APP 一一对应**：侧栏菜单项 = 模块内每个应用（一个应用一个页面），**除「首页看板」外不得规划合并多应用的工作台**（不按角色归并、不按流程段归并）。
2. **首页看板是唯一例外，且每个模块必备**：`dashboard` 做跨应用聚合——KPI 指标带、主链管道（状态分布）、待办队列（如待审批），点数字/单号跳到对应应用页。看板对受限用户恒显，故其初始加载一律 `quiet` 探测 + 零值兜底（不喷错误 toast）。**新建模块必须产出 `app/<组>/dashboard.{js,html}`（key="dashboard"）**——平台壳默认路由写死 `dashboard`（`view/lib/shell.js`），缺看板会导致预渲染/受限窗口把空 `{}` 挂上默认路由、`x-html="tpl"` 对 undefined 求值而整片报错（见 pitfalls #36）。
3. **每个应用页 = 该应用的完整增删改查**，统一解剖结构（见工作流第 3 步）：
   - **列表**：展示关键字段（不止单号+状态，防遗漏）+ 关键字段搜索条件；
   - **详情模态**：点单号弹出，展示**全部**业务字段；
   - **创建/编辑表单**：覆盖**所有**业务字段（审计字段除外）。
4. **`PAGE_META.order` 编排**：`dashboard` 给最小 order（如 10）居首 → 各应用**按业务分段递增**（如 审批流 / 基础数据 / 正向业务 / 退货业务 / 其他，段内按业务流转序，**单据与其变更单相邻**，见 e2e 参考实现）——order 升序即侧栏顺序。**建议以 10 为步长**（10/20/30…）预留插入空隙。**不要在页面里声明 Agent / 服务台**——平台页由 shell 自动追加在菜单尾。
5. **增删改查总体一致**：同模块所有应用页共用同一套列表三段式、模态三段式、表单布局与校验提示风格（细则见 `design-plus/view-convention/patterns.md`）。

## 工作流（按序执行）

### 第 1 步：侦察模块与契约（契约先行，绝不猜字段）

```bash
ls app/<组>/                           # 模块内应用清单
python -m fde_platform.contract_dump <组>   # dump 全部服务契约 + 真实 get/list 返回 → app/<组>/_contracts.md（平台入口：/groupbuild ⑧ 契约冻结，沙箱造数取样；手工轨：此即第⑤步跑绿后的「最终冻结」硬门禁，须晚于最后一次后端代码变更，见《工具链使用说明.md》第 6 步两级冻结）
```
- 服务契约：起平台后 `GET /api/apps` 与 `GET /api/apps/<名>/services`（每个服务的参数名 / required / default / json_type / 说明）。
- **真实返回结构**：`_contracts.md` 已在沙箱副本内跑通业务链（造数链产真实 payload、一次性副本即隔离，不碰真实库）并 dump 核心单据 `get()`/`list` 返回——**模态与表单的字段一律以真实契约/返回为准**。
- 读对应应用的 create/update/set_*/import_batch 源码，确认**写操作实际接受哪些参数**（详情里展示的字段 ≠ 创建时能传的字段，例如 SO 抬头的组织/联系人字段来自快照，create 并不接受）。

### 第 2 步：确认模块（组）布局（仅模块首建时；已有模块跳过）

模块即后端组 `app/<组>/`——**前端不需要自己的模块目录/脚手架**：
- 通用壳、品牌、菜单、路由由平台自动提供（`view_shell.html` + `bootShell` + `/api/view_boot`）；某组只要有应用带 `view.js` 就自动成为视图模块。
- 品牌按约定推导：`name = FDE·<组名大写>`、`sub = FORWARD DEPLOYED`、`foot = <组名> 组 · N 页面`。
- **逐应用页面放各自 `app/<组>/<应用>/view.{js,html}`**（第 3 步）；组级聚合页（如 dashboard，无对应后端应用）放 `app/<组>/<页>.{js,html}`（松散文件，与组内应用子目录并列）。
- 组级契约速查 `_contracts.md` 由 dump 工具写到 `app/<组>/_contracts.md`。

**不得**为新模块复制 alpine / api.js / styles.css / shell——页面一律用**绝对路径** `import "/view/lib/api.js"`（文件与目录深度解耦，搬移不用改）。新组件样式先想能否用现有类；确需新增，追加在**规范表 `fde_platform/static/fde.css`**（`view/lib/styles.css` 已是 `@import` 别名，勿在别名扩写；这属公共层演进，要在报告里向用户说明）。

### 第 3 步：逐应用构建页面（`app/<组>/<应用>/view.js` + `view.html`）

每个应用一个**自描述**页面文件，**就放在该应用的后端目录里**（骨架见 `design-plus/view-convention/patterns.md` §1）：

```js
/* app/<组>/<应用>/view.js —— 与 <应用>.py 同文件夹 */
import { svc, hue, fmt, toast } from "/view/lib/api.js";     // 绝对路径，勿用相对
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "xxx", name: "中文名", ic: "◈",
  title: "页面标题", crumb: "副题 · 要点",
  order: 30,                       // 升序即菜单顺序，建议 10 步长
};

export default function pageXxx() {
  /* Alpine.reactive 工厂体；模板抓取 fetch(new URL("view.html", import.meta.url)) */
}
```

- **应用页 key = 应用文件夹名**（与后端应用名、page_id 对齐；PAGE_META.key 仅组级页/缺省时用）；`name`/`ic`（菜单）、`title`/`crumb`（主区头）、`order`（排序）。
- **工厂必须默认导出**（壳读 `mod.default`）；函数名保留 `pageXxx` 专名（栈轨迹/grep 友好）。
- **模板文件固定名 `view.html`**，经 `new URL("view.html", import.meta.url)` 抓取（相对自身 URL，serve 于 `/app/<名>/view.html`）。
- 统一按下列解剖结构实现（增删改查一致性的落点）：

**① 列表区（查）**
- **关键字段必须展示，防止遗漏**：从该应用 `list` 返回项的字段中选取关键业务列——单号、状态、归属（客户/上级单号）、关键数量/金额、关键时间、关联单号，宁多勿少（宽表用 `.scroll-x` + `.tbl.tight`）；**列表列必须是详情字段集的子集**。
- **关键字段搜索条件**：搜索控件与后端 `list` 服务签名中的可过滤参数**一一对应**（如 `list(status, customer_no, keyword, page, size)` → 状态 chips + 客户下拉 + 关键字框）；后端不支持的参数**不要自造前端假过滤**（要过滤先给后端 list 加参数）。
- `pageable()` 分页；单号列 `.b-link` 点开详情模态；操作列按状态 `x-show` 行内动作（删/撤/审批等）。
- **列点击排序（平台自动，零改动）**：平台 `watchSortableTables()` 自动为可解析的列表表头挂排序（点击三态 升→降→默认序，▲▼ 指示），经平台保留参数 `sort_by/sort_dir` 由后端排序后返回当前页——页面**无需写排序代码**，操作列/复合列自动跳过、模态内表格不装饰。

**② 详情模态（查全）**
- `get()` 返回的**全部业务字段**按语义分 `.kv` 组（`.sec` 小节标题）；子账本（行项目/流水/批次）用 `.tbl.tight`；`*_json` 快照字段 `tryParse()` 结构化展示；底部折叠「原始数据」JSON；页脚 `.modal-ft` 按状态放操作。
- 审计字段（created_at/created_by/version 等）**可以不显示**（在原始数据里仍可查）。

**③ 创建/编辑表单（增/改）**
- **覆盖所有业务字段**：= 后端写服务（create / update / set_* / import_batch）**接受的全部业务参数**；必填红星、可选收进「更多字段 ▾」折叠区；枚举用 select 且选项与后端校验值完全一致。
- 字段分工：create 接受的进创建表单；仅 update/set_* 接受的进编辑入口；纯快照/推导字段（任何写服务都不接受）**只在详情展示**并在相应位置注明"自动生成/快照"，不放表单。
- 审计字段不进表单。
- 有 update/set_*/import_batch 的应用**必须**给编辑入口（模态内小编辑区，或复用创建表单预填 + `mode='edit'`，键字段锁定）。

**④ 一致性约束（同模块内强制）**
- 所有应用页共用：列表三段式（过滤区 / 表格 / 分页条）、模态三段式（墨青头带+状态徽章 / KV 分组体 / 状态操作页脚）、表单布局（必填先行、按语义分组 frow、底部右对齐提交按钮）、校验提示（必填红星 + toast 警告）、展示工具（`hue()`/`dash()`/`fmt()`/`fmtTime()`/`tryParse()`）。
- 字段排列顺序在同一单据的列表/详情/表单间保持一致（单号→状态→归属→数量金额→时间）。

**⑤ 特殊应用**
- 主数据类（customer/product 型）：列表 + 同步按钮（`sync_status` 徽章）+ 手工新建·编辑（`import_batch` upsert，编辑态锁定键字段）。
- 网关/台账类（*_gateway 型）：outbox/inbox 列表 + 详情（重投/查结果按服务暴露的动作给按钮）。
- 纯内部回调型应用（只有 on_* 服务、无用户主动操作）：页面给出说明卡 + 记录列表，不硬造表单。

每写完一个 js：`node --check app/<组>/<应用>/view.js`。**无需任何接线**——文件落盘即进启动清单与授权清单（平台 mtime 缓存，浏览器刷新后生效；管理页「重新扫描」可立即刷新注册表）。

### 第 4 步：端到端验证（不可跳过）

新建验收脚本（两级粒度：逐应用 `app/<模块>/tests/verify_view_<模块>_<应用>.py` 各管一页 + 组级 `app/<模块>/tests/verify_view_<模块>.py` 管壳/菜单序/受限用户/dashboard），照 `design-plus/前端验收样板/verify_view_e2e.py` 范式（受限会话机制含 403 豁免分支、角色名 `limited_role`，六类断言齐全；逐应用脚本为范式按页切片，组级脚本与范式同构）：
- `fde_platform.dbguard.isolate_dbs()` 隔离 + 动态端口起 `main.py`（运维红线——隔离 / 串行 / 跑前杀 dev server——见 README §测试与验收红线）；
- 登录后浏览器内 fetch 造数（走真实 REST）→ 逐页切换断言有内容（非看板页断言无 `.kpi`，防挂载粘滞假过）→ 逐模态断言关键字段 → 表单字段完备性断言 → 写操作真实落库回显断言；
- 受限用户菜单过滤断言（**组级脚本内**：播种仅授权一两个应用的用户 → 菜单收敛为「看板 + 授权应用 + 平台页」，直访无授权路由回落看板）；
- 全程 0 console error / 0 pageerror / 0 HTTP≥400（受限会话的 403 属预期执法，单独豁免）；
- 选择器规则见 `design-plus/view-convention/pitfalls.md`（`:visible` 限定、模态多 `.modal-bd` 用 `.first`、`wait_modal()` 等加载态消失、精确单号定位）。

收尾：
- 新测试的**精确命令**（逐应用 `Bash(python app/<模块>/tests/verify_view_<模块>_<应用>.py)` ×N + 组级 `Bash(python app/<模块>/tests/verify_view_<模块>.py)`）加进 `.claude/settings.json` 白名单；
- **受限用户断言随页面同步**：新增/调整页面后，verify 里 `limited_role` 的页面授权清单与"直访回落"断言要逐字对齐当前菜单（看板成 menu[0] 则回落目标改「首页看板」）——漏同步会在受限阶段误报 403（见 pitfalls #38）；
- 跑全套回归确认无破坏；
- 向用户报告：入口 URL（`http://127.0.0.1:4000/view/<模块>/`）、页面清单、验证结果。

## 硬性规则

1. **菜单即应用**：除首页看板外，一个应用一个页面，**禁止合并工作台**。
2. **列表不遗漏**：关键业务字段上列表 + 搜索条件与后端 list 参数一一对应。
3. **CRUD 全覆盖**：详情含全部业务字段；表单含全部可写业务字段（审计字段可省、快照字段只展示）。
4. **总体一致**：同模块各应用页的列表/模态/表单/校验风格统一（第 3 步④清单）。
5. **契约先行**：字段以后端真实契约与返回为准（dump services + 读 create/update 源码），不照别的视图猜。
6. **组件范式唯一**：架构、类名、交互模式一律照本正本与 `design-plus/view-convention/patterns.md` 的范式（经 e2e 参考实现实测），不发明新架构；用户明确要求的差异除外。
7. **数据隔离**：一切测试经 dbguard（`fde_platform/dbguard.py`）、串行跑——运维红线（隔离 / 串行 / 杀 dev server，勿绕）见 README §测试与验收红线。
8. **生成边界 + 前后端同文件夹**：应用前端只写 `app/<组>/<应用>/view.{js,html}`（与后端 `<应用>.py` 同文件夹，加应用前端 = 2 文件零接线）；组级聚合页放 `app/<组>/<页>.{js,html}`（松散文件）；通用壳 / 品牌 / 菜单 / 路由由平台约定推导，`view/lib/`、`view/pages/` 与后端 `.py` 零改动（样式确需扩充规范表 `fde_platform/static/fde.css` 属平台演进，须先向用户说明；`lib/styles.css` 是 `@import` 别名，勿扩写）。
9. **页面自描述约定**：每页 `export const PAGE_META = {key,name,ic,title,crumb,order}` + `export default function pageXxx()`（工厂默认导出、保留专名）。`order` 升序即菜单顺序，**必须显式给**。import 一律**绝对路径** `/view/lib/*`（相对路径在迁入应用目录后会断）；模板抓取用 `import.meta.url`。
10. **鉴权零实现 + svc 字面量**：不另造认证；页面不判断权限（菜单按页面授权渲染在 shell，数据闸门在后端，隐式放行在闸门）；401 → api.js 自动跳登录。**页面调服务必须用 `svc("app", "service")` 字面量**（可包在闭包里逐项写，勿用变量拼名）——这是隐式放行派生扫描的唯一来源；变量拼名只许服务台用。
11. **reactive 状态同步先行**：页面工厂体内一切会被模板引用的 reactive 状态，必须在**第一个 `await` 之前**同步建好（如 `self.list = pageable(...)` 含空 `items:[]`），再 `await` 拉数、最后 `await self.list.load()`。先 await 后建对象，`tpl` 一赋值即求值 null 子属性而整片报错（见 pitfalls #37）。

## 设计沿革

本规范的前身是「瘦壳 + 静态接线」方案：每个模块自带 `index.html`（手写 21 行页面
import）与 `app.js`（PAGES 清单），加一个应用要在两个框架文件里各接一处线。2026-07-31
重构为**平台通用壳 + 页面自描述 + 动态装配**：模块框架文件（`index.html`/`app.js`）
全部删除，壳由平台 `view_shell.html` 统一渲染，页面清单经 `/api/view_boot` 由扫描动态
生成，工厂经 `import()` 动态加载。生成边界由此收敛到「只写 `pages/` 对，零接线」，与
后端「组建目录即生效」的约定完全对称。

同日二次重构：**前端迁入应用目录，前后端同文件夹**。应用页从 `view/<组>/pages/<应用>.*`
搬到 `app/<组>/<应用>/view.{js,html}`（与 `<应用>.py` 并列），一个应用 = 一个文件夹即可
整份交付；组级聚合页（dashboard 等无后端应用的页）留在 `view/<组>/`。平台以写死文件名端点
`/app/<名>/view.{js,html}` serve 应用前端（同目录 `.py`/`.db` 绝不暴露）；页面 import 统一
改绝对路径 `/view/lib/*`。注册表扫描 `app/<组>/<应用>/view.js` 与 `view/<组>/*.js` 双源合并，
page_id（`<组>:<应用>`）与授权数据格式不变。`_contracts.md` 随之归到 `app/<组>/`。

2026-08-25 **组级页并入组目录**：组级聚合页（dashboard / 流程总览 / 物料 360 等无后端应用的页）
从 `view/<组>/<页>.{js,html}` 迁入 `app/<组>/<页>.{js,html}`（与组内应用子目录并列的松散文件），
`view/` 只保留平台级内容（`lib/`、`pages/`）。注册表扫描源由 `view/<组>/*.js` 改为
`app/<组>/*.js`，组级页改经 `/app/<组>/<页>.{js,html}` serve；后端发现只认子目录里的 `.py`，
松散文件天然不冲突。

2026-08-02 **约定正本迁至 `design-plus/VIEW_CONVENTION.md`**（与后端约定 `skill/app-convention.md`
→ `design-plus/CONVENTION.md` 的迁移同例）：参考资料随迁 `design-plus/view-convention/`（architecture /
patterns / design-system / pitfalls，pitfalls 条目编号保持不变）；`skill/view-generation.md` 与
`skill/view-generation/` 降级为兼容指针；`fde_platform/builder.py` 等平台代码改读本正本。
迁移动机：`design-plus/` 轻量工具链扩展前端四步（第⑥–⑨步，规格见 `design-plus/前端设计.md` /
`前端编码.md` / `前端测试.md` / `前端测试执行.md`），前端约定正本须与步骤规格、与后端
`CONVENTION.md` 同目录、单一来源。

同日**参考实现换防**：前端生成的参考实现由 `app/crm/`（某客户 CRM，20 应用）改为
`app/e2e/`（member/task + `view/e2e/dashboard.*`）。CRM 建于约定建立之前，其前端页面部分
违反现行 svc 字面量铁律（11 处非字面量调用），定位为**只读遗留样例、不作生成参考**；
verify 范式相应由 `app/crm/tests/verify_view_crm.py` 改以 `design-plus/前端验收样板/verify_view_e2e.py` 为准。范式
本体（patterns.md）不因此变化——它已成文化，且经 e2e 模块实测。
