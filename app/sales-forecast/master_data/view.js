/* app/sales-forecast/master_data/view.js —— 主数据中心（多 Tab：客户/物料/车型/用户/日历） */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

export const PAGE_META = {
  key: "master_data", name: "主数据中心", ic: "🗄",
  title: "主数据中心", crumb: "客户 · 物料 · 车型 · 用户 · 日历",
  order: 80,
};

export default function pageMasterData() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,

    /* ---- Tab 管理 ---- */
    tab: "customer",
    tabLabel(t) {
      return { customer: "客户", part: "物料", vehicle: "车型", user: "用户", calendar: "日历" }[t] || t;
    },

    /* ---- 客户 Tab ---- */
    customerList: null,
    customerModal: { open: false, loading: false, d: null },

    /* ---- 物料 Tab ---- */
    partList: null,
    partModal: { open: false, loading: false, d: null },

    /* ---- 车型 Tab ---- */
    vehicleList: null,
    vehicleModal: { open: false, loading: false, d: null },

    /* ---- 用户 Tab ---- */
    userList: null,
    userModal: { open: false, loading: false, d: null },

    /* ---- 日历 Tab ---- */
    calendarList: null,

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());

      /* 所有 Tab 的 pageable 在所有 await 之前同步建好 */
      self.customerList = pageable(async (q) => svc("master_data", "list_customers", { ...q }));
      self.partList = pageable(async (q) => svc("master_data", "list_parts", { ...q }));
      self.vehicleList = pageable(async (q) => svc("master_data", "list_vehicles", { ...q }));
      self.userList = pageable(async (q) => svc("master_data", "list_users", { ...q }));
      self.calendarList = pageable(async (q) => svc("master_data", "list_customers", { ...q })); /* 日历暂用 skeleton */

      /* 只加载当前 tab */
      await self.loadTab();
    },

    async switchTab(t) {
      self.tab = t;
      await self.loadTab();
    },

    async loadTab() {
      const t = self.tab;
      if (t === "customer" && self.customerList.items.length === 0) await self.customerList.load();
      else if (t === "part" && self.partList.items.length === 0) await self.partList.load();
      else if (t === "vehicle" && self.vehicleList.items.length === 0) await self.vehicleList.load();
      else if (t === "user" && self.userList.items.length === 0) await self.userList.load();
      else if (t === "calendar" && self.calendarList.items.length === 0) await self.calendarList.load();
    },

    /* ---- 客户详情 ---- */
    async viewCustomer(d) {
      self.customerModal = { open: true, loading: true, d: null };
      try {
        self.customerModal.d = await svc("master_data", "get_customer", { oem_code: d.oem_code });
      } catch { self.customerModal.open = false; } finally { self.customerModal.loading = false; }
    },
    closeCustomerModal() { self.customerModal.open = false; },

    /* ---- 物料详情 ---- */
    async viewPart(d) {
      self.partModal = { open: true, loading: true, d: null };
      try {
        self.partModal.d = await svc("master_data", "get_part", { part_no: d.part_no });
      } catch { self.partModal.open = false; } finally { self.partModal.loading = false; }
    },
    closePartModal() { self.partModal.open = false; },

    /* ---- 车型详情 ---- */
    async viewVehicle(d) {
      self.vehicleModal = { open: true, loading: true, d: null };
      try {
        self.vehicleModal.d = await svc("master_data", "get_vehicle", { veh_model: d.veh_model });
      } catch { self.vehicleModal.open = false; } finally { self.vehicleModal.loading = false; }
    },
    closeVehicleModal() { self.vehicleModal.open = false; },

    /* ---- 用户详情 ---- */
    async viewUser(d) {
      self.userModal = { open: true, loading: true, d: null };
      try {
        self.userModal.d = await svc("master_data", "get_user", { userno: d.userno });
      } catch { self.userModal.open = false; } finally { self.userModal.loading = false; }
    },
    closeUserModal() { self.userModal.open = false; },
  });
  return self;
}
