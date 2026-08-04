/* app/e2e/member/view.js（与后端 member.py 同文件夹） */
import { svc, hue, fmt, toast } from "/view/lib/api.js";
import { pageable } from "/view/lib/shell.js";

/* 页面自描述（平台扫描的唯一入口）：key = 应用文件夹名（与后端应用名对齐）；
   order 升序 = 菜单顺序 */
export const PAGE_META = {
  key: "member", name: "成员管理", ic: "👥",
  title: "成员管理", crumb: "成员主数据 · 任务指派基础 · 创建后只读",
  order: 10,
};

export default function pageMember() {
  const self = Alpine.reactive({
    tpl: "",
    hue, fmt,
    list: null,                                        // pageable 实例
    filter: "",                                        // 角色过滤：'' 全部 / admin / member
    keyword: "",                                       // 编号 / 姓名 / 邮箱 模糊搜索
    modalX: { open: false, loading: false, d: null },  // 详情模态
    form: { open: false, busy: false, member_no: "", name: "", email: "", role: "member" },

    roleLabel(r) { return { admin: "管理员", member: "成员" }[r] || r || "—"; },

    async init() {
      self.tpl = await fetch(new URL("view.html", import.meta.url)).then((r) => r.text());
      self.list = pageable(async (q) => svc("member", "list",
        { keyword: self.keyword, role: self.filter, ...q }));   // 闭包引用 self（代理）
      await self.list.load();
    },

    search() { self.list.load(1); },

    /* 详情模态：点成员编号 → get 全量字段 */
    async viewMember(doc) {
      self.modalX = { open: true, loading: true, d: null };
      try {
        self.modalX.d = await svc("member", "get", { member_no: doc.member_no });
      } catch { self.modalX.open = false; } finally { self.modalX.loading = false; }
    },
    closeModal() { self.modalX.open = false; },

    /* 创建表单（仅创建 —— BR-11 不开放 update / delete / 停用，无编辑态） */
    openCreate() {
      self.form = { open: true, busy: false, member_no: "", name: "", email: "", role: "member" };
    },
    closeCreate() { self.form.open = false; },
    resetForm() {
      self.form.member_no = ""; self.form.name = "";
      self.form.email = ""; self.form.role = "member";
    },

    async save() {
      const f = self.form;
      if (!f.member_no || !f.name || !f.email || !f.role) return toast("必填字段缺失", "warn");
      f.busy = true;
      try {
        await svc("member", "create", {
          member_no: f.member_no, name: f.name, email: f.email, role: f.role,
        });
        const no = f.member_no;
        f.open = false; self.resetForm();
        toast(`成员 ${no} 创建成功`);
        await self.list.load(1);                       // 保留 keyword/role 过滤，回第 1 页重载
      } catch { /* api.js 已 toast；创建模态保持打开便于修改后重试 */ } finally { f.busy = false; }
    },
  });
  return self;
}