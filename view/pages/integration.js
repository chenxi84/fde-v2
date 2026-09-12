/* 集成接口：外部系统 API 端点管理。组级平台页——只显示/配置当前应用组的端点。
   数据 /api/integration/endpoints?group= + /api/integration/discover?group=。 */
import { get, post, del, toast } from "../lib/api.js";

export const PAGE_META = {
  key: "integration",
  name: "集成",
  ic: "🔗",
  title: "集成接口",
  crumb: "外部系统接口 · 当前组",
  order: 70,
};

function _blankForm() {
  return {
    app_name: "", method_name: "", kind: "external", target: "", url: "",
    http_method: "POST", content_type: "application/json", auth_type: "none",
    auth_param_name: "", auth_credential: "", extra_headers: "",
    timeout_s: 30, retries: 1, mock_enabled: false, mock_data: "",
  };
}

export function pageIntegration() {
  const self = Alpine.reactive({
    tpl: "",
    group: window.__fdeModule || "",
    endpoints: [],
    discovered: { external: [], cross_group: [] },
    modal: { open: false },
    form: _blankForm(),
    picked: "",                 // 「手动配置」下拉选中的 应用|方法

    async init() {
      self.tpl = await fetch(new URL("integration.html", import.meta.url)).then((r) => r.text());
      await self.load();
    },

    async load() {
      const qs = "?group=" + encodeURIComponent(self.group);
      const d = await get("/api/integration/endpoints" + qs, { quiet: true }).catch(() => []);
      self.endpoints = d || [];
    },

    async scan() {
      const qs = "?group=" + encodeURIComponent(self.group);
      const d = await get("/api/integration/discover" + qs, { quiet: true }).catch(() => ({ external: [], cross_group: [] }));
      self.discovered = d || { external: [], cross_group: [] };
    },

    appShort(app) { return String(app || "").split("/").pop(); },
    kindLabel(k) { return k === "cross_group" ? "跨组" : "外部"; },
    kindClass(k) { return k === "cross_group" ? "t-amber" : "t-teal"; },

    // 「＋ 手动配置」不该让人手打 app_name/method_name —— 那能建出指向不存在适配器的
    // 空配置。改成从「已发现的适配器」里挑，保证配置一定落在真实存在的适配器上。
    async openNew(ep) {
      if (ep) {
        self.modal.open = true;
        self.picked = "";
        self.form = {
          ..._blankForm(),
          app_name: ep.app_name, method_name: ep.method_name,
          kind: ep.kind || "external", target: ep.target || "",
        };
        return;
      }
      if (!self.discovered.external.length && !self.discovered.cross_group.length) {
        await self.scan();                       // 没扫过就先扫，否则下拉是空的
      }
      self.modal.open = true;
      self.picked = "";
      self.form = _blankForm();
    },

    // 列出**全部**已发现的适配器（含已配置的）——只列未配置的话，全配好之后
    // 这个下拉就是空的，「手动配置」反而不可用；已配置的选中即等于编辑。
    pickable() {
      return [...(self.discovered.external || []), ...(self.discovered.cross_group || [])];
    },

    pickDiscover() {
      const [a, m] = String(self.picked || "").split("|");
      if (!a) return;
      // 已配置过 → 按真实配置载入。不能拿 discover 推出来的 target 顶替：
      // discover 的 target 是从方法名前缀猜的（_http_fetch_materials → HTTP），
      // 与用户实际保存的目标系统（如 MOCK-ERP）不是一回事，照猜的保存会把配置改坏。
      const saved = (self.endpoints || [])
        .find((e) => e.app_name === a && e.method_name === m);
      if (saved) {
        self.openEdit(saved);
        return;
      }
      const d = self.pickable().find((x) => x.app_name === a && x.method_name === m);
      self.form.app_name = a;
      self.form.method_name = m;
      if (d) {
        self.form.kind = d.kind || "external";
        self.form.target = self.form.target || d.target || "";
      }
    },
    openEdit(ep) {
      self.modal.open = true;
      self.form = {
        app_name: ep.app_name, method_name: ep.method_name, kind: ep.kind || "external",
        target: ep.target || "", url: ep.url || "", http_method: ep.http_method || "POST",
        content_type: ep.content_type || "application/json", auth_type: ep.auth_type || "none",
        auth_param_name: ep.auth_param_name || "", auth_credential: "",
        extra_headers: JSON.stringify(ep.extra_headers || {}),
        timeout_s: ep.timeout_s || 30, retries: ep.retries || 1,
        mock_enabled: !!ep.mock_enabled, mock_data: ep.mock_data || "",
      };
    },
    closeModal() { self.modal.open = false; self.form = _blankForm(); },

    async save() {
      const f = self.form;
      if (!f.app_name || !f.method_name || !f.target) return toast("请填应用/方法/目标系统", "warn");
      try {
        await post("/api/integration/endpoints", {
          group: self.group,
          app_name: f.app_name, method_name: f.method_name, kind: f.kind, target: f.target,
          url: f.url || null, http_method: f.http_method, content_type: f.content_type,
          auth_type: f.auth_type, auth_param_name: f.auth_param_name || null,
          auth_credential: f.auth_credential || null,
          extra_headers: f.extra_headers ? JSON.parse(f.extra_headers) : null,
          timeout_s: f.timeout_s, retries: f.retries,
          mock_enabled: f.mock_enabled, mock_data: f.mock_data || null,
        });
        toast("已保存端点");
        self.closeModal();
        await self.load();
      } catch { /* api.js 统一 toast */ }
    },

    async test(id) {
      try {
        const r = await post("/api/integration/test/" + id, {});
        toast(r && r.status === "ok" ? "连通正常" : ("测试失败：" + ((r && r.error) || "未知")), r && r.status === "ok" ? "ok" : "err");
      } catch { /* api.js 统一 toast */ }
    },

    async remove(id) {
      if (!confirm("删除该集成端点？")) return;
      try {
        await del("/api/integration/endpoints/" + id + "?group=" + encodeURIComponent(self.group));
        await self.load();
      } catch { /* api.js 统一 toast */ }
    },
  });
  return self;
}
