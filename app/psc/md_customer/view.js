/* app/psc/md_customer/view.js（与后端 md_customer.py 同文件夹 · 第⑦步前端编码） */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名（与后端应用名对齐）；
   order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "md_customer", name: "客户主数据", ic: "🏢",
  title: "客户主数据", crumb: "主数据 · 客户/结算模式/线边缓冲参数",
  order: 20,
};

export default function pageMdCustomer() {
  const self = Alpine.reactive({
    tpl: "", hue, fmt,
    list: null,                                        // pageable 实例
    filterNo: "",                                      // 客户编码模糊过滤
    filterName: "",                                    // 客户名称模糊过滤
    filterCredit: "",                                  // 统一社会信用代码模糊过滤
    modalX: { open: false, loading: false, d: null },  // 详情模态
    form: { open: false, busy: false, mode: "create",
      customer_no: "", customer_name: "", settle_mode: "", credit_code: "",
      line_stock_days: "", transfer_lead_days: "" },   // 创建 / 编辑表单
    imp: { open: false, busy: false, text: "", result: null },   // 批量导入模态
    tip: { show: "", pin: "" },                        // 表头字段释义：悬停显示 / 点击钉住
    TIPS: {
      line_stock_days: "客户自有产线旁已放置的缓冲库存可支撑的天数。用于计算最低库存 A = 日需求 × max(0, 生产时间 + 物流时间 − 线边天数)：天数越长，需我方库存兜底的缺口越小。",
      transfer_lead_days: "零件从我方仓库调拨到客户仓库 / 线边所需的天数。与线边库存天数共同构成客户侧缓冲，用于「不设安全库存」硬条件判定：生产时间 + 物流时间 ≤ 线边天数 + 调拨提前期时，高价值件可用速度对冲，不设安全库存。",
    },
    tipShow(k) { self.tip.show = k; },
    tipHide() { if (!self.tip.pin) self.tip.show = ""; },
    tipToggle(k) {
      self.tip.pin = self.tip.pin === k ? "" : k;
      self.tip.show = self.tip.pin || k;
    },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("md_customer", "list",
        { customer_no: self.filterNo || undefined, customer_name: self.filterName || undefined,
          credit_code: self.filterCredit || undefined, ...q }));
      await self.list.load();
    },

    search() { self.list.load(1); },

    /* 详情模态：点客户编码 → get 全量字段 */
    async view(d) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("md_customer", "get", { customer_no: d.customer_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeModal() { self.modalX.open = false; },

    /* 创建表单 */
    openCreate() {
      self.form = { open: true, busy: false, mode: "create",
        customer_no: "", customer_name: "", settle_mode: "", credit_code: "",
        line_stock_days: "", transfer_lead_days: "" };
    },

    /* 编辑表单（列表行 / 详情页脚两处入口；customer_no 只读锁定） */
    edit(d) {
      self.modalX.open = false;
      self.form = { open: true, busy: false, mode: "edit",
        customer_no: d.customer_no, customer_name: d.customer_name,
        settle_mode: d.settle_mode || "", credit_code: d.credit_code || "",
        line_stock_days: d.line_stock_days,
        transfer_lead_days: d.transfer_lead_days ?? "" };
    },
    closeForm() { self.form.open = false; },

    async save() {
      const f = self.form;
      if (!f.customer_no || !f.customer_name) return toast("客户编码与客户名称必填", "warn");
      f.busy = true;
      try {
        const payload = {
          customer_no: f.customer_no,
          customer_name: f.customer_name,
          settle_mode: f.settle_mode,
          credit_code: f.credit_code,
          line_stock_days: f.line_stock_days,
          transfer_lead_days: f.transfer_lead_days,
        };
        if (f.mode === "edit") {
          await svc("md_customer", "update", payload);
          toast("客户主数据更新成功");
        } else {
          await svc("md_customer", "create", payload);
          toast("客户主数据创建成功");
        }
        f.open = false;
        await self.list.load(self.list.page);
      } catch { /* api.js 已 toast；表单保持打开便于修改后重试 */ } finally { f.busy = false; }
    },

    /* 批量导入（ERP 冗余同步）：逐行录入 / 文件读取 → import_batch upsert */
    openImport() { self.imp = { open: true, busy: false, text: "", result: null }; },
    closeImport() { self.imp.open = false; },

    async onImportFile(ev) {
      const file = ev.target.files && ev.target.files[0];
      if (!file) return;
      try { self.imp.text = await file.text(); } catch { toast("文件读取失败", "warn"); }
    },

    downloadTemplate() {
      const csv = "﻿" + "customer_no,customer_name,credit_code,settle_mode,line_stock_days,transfer_lead_days\n"
        + "C1001,某客户,91110000710931000M,现售,3,2\n";
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "md_customer_import_template.csv";
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    },

    /* 解析导入文本 → rows（JSON 数组或 CSV/TSV 逐行；首行表头自动跳过） */
    parseImport() {
      const text = (self.imp.text || "").trim();
      if (!text) return [];
      let rows = [];
      if (text[0] === "[" || text[0] === "{") {
        try {
          const parsed = JSON.parse(text);
          rows = Array.isArray(parsed) ? parsed : [parsed];
        } catch { toast("JSON 格式错误", "warn"); return null; }
      } else {
        const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
        const sep = lines[0].includes("\t") ? "\t" : ",";
        const start = /customer_no/i.test(lines[0]) ? 1 : 0;   // 首行表头跳过
        rows = [];
        for (let i = start; i < lines.length; i++) {
          const cells = lines[i].split(sep).map((c) => c.trim().replace(/^"|"$/g, ""));
          if (!cells.some(Boolean)) continue;
          rows.push({
            customer_no: cells[0] || "",
            customer_name: cells[1] || "",
            credit_code: cells[2] || "",
            settle_mode: cells[3] || "",
            line_stock_days: cells[4] || "",
            transfer_lead_days: cells[5] || "",
          });
        }
      }
      return rows.filter((r) => r && typeof r === "object" && !Array.isArray(r));
    },

    async submitImport() {
      const rows = self.parseImport();
      if (rows === null) return;                        // JSON 解析错误已 toast
      if (!rows.length) return toast("请粘贴或选择导入数据", "warn");
      self.imp.busy = true; self.imp.result = null;
      try {
        const r = await svc("md_customer", "import_batch", { rows });
        self.imp.result = r;
        toast(`导入完成 · 成功 ${r.success} 条 / 失败 ${r.fail} 条`);
        await self.list.load(1);
      } catch { /* api.js 已 toast */ } finally { self.imp.busy = false; }
    },
  });
  return self;
}
