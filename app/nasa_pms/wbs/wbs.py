from __future__ import annotations

import re

from fde import FdeError

# 元素类型（材料 §3.3.4：控制账户建立在「WBS 元素 × 组织单元」的交点上，CA 下可分 WP / PP）。
# ⚠ 本版把它们收成**元素的属性**而不是独立聚合 —— 本组没有 OBS（组织分解），
#   为它硬造一个会把 stakeholder 变成两用（见 `术语表.md` 附「本版口径」#1）。
KINDS = ("product", "enabling", "ca", "wp", "pp")
KIND_CN = {"product": "产品", "enabling": "使能性工作", "ca": "控制账户",
           "wp": "工作包", "pp": "规划包"}

# 材料 §3.5.2 点名的**非产品词**（中英对照）。
# ⚠ 这是**例子不是穷举** —— 原文点名的就是这些，拦不住的一律靠人，不假装拦全了（BR-04）。
NON_PRODUCT = (
    "设计", "工程", "制造", "装配", "返工", "复测", "翻修", "直接人工", "阶段",
    "design", "engineering", "manufacturing", "pipe fitter", "direct labor",
    "rework", "retesting", "refurbishing", "phase a", "phase b", "phase c",
)

# 编号规则（§3.4.2）：顶层 6 位数字；每下一层追加 `.` + 两位数字；最多 7 层；含句点 ≤ 24 字符
_CODE_RE = re.compile(r"^\d{6}(\.\d{2}){0,6}$")
MAX_LEVEL = 7
MAX_LEN = 24

_STATUS_CN = {"draft": "草稿", "baselined": "已基线",
              "in_change": "变更中", "closed": "已关闭"}


class Wbs:
    """工作分解结构元素聚合根。项目工作的产品导向层级分解，含元素级配置控制。

    一致性边界（见 `architecture.md` 聚合根卡 12）：
      · **编号即主键**：层级码落库后不可变（BR-07）—— 改编号等于换一个元素，没有入口；
      · **基线是配置控制的分界**：基线前随便改，基线后改动必须走变更流程（BR-05），
        而"变更是否已批准"**不在本聚合**（属 `change_request` 应用，跨应用只读校验）；
      · **覆盖对账只读需求侧**：`coverage` 读 `requirement.list` 求差，不写需求。

    业务规则落点：BR-01 编号与层级自洽 / BR-02 父先于子 / BR-03 不得含未授权范围 /
                 BR-04 产品导向 / BR-05 基线后修订走变更流程 / BR-06 未收口不得关闭 /
                 BR-07 编号不可变。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, wbs_no: str, title: str, kind: str = "product", parent_no: str = None,
               description: str = None, scope_ref: str = None, owner: str = None,
               req_nos: str = None):
        """建立一个元素（顶层或指定父元素）。落库为草稿状态，版次 0。

        ⚠ 顶层元素**必须自带完整编号**（材料 §3.4.2：每个项目分配一个六位数字码）；
        往树上挂子元素请用 `add_child` —— 子号由系统按规则分配，避免手写出不合规的编号。
        """
        wbs_no = self._clean(wbs_no)
        title = self._clean(title)
        parent_no = self._clean(parent_no)
        self._check_code(wbs_no)                                   # BR-01（格式）
        self._check_title(title)                                   # BR-04
        self._check_kind(kind)
        level = self._level_of(wbs_no)
        if parent_no:
            # ⚠ 顺序有讲究：先判「编号与父号自不自洽」（纯格式，不查库），再判「父在不在」（BR-02）。
            #   反过来时，一个自相矛盾的编号会被报成「父不存在」，把人引到错的方向（实测）。
            if self._parent_of(wbs_no) != parent_no:               # BR-01（父号自洽）
                raise FdeError(
                    f"编号 {wbs_no} 的父号应为「{self._parent_of(wbs_no) or '（顶层）'}」，"
                    f"与传入的「{parent_no}」不一致（BR-01）")
            self._need(parent_no)                                  # BR-02（父存在）
        elif level != 1:
            raise FdeError(f"编号 {wbs_no} 是第 {level} 层，必须给出父元素编号（BR-01）")
        if self.get(wbs_no):
            raise FdeError(f"元素编号 {wbs_no} 已存在（编号唯一且落库后不可变，BR-07）")

        self.db.execute(
            "INSERT INTO wbs_element (wbs_no, title, parent_no, level, kind, description,"
            " scope_ref, owner, req_nos, rev_no, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'draft')",
            (wbs_no, title, parent_no or None, level, kind, self._clean(description),
             self._clean(scope_ref), self._clean(owner), self._norm_reqs(req_nos)),
        )
        return self.get(wbs_no)

    def add_child(self, parent_no: str, title: str, kind: str = "product",
                  description: str = None, scope_ref: str = None, owner: str = None,
                  req_nos: str = None):
        """在父元素下**按规则自动分配子号**并建立子元素（`parent.01` / `parent.02`…）。

        子号取同父下最大末段 +1，两位数字。父元素**已关闭**时拒绝：树的收口之后不再长新枝。
        """
        parent = self._need(parent_no)
        if parent["status"] == "closed":
            raise FdeError(f"父元素 {parent['wbs_no']} 已关闭，不能再往下分解（BR-06）")
        seq = 1
        for row in self.db.execute(
                "SELECT wbs_no FROM wbs_element WHERE parent_no = ?", (parent["wbs_no"],)):
            seq = max(seq, int(str(row["wbs_no"]).rsplit(".", 1)[-1]) + 1)
        if seq > 99:
            raise FdeError(f"父元素 {parent['wbs_no']} 下的子元素已达 99 个，两位子号用尽（BR-01）")
        return self.create(f"{parent['wbs_no']}.{seq:02d}", title, kind=kind,
                           parent_no=parent["wbs_no"], description=description,
                           scope_ref=scope_ref, owner=owner, req_nos=req_nos)

    def get(self, wbs_no: str):
        """按元素编号查询字典条目（全字段）；未命中返回 None，不抛异常。"""
        wbs_no = self._clean(wbs_no)
        if not wbs_no:
            return None
        row = self.db.execute(
            "SELECT wbs_no, title, parent_no, level, kind, description, scope_ref, spec_no,"
            " spec_title, charge_code, owner, req_nos, rev_no, rev_authorization, change_no,"
            " status, close_note FROM wbs_element WHERE wbs_no = ?", (wbs_no,),
        ).fetchone()
        return dict(row) if row else None

    def list(self, status: str = None, kind: str = None, parent_no: str = None,
             owner: str = None, keyword: str = None, page: int = None, size: int = None):
        """按状态 / 类型 / 父元素 / 责任方 / 关键词筛选，**分页返回 `{items, total}`**，默认按编号升序。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（见 VIEW_CONVENTION）——
        返回裸数组时页面会显示空态**而不报错**（同组实测踩过）。编号升序即**层级序**：
        编号是点分十进制的，字符串序天然把父排在子前面。
        """
        where, args = [], []
        for col, val in (("status", status), ("kind", kind),
                         ("parent_no", parent_no), ("owner", owner)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        kw = self._clean(keyword)
        if kw:
            where.append("(wbs_no LIKE ? OR title LIKE ? OR description LIKE ?)")
            args += [f"%{kw}%"] * 3
        sql = ("SELECT wbs_no, title, parent_no, level, kind, description, scope_ref, spec_no,"
               " spec_title, charge_code, owner, req_nos, rev_no, rev_authorization, change_no,"
               " status, close_note FROM wbs_element")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY wbs_no"
        rows = [dict(r) for r in self.db.execute(sql, tuple(args)).fetchall()]

        total = len(rows)
        if size:
            p = max(int(page or 1), 1)
            n = max(int(size), 1)
            rows = rows[(p - 1) * n: p * n]
        return {"items": rows, "total": total}

    def update(self, wbs_no: str, title: str = None, description: str = None,
               scope_ref: str = None, spec_no: str = None, spec_title: str = None,
               charge_code: str = None, owner: str = None, req_nos: str = None,
               change_no: str = None):
        """修改字典字段（**编号不在可改字段里** —— BR-07）。

        基线之后要走变更流程：**只允许在 `draft` 与 `in_change` 上修改**；
        对 `baselined` 的元素直接改会被拒，提示先 `change` 发起修订（BR-05）。
        `closed` 是终态，任何改写一律拒绝。
        """
        cur = self._need(wbs_no)
        st = cur["status"]
        if st == "closed":
            raise FdeError(f"元素 {wbs_no} 已关闭，是终态，不能再修改（BR-06）")
        if st == "baselined":
            raise FdeError(
                f"元素 {wbs_no} 已基线，改动必须走变更流程：先 change(wbs_no, change_no) "
                "进入变更中，改完再 baseline 落实（BR-05）")
        title = self._clean(title)
        if title:
            self._check_title(title)                               # BR-04
        sets, args = [], []
        for col, val in (("title", title), ("description", description),
                         ("scope_ref", scope_ref), ("spec_no", spec_no),
                         ("spec_title", spec_title), ("charge_code", charge_code),
                         ("owner", owner)):
            val = self._clean(val)
            if val:
                sets.append(f"{col} = ?")
                args.append(val)
        reqs = self._norm_reqs(req_nos)
        if reqs is not None:
            sets.append("req_nos = ?")
            args.append(reqs)
        cn = self._clean(change_no)
        if cn:
            sets.append("change_no = ?")
            args.append(cn)
        if sets:
            args.append(wbs_no)
            self.db.execute("UPDATE wbs_element SET " + ", ".join(sets) + " WHERE wbs_no = ?",
                            tuple(args))
        return self.get(wbs_no)

    def baseline(self, wbs_no: str):
        """纳入基线（`draft → baselined`）或**落实变更**（`in_change → baselined`，版次 +1）。

        两个入边共用一个服务，靠当前状态分流 —— 因为"基线"在这本书里就是同一个动作：
        把元素的当前内容冻结为基准（材料 §3.1：Phase B 后期建立受控基线）。
        从变更中回来时把版次递增、并把变更号记进**修订授权**（§3.4.4g 的字典必备字段）。

        闸门：父元素必须**已基线**（BR-02 自上而下）；元素必须有**范围定义出处**（BR-03）。
        """
        cur = self._need(wbs_no)
        st = cur["status"]
        if st == "baselined":
            raise FdeError(f"元素 {wbs_no} 已经是已基线状态")
        if st == "closed":
            raise FdeError(f"元素 {wbs_no} 已关闭，是终态（BR-06）")

        if st == "draft":
            parent_no = self._clean(cur["parent_no"])
            if parent_no:
                parent = self.get(parent_no)
                if not parent or parent["status"] not in ("baselined", "in_change"):
                    raise FdeError(
                        f"父元素 {parent_no} 尚未基线，子元素不能先基线（BR-02，自上而下）")
            if not self._clean(cur["scope_ref"]):
                raise FdeError(
                    f"元素 {wbs_no} 没有填「范围定义出处」—— 没有授权出处的元素不得基线"
                    "（BR-03：WBS 不得含未授权的工作范围）")
            self.db.execute("UPDATE wbs_element SET status = 'baselined' WHERE wbs_no = ?",
                            (wbs_no,))
            return self.get(wbs_no)

        # in_change → baselined：落实变更
        cn = self._clean(cur["change_no"])
        self.db.execute(
            "UPDATE wbs_element SET status = 'baselined', rev_no = rev_no + 1,"
            " rev_authorization = ? WHERE wbs_no = ?", (cn or None, wbs_no))
        return self.get(wbs_no)

    def change(self, wbs_no: str, change_no: str, note: str = None):
        """对已基线的元素发起修订（`baselined → in_change`）。

        **变更号必填，且必须在 `change_request` 里是「已批准」** —— 材料 §3.3.6：
        基线 WBS 的任何修订都要按配置管理过程留文档，含变更理由与项目经理批准。
        这是跨应用只读校验（`change_request.get`），**两个应用、两个事务**。
        """
        cur = self._need(wbs_no)
        change_no = self._clean(change_no)
        if not change_no:
            raise FdeError("发起变更必须给出已批准的变更请求号（BR-05，材料 §3.3.6）")
        if cur["status"] == "draft":
            raise FdeError(
                f"元素 {wbs_no} 还是草稿，不在配置控制之下，直接改即可（不需要变更流程，BR-05）")
        if cur["status"] != "baselined":
            raise FdeError(f"元素 {wbs_no} 当前为「{cur['status']}」，只有已基线才能发起变更")

        cr = self.fde.call("change_request", "get", cr_no=change_no)
        if not cr:
            raise FdeError(f"变更请求 {change_no} 不存在（BR-05）")
        if cr.get("status") != "approved":
            raise FdeError(
                f"变更请求 {change_no} 当前为「{cr.get('status')}」，尚未批准 —— "
                "已基线的元素只能按已批准的变更修订（BR-05）")

        sets = ["status = 'in_change'", "change_no = ?"]
        args = [change_no]
        note = self._clean(note)
        if note:
            sets.append("description = COALESCE(description, '') || ?")
            args.append(("" if not cur.get("description") else "\n") + f"[变更 {change_no}] {note}")
        args.append(wbs_no)
        self.db.execute("UPDATE wbs_element SET " + ", ".join(sets) + " WHERE wbs_no = ?",
                        tuple(args))
        return self.get(wbs_no)

    def close(self, wbs_no: str, note: str = None):
        """关闭元素（`baselined → closed`，终态）。

        闸门（BR-06）：**子元素必须全部关闭**（未收口不关闭）；**变更中不得直接关闭**
        （先把变更落实回已基线，再收口）。
        """
        cur = self._need(wbs_no)
        st = cur["status"]
        if st == "closed":
            raise FdeError(f"元素 {wbs_no} 已经关闭")
        if st == "in_change":
            raise FdeError(
                f"元素 {wbs_no} 正处于变更中，不能直接关闭：先把变更落实（baseline 回已基线）再收口（BR-06）")
        if st == "draft":
            raise FdeError(f"元素 {wbs_no} 还是草稿，未纳入配置控制，无需关闭（BR-06）")
        open_kids = [r["wbs_no"] for r in self.db.execute(
            "SELECT wbs_no FROM wbs_element WHERE parent_no = ? AND status <> 'closed'",
            (wbs_no,))]
        if open_kids:
            raise FdeError(
                f"元素 {wbs_no} 下还有 {len(open_kids)} 个未关闭的子元素"
                f"（{'、'.join(open_kids[:3])}…），不能关闭（BR-06）")
        self.db.execute("UPDATE wbs_element SET status = 'closed', close_note = ? WHERE wbs_no = ?",
                        (self._clean(note) or None, wbs_no))
        return self.get(wbs_no)

    def tree(self, root: str = None):
        """返回嵌套树（`children` 递归）；`root` 为空时返回全部顶层。

        一次读全表在内存组树 —— 元素树是**同一个聚合内**的结构（父子都在本表），
        不需要按层往返查库。前端据此画元素树 / 缩进索引（材料 §3.4.3 图 3-12）。
        """
        root = self._clean(root)
        rows = self.list()["items"]
        nodes = {r["wbs_no"]: dict(r, children=[]) for r in rows}
        tops = []
        for no, node in nodes.items():
            parent = self._clean(node["parent_no"])
            if parent and parent in nodes:
                nodes[parent]["children"].append(node)
            elif not root or no == root:
                tops.append(node)
        if root:
            return nodes.get(root)
        return tops

    def coverage(self):
        """需求覆盖对账：返回**两侧缺口**（材料 §3.3.3 的交叉引用矩阵）。

        - `uncovered`：有需求、但没有任何元素把它算进去（§3.3.3「矩阵里没有 X 的位置」）
        - `unassigned`：有元素、但没挂需求出处（可能是"使能性工作"这类共性工作，
          也可能真是漏了 —— 由人判断，本服务只列出来）

        需求侧是**跨应用只读**（`requirement.list`），本应用不写需求。
        """
        res = self.fde.call("requirement", "list", page=1, size=9999)
        reqs = (res or {}).get("items") or []
        used = set()
        for r in self.db.execute("SELECT req_nos FROM wbs_element"):
            used |= self._req_set(r["req_nos"])
        uncovered = [{"req_no": q.get("req_no"), "title": q.get("title"),
                      "status": q.get("status")}
                     for q in reqs if self._clean(q.get("req_no")) not in used]
        unassigned = [{"wbs_no": r["wbs_no"], "title": r["title"], "kind": r["kind"]}
                      for r in self.db.execute(
                          "SELECT wbs_no, title, kind FROM wbs_element"
                          " WHERE req_nos IS NULL OR req_nos = '' ORDER BY wbs_no")]
        return {"requirements_total": len(reqs), "covered": len(reqs) - len(uncovered),
                "uncovered": uncovered, "unassigned": unassigned}

    # ── 私有（非服务） ────────────────────────────────────

    @staticmethod
    def _clean(v):
        return str(v).strip() if v is not None else ""

    @staticmethod
    def _req_set(s):
        return {x.strip() for x in str(s or "").split(",") if x.strip()}

    def _norm_reqs(self, v):
        """把逗号分隔的需求编号规范化（去空、去重、保序）；空 → None（不写空串）。"""
        if v is None:
            return None
        got = []
        for x in str(v).split(","):
            x = x.strip()
            if x and x not in got:
                got.append(x)
        return ",".join(got) if got else None

    @staticmethod
    def _level_of(code: str) -> int:
        return code.count(".") + 1

    @staticmethod
    def _parent_of(code: str) -> str:
        return code.rsplit(".", 1)[0] if "." in code else ""

    @staticmethod
    def _check_code(code: str):
        """BR-01：编号必须是分层十进制码，且不超层数 / 长度上限（材料 §3.4.2）。"""
        if not code:
            raise FdeError("元素编号不能为空（BR-01）")
        if len(code) > MAX_LEN:
            raise FdeError(f"元素编号 {code} 长 {len(code)} 字符，超过上限 {MAX_LEN} 字符（BR-01）")
        if code.count(".") + 1 > MAX_LEVEL:
            raise FdeError(f"元素编号 {code} 有 {code.count('.') + 1} 层，最多 {MAX_LEVEL} 层（BR-01）")
        if not _CODE_RE.match(code):
            raise FdeError(
                f"元素编号 {code} 不符合编码规则：顶层是 6 位数字，每下一层追加「.」+ 两位数字"
                "（如 123456.02.07）（BR-01）")

    @staticmethod
    def _check_kind(kind: str):
        if kind not in KINDS:
            raise FdeError(f"元素类型只能是 {'/'.join(KINDS)} 之一（"
                           f"{'/'.join(KIND_CN[k] for k in KINDS)}）")

    @staticmethod
    def _check_title(title: str):
        """BR-04：名称必须产品导向 —— 材料 §3.5.2 点名的非产品词一律拦（是例子不是穷举）。"""
        if not title:
            raise FdeError("元素名称不能为空（BR-04）")
        low = title.lower()
        for bad in NON_PRODUCT:
            if bad in low:
                raise FdeError(
                    f"元素名称「{title}」含非产品词「{bad}」—— WBS 元素要按**产品**分解，"
                    "不能用职能 / 组织 / 阶段 / 工种来分（BR-04，材料 §3.5.2）")

    def _need(self, wbs_no: str):
        cur = self.get(wbs_no)
        if not cur:
            raise FdeError(f"元素编号 {self._clean(wbs_no) or '（空）'} 不存在")
        return cur
