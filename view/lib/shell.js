/* FDE 视图 · 公共基座 —— shell（路由 / 菜单 / 用户条 / 挂载）+ 共享分页工具。
 *
 * 模块无关：业务模块不修改本文件。平台通用壳（templates/view_shell.html）在
 * /view/<组>/ 根调用 bootShell(组名)——拉 /api/view_boot 页面清单（服务端扫描
 * app/<组>/<应用>/view.js 与组级页 view/<组>/*.js 得出）、动态 import() 各页工厂、
 * 注册 Alpine 组件后启动。模块内无任何框架文件（无 index.html / app.js）：
 * 加应用前端 = 在应用目录写 view.{js,html}（与后端 <应用>.py 同文件夹）。
 *
 * 三项平台行为（业务代码零感知）：
 *  1. 平台公共页自动追加：Agent 按页面授权可见；服务台（console）仅 admin 可见
 *     （其服务调用是动态的、不可派生授权，故不进授权体系）；
 *  2. 菜单按**页面授权**渲染：init 拉 /api/my_pages（角色页面授权集），业务菜单
 *     项按 `<module>:<key>` 过滤；admin 全通。直访无授权路由回落首个授权页。
 *     授权集到达前菜单为空（杜绝短暂暴露）；
 *  3. 页面上下文：路由切换时写 window.__fdePage（api.js 的 svc 据此注入 X-Fde-Page
 *     请求头，后端对获授页面隐式放行其派生服务）。
 */
import { get, dash, fmtTime, tryParse } from "./api.js";
import { pageAgent } from "../pages/agent.js";
import { pageConsole } from "../pages/console.js";
import { agentRail } from "../pages/agent_rail.js";

/* 平台公共页（可按页面授权）；console 单列——仅 admin 可见、不可授权 */
export const PLATFORM_PAGES = [
  { key: "agent", name: "Agent", ic: "✦", title: "平台 Agent", crumb: "对话式跨应用编排", platform: true },
];

const ADMIN_ONLY_PAGES = [
  { key: "console", name: "服务台", ic: "⌗", title: "通用服务台", crumb: "按服务契约自动建表 · 覆盖全部应用", platform: true },
];

const PLATFORM_COMPONENTS = { agent: pageAgent, console: pageConsole };

/* x-html 模板片段中的助手函数经 window 全局解析（Alpine 表达式回落 window） */
window.dash = dash;
window.fmtTime = fmtTime;
window.tryParse = tryParse;

export function createShell({ module, brand, pages, components }) {
  return {
    module,
    brand,
    route: "dashboard",
    me: null,
    toasts: [],
    isAdmin: false,
    granted: null,       // 页面授权集（Set）；null = 未到达（菜单为空，不暴露）
    bizPages: pages,     // 模块声明的业务页（含 dashboard 等模块专属页）
    bizComponents: components,
    agentOpen: (localStorage.getItem("fde.agent.rail") || "1") === "1",  // 右栏 Agent，默认展开、记住状态

    get menu() {
      if (this.granted === null) return [];
      const biz = this.bizPages.filter(
        (p) => this.isAdmin || this.granted.has(this.module + ":" + p.key));
      const plat = [
        ...PLATFORM_PAGES.filter(
          (p) => this.isAdmin || this.granted.has("_platform:" + p.key)),
        ...(this.isAdmin ? ADMIN_ONLY_PAGES : []),
      ];
      return [...biz, ...plat];
    },
    get page() {
      return this.menu.find((p) => p.key === this.route)
        || this.menu[0] || { title: "", crumb: "" };
    },

    init() {
      window.addEventListener("fde:toast", (e) => this.pushToast(e.detail));
      window.addEventListener("hashchange", () => this.syncRoute());
      /* 其他页面（如流程总览）请求展开 Agent 右栏 */
      window.addEventListener("fde:agent-open", () => {
        this.agentOpen = true;
        localStorage.setItem("fde.agent.rail", "1");
      });
      get("/api/me")
        .then((me) => { this.me = me; })
        .catch(() => { /* 401 已由 api 层跳转登录 */ });
      get("/api/my_pages")
        .then((d) => {
          this.isAdmin = !!d.is_admin;
          this.granted = new Set(d.pages || []);
          this.syncRoute();  // 菜单就绪后校正路由（无授权 hash → 首个授权页）
        })
        .catch(() => { this.granted = new Set(); });
      this.syncRoute();
    },

    syncRoute() {
      const key = (location.hash || "#/dashboard").replace(/^#\//, "") || "dashboard";
      const fallback = this.menu[0] ? this.menu[0].key : "dashboard";
      this.route = this.menu.some((p) => p.key === key) ? key : fallback;
      /* 页面上下文：业务页 → <module>:<key>；平台页 → _platform:<key>。
         api.js 的 svc() 据此注入 X-Fde-Page（页面授权隐式放行的依据）。 */
      const inBiz = this.bizPages.some((p) => p.key === this.route);
      window.__fdePage = (inBiz ? this.module : "_platform") + ":" + this.route;
      window.scrollTo({ top: 0 });
    },
    go(key) { location.hash = "#/" + key; },

    toggleAgent() {
      this.agentOpen = !this.agentOpen;
      localStorage.setItem("fde.agent.rail", this.agentOpen ? "1" : "0");
    },

    /* 单一挂载点：按 route 查组件注册表（业务注册表 + 平台页），实例化给 x-data */
    mount() {
      const factory = this.bizComponents[this.route] || PLATFORM_COMPONENTS[this.route];
      return factory ? factory() : {};
    },

    pushToast({ message, kind }) {
      const id = Date.now() + Math.random();
      this.toasts.push({ id, message, kind });
      setTimeout(() => { this.toasts = this.toasts.filter((t) => t.id !== id); }, 4200);
    },
  };
}

/* 通用壳启动引导（平台壳 view_shell.html 调用）：
   拉服务端启动清单 → 动态 import() 各页工厂 → 注册 Alpine 组件 → 启动。
   清单由平台扫描 app/<组>/<应用>/view.js 与 view/<组>/*.js 得出（含每页 url / PAGE_META 元数据 / order），
   故模块内无需任何框架文件；新页面落盘即进清单（mtime 缓存，下次刷新生效）。 */
export async function bootShell(module) {
  const fail = (msg) => {
    document.body.innerHTML =
      '<div style="max-width:560px;margin:80px auto;padding:28px 32px;font:14px/1.8 system-ui;'
      + 'color:#334155;background:#fff;border:1px solid #e2e8f0;border-radius:12px">'
      + '<div style="font-size:17px;font-weight:700;color:#b45309">视图启动失败</div>'
      + `<div style="margin-top:8px;color:#64748b">${msg}</div>`
      + '<div style="margin-top:16px"><a href="/view/" style="color:#175e54">← 返回视图清单</a>'
      + '&nbsp;&nbsp;<a href="/" style="color:#175e54">回平台首页</a></div></div>';
  };

  let man;
  try {
    man = await get(`/api/view_boot?module=${encodeURIComponent(module)}`);
  } catch (e) {
    /* 401 时 api 层已跳登录页；此处兜底其余失败（清单 404 / 解析错误等） */
    return fail(`无法加载模块「${module}」的页面清单：${(e && e.message) || e}`);
  }

  const pages = (man && man.pages) || [];
  /* 每页「默认隐藏列」（PAGE_META.col_default_hidden 逗号串）→ 供列控制无个人配置时套用 */
  window.__fdeColDefaults = {};
  pages.forEach((p) => {
    if (p.col_default_hidden) {
      window.__fdeColDefaults[p.id] = String(p.col_default_hidden)
        .split(",").map((s) => s.trim()).filter(Boolean);
    }
  });
  const components = {};
  try {
    const mods = await Promise.all(pages.map((p) => import(p.url)));
    pages.forEach((p, i) => {
      const factory = mods[i] && mods[i].default;   // 约定：页面工厂为默认导出
      if (factory) {
        Alpine.data(p.key, factory);
        components[p.key] = factory;
      }
    });
  } catch (e) {
    return fail(`页面模块动态加载失败：${(e && e.message) || e}`);
  }

  Alpine.data("shell", () => createShell({
    module,
    brand: (man && man.brand) || { name: module, sub: "", foot: "" },
    pages, components,
  }));
  Alpine.data("agentRail", agentRail);   // 右栏 Agent 组件（壳层常驻，全页面可见）
  Alpine.start();
  watchSortableTables();   // 平台级列表排序自动装饰（零应用改动，见文件尾部）
}

/* 列表分页 + 排序 + 展开行管理（各应用页共用）。
   排序走平台 list 拦截（fde_platform/listsort.py）：sort_by/sort_dir 为平台保留参数，
   后端按全量排序后返回请求页——应用 list 契约零变化，无需任何改造即获得列排序。 */
export function pageable(loader, size = 20) {
  return {
    items: [], total: 0, page: 1, size,
    loading: false, openKey: "",
    sortKey: "", sortDir: "",            // 排序态："" = 服务端默认序；asc / desc

    async load(page = 1, extra = {}) {
      this.loading = true;
      try {
        const sort = this.sortKey
          ? { sort_by: this.sortKey, sort_dir: this.sortDir || "asc" } : {};
        const data = await loader({ page, size, ...sort, ...extra });
        this.items = (data && data.items) || [];
        this.total = (data && data.total) ?? this.items.length;
        this.page = (data && data.page) ?? page;
      } finally {
        this.loading = false;
      }
    },
    get pages() { return Math.max(1, Math.ceil(this.total / this.size)); },

    /* 表头点击三态循环：升序 → 降序 → 恢复默认序（重置页码重新请求） */
    sortBy(key) {
      if (!key) return;
      if (this.sortKey !== key) { this.sortKey = key; this.sortDir = "asc"; }
      else if (this.sortDir === "asc") { this.sortDir = "desc"; }
      else { this.sortKey = ""; this.sortDir = ""; }
      return this.load(1);
    },
    sortIcon(key) {
      if (this.sortKey !== key) return "⇅";
      return this.sortDir === "asc" ? "▲" : "▼";
    },

    toggle(key) { this.openKey = this.openKey === key ? "" : key; },
    isOpen(key) { return this.openKey === key; },
  };
}

/* ── 平台级列表排序自动装饰（零应用改动）─────────────────────────────
   bootShell 启动后观察 main 区：凡 table.tbl 且能定位到 pageable 实例，
   即为可解析的表头列自动挂 data-sort + 点击排序 + .arr 指示器。
   列→字段解析用「行采样匹配」：单元格归一化文本与 items 字段值交叉比对，
   唯一命中的列才绑定；解析不出的列（操作列/复合渲染列）自动跳过不挂载。
   保护：模态内表格不装饰；装饰失败静默，绝不影响业务页。 */
const _sortedTables = new WeakSet();

function _isPageable(v) {
  return v && typeof v === "object" && Array.isArray(v.items)
    && typeof v.load === "function" && typeof v.sortBy === "function";
}

function _findPageable(table) {
  const holder = table.closest("[x-data]");
  if (!holder || !window.Alpine) return null;
  const A = window.Alpine;
  /* Alpine $data() 的合并代理不可枚举；改走元素作用域链 _x_dataStack（v3 稳定内部结构），
     经 Alpine.raw() 取底层对象枚举键名，值仍从代理读。由近及远，首个含 pageable 的作用域生效。 */
  const scopes = holder._x_dataStack || [];
  const keysOf = (o) => { try { return Object.keys((A.raw && A.raw(o)) || {}); } catch { return []; } };
  const rowCount = table.querySelectorAll("tr.data").length;
  const cands = [];
  for (const scope of scopes) {
    for (const k of keysOf(scope)) {
      let v;
      try { v = scope[k]; } catch { continue; }
      if (_isPageable(v)) cands.push(v);
    }
    if (cands.length) break;
  }
  if (!cands.length) return null;
  /* 多个 pageable 时按行数匹配消歧；空表且多候选 → 无法确定，放弃（下轮重试） */
  return cands.find((p) => p.items.length === rowCount)
    || (rowCount ? cands[0] : (cands.length === 1 ? cands[0] : null));
}

/* 单元格归一化：去千分位逗号；「—」/空 → null；colspan 单元格 → undefined（弃列） */
function _normCell(td) {
  if (!td || td.colSpan > 1) return undefined;
  const t = (td.innerText || "").trim();
  if (t === "" || t === "—") return null;
  return t.replace(/,/g, "");
}

/* 单元格文本 ↔ 字段值 宽松匹配（原值 / fmtTime 截断19位 / 数值） */
function _cellMatches(t, v) {
  if (t === null) return v === null || v === undefined || v === "";
  if (v === null || v === undefined || v === "") return false;
  const s = String(v);
  if (t === s) return true;
  if (t === s.slice(0, 19)) return true;
  if (typeof v === "number") return Number(t) === v;
  return false;
}

/* 返回 [{th, key}]；key 为空串 = 该列不可排序 */
function _resolveColumns(table, pl) {
  const hdr = Array.from(table.querySelectorAll("tr"))
    .find((tr) => tr.querySelector("th"));
  if (!hdr) return [];
  const ths = Array.from(hdr.children).filter((el) => el.tagName === "TH");
  const rows = Array.from(table.querySelectorAll("tr.data")).slice(0, 5);
  const items = (pl.items || [])
    .filter((it) => it && typeof it === "object").slice(0, 5);
  if (!rows.length || !items.length || rows.length > items.length) return [];
  const keys = Object.keys(items[0]);
  return ths.map((th, i) => {
    const cells = rows.map((r) => _normCell(r.children[i]));
    if (cells.some((c) => c === undefined)) return { th, key: "" };
    const hits = keys.filter(
      (k) => rows.every((_, ri) => _cellMatches(cells[ri], items[ri][k])));
    return { th, key: hits.length === 1 ? hits[0] : "" };
  });
}

/* 表头文本清洗（去排序箭头/释义徽标），作为列配置的稳定标识 */
function _thLabel(th) {
  return (th.textContent || "").replace(/[⇅▲▼?]/g, "").trim();
}

function _decorateTable(table) {
  if (_sortedTables.has(table) || table.closest(".modal-mask")) return;
  const pl = _findPageable(table);
  if (!pl) return;
  const cols = _resolveColumns(table, pl);
  if (!cols.some((c) => c.key)) return;   // 数据未就绪或无可解析列 → 下轮重试
  _sortedTables.add(table);
  const sync = () => cols.forEach(({ th, key }) => {
    const arr = th.querySelector(".arr");
    if (arr) arr.textContent = key ? pl.sortIcon(key) : "";
    th.classList.toggle("sorted", !!key && pl.sortKey === key);
  });
  cols.forEach(({ th, key }) => {
    if (!key) return;
    th.setAttribute("data-sort", key);
    const arr = document.createElement("span");
    arr.className = "arr";
    arr.textContent = "⇅";
    th.appendChild(arr);
    th.addEventListener("click", (e) => {
      /* 跳过表头内自带点击行为的子元素（按钮/输入/「?」释义徽标等），避免误触排序 */
      let el = e.target;
      while (el && el !== th) {
        if (el.nodeType === 1 && (el.matches("button,input,select,a")
          || el.hasAttribute("@click") || el.hasAttribute("x-on:click"))) return;
        el = el.parentElement;
      }
      try { Promise.resolve(pl.sortBy(key)).catch(() => {}); } catch { /* 静默 */ }
      sync();
    });
  });
  sync();
  _attachColumnControl(table, cols);
}

/* ── 自定义显示列（per-user 服务端持久化，跟账号走）────────────────
   复用排序的列解析：可解析列进勾选弹层；隐藏用 nth-child CSS（扛 x-for 重渲染）；
   配置存 /api/prefs/cols:<页>（value=隐藏字段 key 数组），任意设备登录恢复。 */
let _colctlSeq = 0;
const _prefCache = {};

const _colPrefKey = () => "cols:" + (window.__fdePage || "page");

/* 返回该账号已存的隐藏列数组；服务端无配置时返回 null（区别于显式存 []） */
async function _loadHidden(key) {
  if (key in _prefCache) return _prefCache[key];
  let val = null;
  try {
    const r = await fetch("/api/prefs/" + encodeURIComponent(key), { credentials: "same-origin" });
    const j = await r.json();
    val = (j && Array.isArray(j.data)) ? j.data : null;
  } catch { val = null; }
  _prefCache[key] = val;
  return val;
}
/* 默认隐藏列按页 id（__fdePage）登记，与 pref 键（cols:前缀）不同，此处用页 id 查 */
const _colDefault = () => (window.__fdeColDefaults && window.__fdeColDefaults[window.__fdePage || ""]) || [];
function _saveHidden(key, hidden) {
  _prefCache[key] = hidden;
  fetch("/api/prefs/" + encodeURIComponent(key), {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value: hidden }),
  }).catch(() => {});
}

/* hidden 为隐藏的表头文本数组；按列序号 nth-child 隐藏（与字段解析无关，全列可配） */
function _applyHidden(table, colsAll, hidden) {
  if (!table.id) table.id = "fde-tbl-" + (++_colctlSeq);
  let style = document.getElementById("colstyle-" + table.id);
  if (!style) {
    style = document.createElement("style");
    style.id = "colstyle-" + table.id;
    document.head.appendChild(style);
  }
  const rules = [];
  colsAll.forEach(({ i, label }) => {
    if (hidden.includes(label)) {
      const n = i + 1;
      rules.push(`#${table.id} th:nth-child(${n}), #${table.id} tr.data td:nth-child(${n}) { display: none; }`);
    }
  });
  style.textContent = rules.join("\n");
}

/* 列设置图标（三列表格 glyph），替代「列」汉字按钮 */
const _COLCTL_ICON =
  '<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">'
  + '<rect x="1.2" y="2.2" width="13.6" height="11.6" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.3"/>'
  + '<line x1="5.8" y1="2.2" x2="5.8" y2="13.8" stroke="currentColor" stroke-width="1.1"/>'
  + '<line x1="10.4" y1="2.2" x2="10.4" y2="13.8" stroke="currentColor" stroke-width="1.1"/></svg>';

function _attachColumnControl(table, cols) {
  /* 全列可配：以表头文本为稳定标识、按列序号隐藏（与字段解析无关）；仅排除操作列 */
  const colsAll = cols.map((c, i) => ({ ...c, i, label: _thLabel(c.th) }))
    .filter((c) => c.label && !c.th.classList.contains("right") && c.label !== "操作");
  if (!colsAll.length) return;
  const key = _colPrefKey();
  const card = table.closest(".card") || table.closest(".bd");
  if (card && card.querySelector(".colctl")) return;
  const ctl = document.createElement("span");
  ctl.className = "colctl";
  const btn = document.createElement("button");
  btn.type = "button"; btn.className = "colctl-btn";
  btn.title = "自定义显示列"; btn.setAttribute("aria-label", "自定义显示列");
  btn.innerHTML = _COLCTL_ICON;
  const pop = document.createElement("div");
  pop.className = "colctl-pop";
  ctl.appendChild(btn); ctl.appendChild(pop);
  /* 优先并入卡片工具栏右侧（与查询/新建同行，最自然）；无工具栏才回落到表格上方 */
  const toolbar = card && card.querySelector(".tagline .right, .right.tagline, .tagline.right");
  if (toolbar) toolbar.appendChild(ctl);
  else {
    const anchor = table.closest(".scroll-x") || table;
    if (!anchor.parentElement) return;
    anchor.parentElement.insertBefore(ctl, anchor);
  }

  const render = async () => {
    const stored = await _loadHidden(key);
    const hidden = stored || _colDefault(key);   // 无个人配置时套用页面默认隐藏列
    pop.innerHTML = "";
    colsAll.forEach((c) => {
      const item = document.createElement("label");
      item.className = "colctl-item";
      item.dataset.col = c.label;
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !hidden.includes(c.label);
      item.appendChild(cb);
      item.appendChild(document.createTextNode(c.label));
      pop.appendChild(item);
    });
    _applyHidden(table, colsAll, hidden);   // 挂载即恢复（个人配置优先，否则默认）
  };

  /* 事件委托：监听挂在 pop 容器一次，复选框重建不丢监听 */
  pop.addEventListener("change", async (e) => {
    const cb = e.target;
    if (!cb || cb.tagName !== "INPUT") return;
    const item = cb.closest(".colctl-item");
    const label = item && item.dataset.col;
    if (!label) return;
    const base = (await _loadHidden(key)) || _colDefault(key);
    const set = new Set(base);
    if (cb.checked) set.delete(label); else set.add(label);
    const arr = [...set];
    _applyHidden(table, colsAll, arr);
    _saveHidden(key, arr);   // 一旦手动调整即显式持久化，覆盖默认
  });

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (pop.classList.toggle("open")) render();
  });
  document.addEventListener("click", (e) => {
    if (!ctl.contains(e.target)) pop.classList.remove("open");
  });
  render();
}

export function watchSortableTables() {
  let scheduled = false;
  const sweep = () => {
    scheduled = false;
    try {
      document.querySelectorAll("main table.tbl").forEach(_decorateTable);
    } catch { /* 平台增强绝不破坏业务页 */ }
  };
  const schedule = () => {
    if (!scheduled) { scheduled = true; setTimeout(sweep, 60); }
  };
  new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
  schedule();
}
