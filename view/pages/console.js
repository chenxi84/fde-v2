/* 通用服务台：按服务契约自动建表，覆盖全部应用 */
import { get, svc, hue } from "../lib/api.js";


export function pageConsole() {
  const self = Alpine.reactive({
    tpl: "",
    hue,
    apps: [],
    group: "",          // 组过滤（"" = 全部）
    app: "",
    services: [],
    forms: {},          // 服务名 → {参数名: 值}
    results: {},        // 服务名 → 结果对象
    busy: "",

    async init() {
      self.tpl = await fetch(new URL("console.html", import.meta.url)).then((r) => r.text());
      self.apps = (await get("/api/apps").catch(() => [])) || [];
    },

    get groups() {
      const gs = new Set(self.apps.map((a) => a.group).filter(Boolean));
      return [...gs].sort();
    },
    get appsShown() {
      return self.apps.filter((a) => !self.group || a.group === self.group);
    },

    async pickApp(name) {
      self.app = name;
      self.services = (await get(`/api/apps/${name}/services`).catch(() => [])) || [];
      self.forms = {};
      self.results = {};
    },

    formFor(s) {
      if (!self.forms[s.name]) {
        const f = {};
        s.parameters.forEach((p) => {
          f[p.name] = p.default === null || p.default === undefined ? "" : p.default;
        });
        self.forms[s.name] = f;
      }
      return self.forms[s.name];
    },

    async run(s) {
      const params = {};
      const f = self.forms[s.name] || {};
      for (const p of s.parameters) {
        const v = f[p.name];
        if (v !== "" && v !== null && v !== undefined) params[p.name] = v;
      }
      self.busy = s.name;
      try {
        self.results[s.name] = await svc(self.app, s.name, params);
      } catch (e) {
        self.results[s.name] = { error: String(e.message || e) };
      } finally {
        self.busy = "";
      }
    },

    pretty(v) {
      try { return JSON.stringify(v, null, 2); } catch { return String(v); }
    },
  });
  return self;
}
