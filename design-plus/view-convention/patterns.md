# 代码范式（Patterns）

所有范式是成文化的前端视图范式，经参考实现实测。**参考实现 = `app/e2e/<应用>/view.*`（member / task）+ `view/e2e/dashboard.*`（组级看板）+ `view/e2e/process.*`（组级流程总览，见 §8）**，新模块照抄结构、换业务字段。

> **页面组织**：菜单 = dashboard（组级页 `view/<组>/dashboard.*`）+ 每个应用一页（`app/<组>/<应用>/view.{js,html}`，与后端同文件夹）；Agent / 服务台由 shell 自动追加，**不在模块内声明**。公共基座（`view/lib/`）只 import、不复制、不修改。

## 0. 列表字段 / 搜索条件 / CRUD 完整性规范

**列表关键字段（防遗漏）**
- 列集合从该应用 `list` 返回项字段中选取，覆盖：单号、状态、归属（客户/上级单号）、关键数量/金额、关键时间、关联单号；返回字段多时宁多勿少，宽表 `.scroll-x` + `.tbl.tight`。
- **列表列 ⊆ 详情字段集**（列表显示的每个字段详情里必须有）。
- 自检方法：dump 一条真实 list item，逐字段过一遍——是业务字段就该考虑上列表或至少上详情。

**搜索条件（与后端对齐）**
- 读后端 `list(self, <过滤参数>..., page, size)` 签名，**每个过滤参数对应一个控件**：
  - 状态类 → `fchip` 组（含「全部」空值项）；
  - 归属类（customer_no 等）→ 下拉（选项来自对应主数据 `list`）；
  - 关键字类 → 输入框（`@keydown.enter` 触发）+ 搜索按钮；
  - 日期类 → date 输入或起止区间。
- 后端 list 不支持的维度**不自造前端假过滤**——需要就先给后端 list 服务加参数（这属于平台改动，要向用户说明）。

**CRUD 字段完整性**
- 字段三分类：
  - **可写业务字段**：create / update / set_* / import_batch 接受的参数 → **必须进表单**（create 接受的进创建表单；仅 update 接受的进编辑入口）；
  - **快照/推导字段**：任何写服务都不接受（如 SO 抬头的客户等级/联系人，来自 customer.get 快照）→ **只在详情展示**，表单不放（可在详情标注"快照自客户"）；
  - **审计字段**：created_at / created_by / updated_* / version 等 → 表单不放，详情**可省**（原始数据 JSON 里仍可查）。
- 枚举字段的 select 选项必须与后端校验值**完全一致**（读源码里的允许值列表，如 trading_entity 的 股份/重庆/普恩/上海贸易）。
- 有写后服务（update/set_*/import_batch）的应用**必须**给编辑入口，否则只有"增删查"没有"改"，不算完整 CRUD。

**一致性清单（同模块每页逐项对照）**
- [ ] 列表三段式：过滤区（tagline: 标题 + chips + 搜索）/ 表格（单号 b-link、状态 st 徽章、操作 rowact）/ 分页条（上一页·页码·下一页 + 总数）
- [ ] 模态三段式：墨青头带（docno + 状态徽章 + ✕）/ KV 分组体（.kv + .sec，子账本 .tbl.tight，折叠原始 JSON）/ 状态操作页脚（.modal-ft）
- [ ] 表单：必填红星先行、按语义 frow 分组、可选项「更多字段 ▾」折叠、底部右对齐提交按钮、`:disabled` 编辑态锁键
- [ ] 展示工具统一：`hue()`/`dash()`/`fmt()`/`fmtTime()`/`tryParse()`，无自造格式化
- [ ] 字段顺序统一：单号 → 状态 → 归属 → 数量/金额 → 时间（列表/详情/表单同一顺序）

## 1. 页面工厂（每页骨架 = PAGE_META 自描述 + 默认导出工厂）

```js
/* app/<组>/<应用>/view.js（与后端 <应用>.py 同文件夹） */
import { svc, hue, fmt, toast } from "/view/lib/api.js";     // ← 绝对路径，勿用相对（迁入应用目录后相对会断）
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：应用页 key = 文件夹名（与后端应用名对齐）；
   order 升序 = 菜单顺序（建议 10 步长） */
export const PAGE_META = {
  key: "xxx", name: "中文名", ic: "◈",
  title: "页面标题", crumb: "副题 · 要点",
  order: 30,
};

export default function pageXxx() {          // ← 默认导出（壳读 mod.default）；函数保留专名
  const self = Alpine.reactive({      // ← 必须 Alpine.reactive，裸对象赋值不触发重渲染
    tpl: "",
    hue, fmt,
    list: null,                        // pageable 实例
    filter: "", keyword: "",
    modalX: { open: false, loading: false, d: null },

    async init() {
      // 模板抓取用 import.meta.url（相对自身 URL）——应用页模板固定名 view.html
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("some_app", "list",
        { status: self.filter, keyword: self.keyword, ...q }));         // 闭包引用 self（代理）
      await self.list.load();
    },

    search() { self.list.load(1); },

    async viewX(doc) {                 // 点单号 → 开模态
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("some_app", "get", { xxx_no: doc.xxx_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeX() { self.modalX.open = false; },
  });
  return self;
}
```

要点：
- **`PAGE_META` 是平台的唯一扫描入口**：`name`/`ic` 供菜单，`title`/`crumb` 供主区头，`order` 决定菜单顺序（升序，建议 10/20/30… 步长预留插入空隙）。漏写 `PAGE_META` 只影响美观（回落文件名/默认图标），不坏授权与启动——但**必须写**。
- **工厂必须默认导出**（`export default function pageXxx`）：壳经 `import()` 动态加载后读 `mod.default` 注册。函数名保留 `pageXxx` 专名，栈轨迹与 grep 才友好。
- 状态写在 `self` 上、方法里一律 `self.xxx =`（代理写入才响应式）；**不要**在方法里用 `this`（工厂不是组件方法，this 无绑定）。
- `pageable()` 的 loader 是闭包，读取 `self.filter` 等当前值——filter 变化后 `load(1)` 即带新参数。
- **列排序零改动**：平台 `watchSortableTables()`（shell.js）在页面挂载后自动为「main 区 `table.tbl` 且能定位到 pageable 实例」的表头挂 `data-sort` + ▲▼ 指示 + 点击排序；点击经 `sortBy()` 携带平台保留参数 `sort_by/sort_dir` 重新请求后端，平台排序后只回一页。列→字段用行采样匹配解析，操作列/复合渲染列自动跳过；模态内表格不装饰。**页面无需写任何排序代码**；需自定义时才手工覆盖。
- **自定义显示列（跟账号）**：同一装饰器在卡片工具栏右侧注入「列设置」图标（无工具栏时回落表格上方），弹层对**全部已渲染列**（以表头文本为标识、仅排除操作列）勾选显隐；隐藏用 `nth-child` CSS（扛 `x-for` 重渲染，空态行不受影响）。配置经 `/api/prefs/cols:<模块:页>`（`users.user_prefs` 表）per-user 持久化——同一账号任意设备登录恢复，不同账号互不影响。**注意**：列配置只能管理页面已渲染的列；若要表结构全字段可配，应用 `list()` 需返回全字段并把字段渲染成列（`md_material` 为范例）。**默认只显示关键列**：在 `PAGE_META` 声明 `col_default_hidden: "列名,列名,…"`，用户无个人配置时平台按它默认隐藏；用户手动调整后以个人配置（per-user）覆盖。
- `init()` 由 Alpine 在挂载时自动调用（单一挂载点每次路由切换重建实例 → 每进一次页面重新拉数）。

## 2. 列表 + 过滤 + 分页（模板片段）

```html
<div class="card mt12"><div class="bd" style="padding:0">
  <div class="tagline" style="padding:12px 16px; flex-wrap:wrap">
    <b>标题</b>
    <div class="right tagline" style="gap:8px">
      <div class="chips">
        <template x-for="s in ['', '状态A', '状态B']" :key="s || '全部'">
          <span class="fchip" :class="{on: filter === s}"
            @click="filter = s; list.load(1)" x-text="s || '全部'"></span>
        </template>
      </div>
      <input x-model="keyword" @keydown.enter="search()" placeholder="搜索…" style="width:200px">
      <button class="b-ghost b-sm" @click="search()">搜索</button>
    </div>
  </div>
  <div class="scroll-x">
    <table class="tbl tight">
      <tr><th>单号</th><th>…</th><th>状态</th><th class="right">操作</th></tr>
      <template x-if="!list.items.length"><tr><td colspan="4" class="empty">无匹配数据</td></tr></template>
      <template x-for="d in list.items" :key="d.xxx_no">
        <tr class="data">
          <td><button class="b-link mono" @click="viewX(d)" x-text="d.xxx_no"></button></td>
          <td x-text="dash(d.field)"></td>
          <td><span class="st" :class="'st-' + hue(d.status)" x-text="d.status"></span></td>
          <td class="right rowact">
            <button class="b-pri b-sm" x-show="d.status === '草稿'" @click="act(d, 'submit')">提交</button>
          </td>
        </tr>
      </template>
    </table>
  </div>
  <div class="tagline" style="padding:10px 16px">
    <span class="muted" x-text="'共 ' + list.total + ' 条'"></span>
    <div class="right tagline" style="gap:8px">
      <button class="b-ghost b-sm" :disabled="list.page <= 1" @click="list.load(list.page - 1)">‹ 上一页</button>
      <span class="muted mono" x-text="list.page + ' / ' + list.pages"></span>
      <button class="b-ghost b-sm" :disabled="list.page >= list.pages" @click="list.load(list.page + 1)">下一页 ›</button>
    </div>
  </div>
</div></div>
```

## 3. 详情模态

```html
<div class="modal-mask" x-show="modalX.open" @click.self="closeX()"
     @keydown.escape.window="closeX()" x-cloak>
  <div class="modal">
    <div class="modal-hd">
      <div><div class="docno" x-text="modalX.d ? modalX.d.xxx_no : '单据名'"></div>
        <div class="sub">中文说明 · ENGLISH</div></div>
      <template x-if="modalX.d">
        <span class="st" :class="'st-' + hue(modalX.d.status)" x-text="modalX.d.status"></span>
      </template>
      <button class="x" @click="closeX()">✕</button>
    </div>
    <div class="modal-bd">
      <template x-if="modalX.loading">
        <div class="loadbox"><span class="spin">◌</span><br>载入明细…</div>
      </template>
      <template x-if="!modalX.loading && modalX.d">
        <div>
          <div class="kv">
            <div><div class="k">字段名</div><div class="v mono" x-text="dash(modalX.d.f1)"></div></div>
            <!-- 全部字段按语义分组；长标签字段用 style="grid-column: span 2" -->
          </div>
          <div class="sec">子账本标题（N）</div>
          <div class="scroll-x">
            <table class="tbl tight"> …行项目/流水… </table>
          </div>
          <details class="raw"><summary>原始数据</summary>
            <pre class="json" x-text="JSON.stringify(modalX.d, null, 2)"></pre></details>
        </div>
      </template>
    </div>
    <div class="modal-ft" x-show="modalX.d">
      <template x-if="modalX.d">
        <div class="tagline" style="gap:8px">
          <button class="b-pri" x-show="modalX.d.status === '草稿'" @click="act(modalX.d, 'submit')">提交</button>
        </div>
      </template>
    </div>
  </div>
</div>
```

规则：
- `get()` 返回的**所有字段**都要出现（按语义分 `.kv` 组 + `.sec` 小节）——详情即"查"的完整面。
- `*_json` 快照字段（`snapshot_json`/`sap_result_json`/`price_snapshot_json` 等）用 `tryParse()` 解析后结构化展示（KV 或表格），不要直接倒 JSON。
- 页脚操作按状态 `x-show`；危险操作用 `b-dng` + `confirm()`。
- 一个模态里可能出现**多个 `.modal-bd`**（主详情 + 内嵌编辑区）——测试断言用 `.first`。

## 4. 表单（创建 / 编辑复用）

字段 = 后端 create/update **实际接受的参数**（先读源码/dump 契约！）。可选字段折叠：

```html
<div class="collapse" :class="{open: form.show}">
  <div class="card mt12 mb0">
    <div class="hd">
      <h3 x-text="form.mode === 'edit' ? ('编辑 · ' + form.editNo) : '新建 XX'"></h3>
      <button class="b-ghost b-sm right" x-show="form.mode === 'edit'"
        @click="form.show = false; resetForm()">取消编辑</button>
    </div>
    <div class="bd">
      <div class="frow">
        <div><label class="f">必填字段 <span class="req">*</span></label>
          <input x-model="form.f1" :disabled="form.mode === 'edit'"></div>
        <div><label class="f">枚举字段</label>
          <select x-model="form.f2"><option>选项A</option><option>选项B</option></select></div>
        <!-- 次要字段收进「更多字段 ▾」：每行一个 l.more 折叠区 -->
      </div>
      <div class="mt12 tagline">
        <button class="b-pri right" :disabled="form.busy" @click="save()"
          x-text="form.busy ? '处理中…' : (form.mode === 'edit' ? '保存修改' : '创建')"></button>
      </div>
    </div>
  </div>
</div>
```

```js
async save() {
  const f = self.form;
  if (!f.f1) return toast("必填字段缺失", "warn");
  f.busy = true;
  try {
    if (f.mode === "edit") {
      await svc("app", "update", { xxx_no: f.editNo, /* 允许修改的字段 */ });
    } else {
      await svc("app", "create", { /* 与后端参数一一对应 */ });
    }
    f.show = false; self.resetForm();
    await self.list.load(self.list.page);
  } catch { /* api.js 已 toast */ } finally { f.busy = false; }
}
```

编辑入口两种形态（视后端能力选）：
- 模态内小编辑区（`.modal-bd` 追加一段，`x-show` 限定可编辑状态）——适合 update 只允许少数字段（如 SO 抬头 4 字段）。
- 复用创建表单（`mode='edit'` 预填全部字段、键字段 disabled）——适合 set_lines 这类整体替换。

## 5. 主数据页（同步 + 手工增改）

- 头部：`sync_status` 徽章（同步时间/条数/警告）+「立即同步」按钮（调 `sync` 服务，toast 同步条数/警告数）。
- 手工新建·编辑：表单 → `import_batch({rows:[row]})` upsert；结果 `r.failed` 时 toast `r.errors[].reason`；编辑态键字段（customer_no/ctct_code）`:disabled="form.editing"`。
- 行上「编辑」按钮预填表单并滚到顶部。

## 6. 展示工具（lib/api.js 已提供，勿重复实现）

| 工具 | 用途 |
|---|---|
| `dash(v)` | 空值 → 「—」（window 全局，模板里可直接用） |
| `fmt(n)` | 数字千分位（空 → 「—」） |
| `fmtTime(v)` | 时间截到秒（window 全局） |
| `tryParse(v)` | `*_json` 字段解析（对象原样、失败 null，window 全局） |
| `hue(status)` | 状态 → 徽章色类后缀（`st-green/amber/red/blue/teal/slate`） |
| `liveStatus` | 活跃状态集（审批中/执行中/待重试/申请中/待回调）——进行态判定/pulse 徽章的公共常量（当前无业务页消费，新增页面可用） |
| `toast(msg, kind)` | 全局提示（shell 已挂监听） |
| `svc/get/post/del` | API 封装；`svc(app, svc, params, {quiet:true})` 静默探测 |

> `dash`/`fmtTime`/`tryParse` 由 `lib/shell.js` 导入时挂到 window（x-html 模板表达式回落 window 解析）；`hue`/`fmt` 习惯上再放进页面 `self`（列表/模态模板里用）。
> 新状态色：在 `lib/api.js` 的 `HUES` 映射里补 `状态: '颜色'`（全局唯一一份，属公共层演进，向用户说明）。

## 7. 模块装配（零接线 + 前后端同文件夹：壳与菜单由平台约定推导）

**新增一个应用的前端 = 在该应用的后端目录 `app/<组>/<应用>/` 下只写 2 个文件**（与
`<应用>.py` 并列），**没有任何接线**：

- `view.js` —— `PAGE_META` 自描述 + 默认导出工厂（§1），绝对路径 `import "/view/lib/*"`。
- `view.html` —— 模板片段（§2-§6），经 `new URL("view.html", import.meta.url)` 抓取。

**组级聚合页**（无对应后端应用，如 dashboard）放 `view/<组>/<页>.{js,html}`（key = 文件名）。

文件落盘即被平台扫描装配：启动清单（菜单/路由）、角色授权清单、首页线路图、
`svc()` 隐式放行派生边，全部自动纳入。**不写、也不修改任何框架文件**——模块内本就不存在
`index.html` / `app.js`，应用目录里也只多 `view.js`/`view.html` 两个文件。

**新建模块 = 建 `app/<组>/` 组**（前端无独立模块目录、无脚手架）：某组只要有应用带
`view.js` 就自动成为视图模块。通用壳、品牌、菜单、路由由平台统一提供，品牌按约定推导：

```
name = FDE·<组名大写>        （如 e2e → FDE·E2E，rail 品牌位，x-html 渲染）
sub  = FORWARD DEPLOYED
foot = <组名> 组 · N 页面     （N = 扫描到的页面数）
```

**装配链路（平台负责，业务零感知）**：

```
浏览器 GET /view/<组>/
  → web.py 识别「有视图页面的组」（app/<组>/ 应用含 view.js 或 view/<组>/ 有组级页），
    渲染平台通用壳 templates/view_shell.html
  → 壳内 bootShell(组名)（lib/shell.js）
      → GET /api/view_boot?module=<组>   （view_registry 扫描 app/<组>/<应用>/view.js
                                           与 view/<组>/*.js 合并，按 PAGE_META.order
                                           升序 + 约定推导品牌）
      → Promise.all(pages.map(p => import(p.url)))   动态加载各页工厂
           应用页 p.url = /app/<应用>/view.js · 组级页 p.url = /view/<组>/<页>.js
      → 逐页 Alpine.data(key, mod.default) 注册
      → Alpine.data("shell", createShell({module, brand, pages, components}))
      → Alpine.start()
```

要点：
- **通用壳是平台模板**（`view_shell.html`），不是模块文件——业务生成永不复制/修改它；其侧栏/主区/toast 骨架（`x-for menu` / 单一挂载点 / toasts）对所有组一致。
- **应用页经写死端点 serve**：`/app/<名>/view.js`（`text/javascript`）与 `/app/<名>/view.html`，只认这两个文件名——同目录的 `<应用>.py`/`.db`/`resource/` **永不被 expose**（安全红线）。组级页与 `view/lib/`、`view/pages/` 经 `/view/…` 静态放行。
- **`import()` 的 `p.url` 是绝对路径**，页面内模板抓取用 `import.meta.url`（§1）——文件搬到应用目录后无需改任何引用。
- **菜单顺序 = `PAGE_META.order` 升序**（同序回落 key）——这是唯一需要精心编排的字段，务必显式给且以 10 为步长。
- **新页面生效时机**：`view_registry` 以被扫描文件 mtime 为缓存令牌，落盘后浏览器刷新即见；管理页「重新扫描」可立即刷新。
- **启动失败不白屏**：清单 404 / import 报错时 `bootShell` 渲染错误面板（含返回链接）；401 由 api 层先行跳登录。

## 8. 数据驱动 SVG 流程图（组级「流程总览」页）

**参考实现：`view/e2e/process.{js,html}`（组级流程总览样例，最小自足）**。用于把一条跨应用的业务链路画成**可点击、带状态**的流程图。

**页面骨架同 §7 组级聚合页**：`view/<组>/process.js`，`PAGE_META.key = "process"`、`order` 紧跟 dashboard（15）。

关键范式（均为实测踩坑）：

1. **不要在 `<svg>` 内用 Alpine `x-for`**。`<template>` 不是 SVG 元素，`x-for` 展开走 innerHTML、SVG 子元素进不了
   SVG 命名空间 → `:x/:y/:width/:height` 绑定不生效、节点坐标全空。✅ 正解：**在 JS 里把整张 SVG 拼成字符串，
   `x-html` 注入**；点击用**事件委托**——容器 `@click="onSvgClick($event)"`，子元素带 `data-page="<key>"`，
   `e.target.closest("[data-page]")` 定位跳转目标，不逐节点绑 `@click`。

2. **坐标在 JS 里算**：`computeLayout()` 产出 `stages/nodes/edges` 的 x/y/w/h（分支汇聚用「三行拓扑」：
   1 列 → 2 列 → 1 列，阶段头用居中胶囊）。注意 **胶囊（220px）宽于窄分支节点（单步骤 150px）时按胶囊右对齐**
   （`cx = w - PAD - PILL_W/2`），否则胶囊溢出图边界（库存策略单步骤踩过）。

3. **连线用正交直角转角**（`elbow`：竖→横→竖 + 向下三角箭头），不用斜线；同阶段相邻步骤之间用**横向小箭头**
   （`hArrow`）体现前后顺序。

4. **状态由前端 quiet 聚合多个应用服务推导**（`svc(app, svc, params, {quiet:true})` + `.catch` 零值兜底），
   不新增后端聚合端点。每节点 `{name, done, summary}`：`done` 驱动绿/灰底色，`summary` 直接展示——
   **计数型摘要**（如「已填 3/5」）比布尔（「已填报」）更有用。

5. **节点点击跳转对应页并带版本号**：`localStorage.setItem("fde.process.fv", fv)` → `location.hash = "#/"+key`；
   各列表页读该键回填默认版本。

6. **联动右栏 Agent**：按钮先 `dispatchEvent(new CustomEvent("fde:agent-open"))`（壳展开右栏），
   再 `setTimeout(() => dispatchEvent(new CustomEvent("fde:agent-prompt", {detail:{message}})), 250)`（右栏
   `agent_rail` 监听后自动填充并 `send()`）。

7. **暗色主题**：底色深墨 `#0f1b2a`、节点暗卡 `#182432`、完成深绿 `#12271c` + 亮绿点/字，连线暗灰，
   与右栏 Agent 视觉统一。
