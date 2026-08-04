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
  Alpine.start();
}

/* 列表分页 + 展开行管理（各应用页共用） */
export function pageable(loader, size = 20) {
  return {
    items: [], total: 0, page: 1, size,
    loading: false, openKey: "",

    async load(page = 1, extra = {}) {
      this.loading = true;
      try {
        const data = await loader({ page, size, ...extra });
        this.items = (data && data.items) || [];
        this.total = (data && data.total) ?? this.items.length;
        this.page = (data && data.page) ?? page;
      } finally {
        this.loading = false;
      }
    },
    get pages() { return Math.max(1, Math.ceil(this.total / this.size)); },
    toggle(key) { this.openKey = this.openKey === key ? "" : key; },
    isOpen(key) { return this.openKey === key; },
  };
}
