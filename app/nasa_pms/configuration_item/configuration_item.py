from __future__ import annotations

import re

from fde import FdeError

# 配置项类型字典（材料 §6.5.1.3「Outputs」：CM 列为受控项的是 items / documents / hardware /
# software / models ...；术语表未收类型名，第②步就地取名并回填）
TYPES = ("hardware", "software", "document", "model", "data")
# 材料 §6.5.1.2.2 与 FIGURE 6.5-3：NASA 通常控制四条基线
BASELINES = ("functional", "allocated", "product", "as_deployed")
BASELINE_CN = {"functional": "功能基线", "allocated": "分配基线",
               "product": "产品基线", "as_deployed": "部署基线"}
# 「已发布」的内容冻结：改它必须带已批准的变更号（BR-02）。archived 是终态，另按 BR-02 后半拦死。
_FROZEN = ("released",)
_ARCHIVED = "archived"


class ConfigurationItem:
    """配置项聚合根。纳入配置管理的工作产品，含版本与基线归属。数据来源类型：独立创建。

    一致性边界（见 `architecture.md` 聚合根卡 3）：
      · 配置项的**版本与状态同事务维护** —— 版本递增会让状态回落到「受控」（新版本尚未发布），
        这一步必须原子完成，否则会出现"版本已变、状态仍显示已发布"的假象；
      · **已被基线冻结的版本**由本聚合内 `baseline` / `baseline_ver` 承载，不跨应用维护；
      · **变更请求的审批不在本聚合**（属 `change_request` 应用）—— 本应用只校验"是否带了变更号"，
        "变更是否已批准"由 `change_request` 保证（**该应用已建成**，本版有意不做该校验 ——
        接线只是加一行 `self.fde.call("change_request", "get", ...)`，见详设 §6.3）。

    业务规则落点：BR-01 版本只能递增 / BR-02 已发布版本不可改写（归档为终态）/
                 BR-03 版本变更须经已批准的变更请求 / BR-04 编号唯一且不可变 / BR-05 类型受字典约束。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, name: str, ci_type: str, owner: str = None, project_no: str = None):
        """新建一个配置项，落库为草稿状态，初始版本恒为 v1（新配置项从第一版开始）。"""
        name = self._clean(name)
        ci_type = self._clean(ci_type)
        if not name:
            raise FdeError("配置项名称不能为空")
        self._check_type(ci_type)                               # BR-05

        ci_no = self._next_no()
        self.db.execute(
            "INSERT INTO configuration_item (ci_no, name, ci_type, version, status,"
            " owner, project_no)"
            " VALUES (?, ?, ?, 1, 'draft', ?, ?)",
            (ci_no, name, ci_type, self._clean(owner), self._clean(project_no)),
        )
        return self.get(ci_no)

    def control(self, ci_no: str, owner: str = None):
        """提交受控：草稿 → 受控（`draft → controlled`）。

        受控是"纳入配置管理"的时点 —— 材料 §6.5.1.1「Designated configuration items to be
        controlled」：先有受控项清单，才有基线与变更控制。故**未受控的配置项不能纳入基线**。
        """
        cur = self._need(ci_no)
        if cur["status"] == "controlled":
            raise FdeError(f"配置项 {ci_no} 已经是受控状态")
        if cur["status"] != "draft":
            raise FdeError(f"配置项 {ci_no} 当前为「{cur['status']}」，只有草稿状态才能提交受控")
        sets, args = ["status = 'controlled'"], []
        owner = self._clean(owner)
        if owner:
            sets.append("owner = ?")
            args.append(owner)
        args.append(ci_no)
        self.db.execute("UPDATE configuration_item SET " + ", ".join(sets) + " WHERE ci_no = ?",
                        tuple(args))
        return self.get(ci_no)

    def release(self, ci_no: str, change_no: str = None):
        """发版：受控 → 已发布（`controlled → released`），把当前版本冻结为已发布版本。

        **首次发版不需要变更号**（新配置项第一次基线化就是发版本，无所谓"变更"）；
        **非首次发版属于版本变更**，必须携带已批准的变更请求号（BR-03，与 `bump_version` 同源规则）。
        """
        cur = self._need(ci_no)
        if cur["status"] != "controlled":
            raise FdeError(f"配置项 {ci_no} 当前为「{cur['status']}」，只有受控状态才能发版")
        change_no = self._clean(change_no)
        if cur["released_ver"] and not change_no:
            raise FdeError(
                f"配置项 {ci_no} 已有发布版本 v{cur['released_ver']}，再次发版属于版本变更，"
                "必须携带已批准的变更请求号（BR-03）")

        sets = ["status = 'released'", "released_ver = ?"]
        args = [cur["version"]]
        if change_no:
            sets.append("change_no = ?")
            args.append(change_no)
        args.append(ci_no)
        self.db.execute("UPDATE configuration_item SET " + ", ".join(sets) + " WHERE ci_no = ?",
                        tuple(args))
        return self.get(ci_no)

    def bump_version(self, ci_no: str, new_version, change_no: str):
        """版本变更：把当前版本升到 `new_version`，状态回落为「受控」。

        两条不变量同时落在本服务上：
          · **BR-01 只能递增** —— `new_version` 必须严格大于当前版本；
          · **BR-03 必须经由已批准的变更请求** —— `change_no` 必填；本应用只能校验"带了变更号"，
            "变更是否已批准"由 `change_request` 应用保证（该应用建成后应改为跨应用校验，见详设 §6.3）。

        状态回落为「受控」是刻意的：**已发布版本不可改写**（BR-02），新版本要重新走发版才算发布。
        """
        cur = self._need(ci_no)
        if cur["status"] == _ARCHIVED:
            raise FdeError(f"配置项 {ci_no} 已归档（终态），不能再变更版本")
        change_no = self._clean(change_no)
        if not change_no:
            raise FdeError("版本变更必须经由已批准的变更请求，请提供变更请求号（BR-03）")
        nv = self._int(new_version, "新版本号")
        if nv <= int(cur["version"]):
            raise FdeError(
                f"配置项版本只能递增：新版本 v{nv} 不大于当前版本 v{cur['version']}（BR-01）")

        self.db.execute(
            "UPDATE configuration_item SET version = ?, status = 'controlled', change_no = ?"
            " WHERE ci_no = ?", (nv, change_no, ci_no))
        return self.get(ci_no)

    def assign_baseline(self, ci_no: str, baseline: str, baseline_ver: str = None):
        """把配置项纳入某条基线（材料 §6.5.1.2.2 的四条基线之一）。

        校验：类型受字典约束；**未受控的配置项不能进基线**（还没纳入配置管理）；已归档不能进；
        同一配置项**不能重复纳入同一条基线**（基线一旦建立即是变更的基准，重复纳入使基准失去意义）。
        """
        cur = self._need(ci_no)
        baseline = self._clean(baseline)
        if baseline not in BASELINES:
            raise FdeError(f"基线只能是 {'/'.join(BASELINES)} 之一")
        if cur["status"] == "draft":
            raise FdeError(f"配置项 {ci_no} 尚未受控，不能纳入基线（请先提交受控）")
        if cur["status"] == _ARCHIVED:
            raise FdeError(f"配置项 {ci_no} 已归档，不能纳入基线")
        if cur["baseline"] == baseline:
            raise FdeError(f"配置项 {ci_no} 已在「{BASELINE_CN[baseline]}」中，不能重复纳入")

        self.db.execute(
            "UPDATE configuration_item SET baseline = ?, baseline_ver = ? WHERE ci_no = ?",
            (baseline, self._clean(baseline_ver) or None, ci_no))
        return self.get(ci_no)

    def update(self, ci_no: str, name: str = None, ci_type: str = None,
               owner: str = None, change_no: str = None):
        """修改配置项内容（名称 / 类型 / 责任人）。

        **版本与编号都不在本服务的字段白名单里**：版本只能经 `bump_version` 递增（BR-01），
        编号落库不可变（BR-04）—— 没有参数可传，也就无从改起。

        已发布（`released`）的配置项**不得直接改写**，必须携带已批准的变更号（BR-02）；
        已归档（`archived`）是终态，任何修改都拒绝。
        """
        cur = self._need(ci_no)
        if cur["status"] == _ARCHIVED:
            raise FdeError(f"配置项 {ci_no} 已归档（终态），不能再修改")
        change_no = self._clean(change_no)
        if cur["status"] in _FROZEN:
            if not change_no:
                raise FdeError("已发布的配置项不能直接修改，请先提交变更请求（BR-02）")
            self.db.execute("UPDATE configuration_item SET change_no = ? WHERE ci_no = ?",
                            (change_no, ci_no))

        sets, args = [], []
        if name is not None:
            name = self._clean(name)
            if not name:
                raise FdeError("配置项名称不能为空")
            sets.append("name = ?")
            args.append(name)
        if ci_type is not None:
            ci_type = self._clean(ci_type)
            self._check_type(ci_type)                           # BR-05
            sets.append("ci_type = ?")
            args.append(ci_type)
        if owner is not None:
            sets.append("owner = ?")
            args.append(self._clean(owner))
        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(ci_no)
        self.db.execute("UPDATE configuration_item SET " + ", ".join(sets) + " WHERE ci_no = ?",
                        tuple(args))
        return self.get(ci_no)

    def archive(self, ci_no: str, reason: str = None):
        """归档：已发布 → 已归档（`released → archived`，状态机终态）。

        只有**已发布**的配置项能归档 —— 归档是对"已交付的版本"做收尾（材料 §6.5.1.2.4
        Configuration Status Accounting 要求保留完整历史）。草稿/受控项未交付，直接归档会让
        历史里出现"从没有过已发布版本却已归档"的空洞。
        归档后**不删除**：材料要求 historical traceability，记录必须留存且不可再改。
        """
        cur = self._need(ci_no)
        if cur["status"] == _ARCHIVED:
            raise FdeError(f"配置项 {ci_no} 已经是归档状态")
        if cur["status"] != "released":
            raise FdeError(f"配置项 {ci_no} 当前为「{cur['status']}」，只有已发布的配置项才能归档")
        self.db.execute("UPDATE configuration_item SET status = 'archived' WHERE ci_no = ?",
                        (ci_no,))
        out = self.get(ci_no)
        out["reason"] = self._clean(reason) or None
        return out

    def get(self, ci_no: str):
        """按配置项编号查询；未命中返回 None，不抛异常。"""
        ci_no = self._clean(ci_no)
        if not ci_no:
            return None
        row = self.db.execute(
            "SELECT ci_no, name, ci_type, version, released_ver, baseline, baseline_ver,"
            " status, owner, change_no, project_no"
            " FROM configuration_item WHERE ci_no = ?", (ci_no,),
        ).fetchone()
        return dict(row) if row else None

    def list(self, ci_type: str = None, status: str = None, baseline: str = None,
             page: int = None, size: int = None):
        """按类型 / 状态 / 所属基线筛选，**分页返回 `{items, total}`**，默认按编号升序。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（见 VIEW_CONVENTION）——
        少了它们，前端拿到的 `items` 恒为空、页面静默显示空态而**不报错**（同组实测踩过：
        后端返回裸数组时，页面显示「暂无数据」却 0 error）。
        """
        where, args = [], []
        for col, val in (("ci_type", ci_type), ("status", status), ("baseline", baseline)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = ("SELECT ci_no, name, ci_type, version, released_ver, baseline, baseline_ver,"
               " status, owner FROM configuration_item")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ci_no"
        rows = [dict(r) for r in self.db.execute(sql, tuple(args)).fetchall()]

        total = len(rows)
        if size:
            p = max(int(page or 1), 1)
            n = max(int(size), 1)
            rows = rows[(p - 1) * n: p * n]
        return {"items": rows, "total": total}

    # ── 私有（非服务） ────────────────────────────────────

    @staticmethod
    def _clean(v):
        return str(v).strip() if v is not None else ""

    @staticmethod
    def _int(v, label: str) -> int:
        """把入参解析为正整数，非法即拒（None / 空串 / 小数 / 非数字都拦下）。"""
        s = str(v).strip() if v is not None else ""
        if not re.match(r"^\d+$", s):
            raise FdeError(f"{label}必须是正整数")
        n = int(s)
        if n < 1:
            raise FdeError(f"{label}必须大于 0")
        return n

    @staticmethod
    def _check_type(ci_type: str):
        if not ci_type:
            raise FdeError("配置项类型不能为空")
        if ci_type not in TYPES:
            raise FdeError(f"配置项类型只能是 {'/'.join(TYPES)} 之一（BR-05）")

    def _need(self, ci_no: str):
        ci_no = self._clean(ci_no)
        if not ci_no:
            raise FdeError("配置项编号不能为空")
        cur = self.get(ci_no)
        if not cur:
            raise FdeError(f"配置项 {ci_no} 不存在")
        return cur

    def _next_no(self) -> str:
        """生成下一个配置项编号：CI-<三位序号>（BR-04：编号唯一）。"""
        rows = self.db.execute("SELECT ci_no FROM configuration_item").fetchall()
        mx = 0
        for r in rows:
            m = re.match(r"^CI-(\d+)$", str(r["ci_no"]))
            if m:
                mx = max(mx, int(m.group(1)))
        return f"CI-{mx + 1:03d}"
