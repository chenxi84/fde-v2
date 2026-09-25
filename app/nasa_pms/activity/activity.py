from __future__ import annotations

import datetime as _dt

from fde import FdeError

# 活动类型（材料 §5.5.5：summary activity 与 discrete measurable activity 是两类写法）
KINDS = ("summary", "activity", "milestone")
KIND_CN = {"summary": "汇总", "activity": "活动", "milestone": "里程碑"}
# 边界里程碑：只有这两个允许"没有前置 / 没有后续"（§5.5.8 的 no open ends 的例外）
PHASES = ("start", "finish")
STATUS_CN = {"planned": "计划", "in_progress": "进行中", "completed": "已完成"}


class Activity:
    """进度活动聚合根。IMS 里的一个离散可度量工作单元（活动 / 里程碑）。

    一致性边界（见 `architecture.md` 聚合根卡 13）：
      · **日期不进表**：表里只有 `duration_days` 与 `predecessors`，计划日期由 `schedule_view()`
        **正推派生** —— 材料 §5.5.9.3 要的就是这个（"dates … determined by logic and durations
        rather than by wishful thinking or estimates constructed to meet a particular finish date"）；
      · **基线是正交维度**：`baseline_start` 非空即已基线，它不改 `status`；基线后改计划字段
        由 BR-07 拦（要已批准的变更号）；
      · **回填实绩不碰基线**：`record_progress` 的写集合里没有基线列（BR-08，§7.3 原话）；
      · **挂靠是跨应用只读校验**：`wbs.get` + `wbs.list(parent_no=…)` 判叶子，本应用不写 wbs。

    业务规则落点：BR-01 禁开口端 / BR-02 禁冗余链接 / BR-03 逻辑链完整且无环 /
                 BR-04 里程碑工期为 0 / BR-05 必须挂在 WBS 叶子 / BR-06 名称唯一 /
                 BR-07 基线后走变更 / BR-08 回填实绩不动基线。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, name: str, wbs_no: str, duration_days: int = 1,
               kind: str = "activity", predecessors: str = None, owner: str = None,
               phase: str = None, note: str = None):
        """建一个活动（或汇总活动）。编号系统生成；`wbs_no` 必须是 **WBS 的叶子元素**。"""
        name = self._clean(name)
        if not name:
            raise FdeError("活动名称不能为空（BR-06）")
        self._check_kind(kind)
        self._check_name_free(name)                                  # BR-06
        wbs_no = self._need_leaf(wbs_no)                             # BR-05（跨应用）
        phase = self._clean(phase)
        if phase and phase not in PHASES:
            raise FdeError(f"边界标记只能是 {'/'.join(PHASES)} 之一（BR-01）")
        dur = self._check_duration(kind, duration_days)              # BR-04
        preds = self._norm(predecessors)
        self._assert_preds_exist(preds)                              # BR-03（存在性）
        self._assert_acyclic(None, preds)                            # BR-03（无环）
        # ⚠ 建活动时也要查冗余：只查 link 的话，建的时候一次性把冗余前置塞进来就绕过去了
        self._assert_no_redundant(None, preds)                       # BR-02

        act_no = self._next_no()
        self.db.execute(
            "INSERT INTO activity (act_no, name, kind, phase, wbs_no, duration_days,"
            " predecessors, owner, status, percent_complete, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned', 0, ?)",
            (act_no, name, kind, phase or None, wbs_no, dur,
             ",".join(preds) or None, self._clean(owner), self._clean(note)),
        )
        return self.get(act_no)

    def add_milestone(self, name: str, wbs_no: str, predecessors: str = None,
                      owner: str = None, phase: str = None, note: str = None):
        """建里程碑（工期恒 0 的便捷入口 —— 里程碑是**事件**不是工作，§5.5.7.1）。"""
        return self.create(name=name, wbs_no=wbs_no, duration_days=0, kind="milestone",
                           predecessors=predecessors, owner=owner, phase=phase, note=note)

    def get(self, act_no: str):
        """按编号查活动；未命中返回 None，不抛异常。"""
        act_no = self._clean(act_no)
        if not act_no:
            return None
        row = self.db.execute(
            "SELECT act_no, name, kind, phase, wbs_no, duration_days, predecessors, owner,"
            " status, percent_complete, actual_start, actual_finish, baseline_start,"
            " baseline_finish, change_no, note FROM activity WHERE act_no = ?", (act_no,),
        ).fetchone()
        return dict(row) if row else None

    def list(self, status: str = None, kind: str = None, wbs_no: str = None,
             owner: str = None, baselined: str = None, keyword: str = None,
             page: int = None, size: int = None):
        """按状态 / 类型 / 挂靠元素 / 责任方 / 是否已基线 / 关键词筛选，**分页返回 `{items,total}`**。

        ⚠ `page`/`size` 与 `{items,total}` 是前端 `pageable` 的契约（VIEW_CONVENTION）——
        返回裸数组时页面显示空态而不报错（同组实测踩过）。
        """
        where, args = [], []
        for col, val in (("status", status), ("kind", kind), ("wbs_no", wbs_no), ("owner", owner)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        b = self._clean(baselined)
        if b in ("1", "true", "yes"):
            where.append("baseline_start IS NOT NULL")
        elif b in ("0", "false", "no"):
            where.append("baseline_start IS NULL")
        kw = self._clean(keyword)
        if kw:
            where.append("(act_no LIKE ? OR name LIKE ? OR wbs_no LIKE ?)")
            args += [f"%{kw}%"] * 3
        sql = ("SELECT act_no, name, kind, phase, wbs_no, duration_days, predecessors, owner,"
               " status, percent_complete, actual_start, actual_finish, baseline_start,"
               " baseline_finish, change_no, note FROM activity")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY act_no"
        rows = [dict(r) for r in self.db.execute(sql, tuple(args)).fetchall()]
        total = len(rows)
        if size:
            p = max(int(page or 1), 1)
            n = max(int(size), 1)
            rows = rows[(p - 1) * n: p * n]
        return {"items": rows, "total": total}

    def update(self, act_no: str, name: str = None, duration_days: int = None,
               predecessors: str = None, wbs_no: str = None, owner: str = None,
               note: str = None, change_no: str = None):
        """改**计划字段**（名称 / 工期 / 前置 / 挂靠元素 / 责任方 / 备注）。

        BR-07：**已基线**的活动必须先 `change(act_no, change_no)` 挂上已批准的变更号才允许改
        —— 材料 §7.3：进度基线受项目的变更控制过程控制。**编号不可改**（不在可改字段里）。
        """
        cur = self._need(act_no)
        cn = self._clean(change_no)
        if cur["baseline_start"] and not cn:
            raise FdeError(
                f"活动 {act_no} 已基线（{cur['baseline_start']}），改动必须走变更流程："
                "先 change(act_no, change_no) 挂上已批准的变更号（BR-07）")
        sets, args = [], []
        nm = self._clean(name)
        if nm:
            self._check_name_free(nm, exclude=act_no)                # BR-06
            sets.append("name = ?")
            args.append(nm)
        if duration_days is not None:
            sets.append("duration_days = ?")
            args.append(self._check_duration(cur["kind"], duration_days))   # BR-04
        if predecessors is not None:
            preds = self._norm(predecessors)
            self._assert_preds_exist(preds)                          # BR-03
            self._assert_acyclic(act_no, preds)                      # BR-03（改链也要查环）
            self._assert_no_redundant(act_no, preds)                 # BR-02
            sets.append("predecessors = ?")
            args.append(",".join(preds) or None)
        wb = self._clean(wbs_no)
        if wb:
            sets.append("wbs_no = ?")
            args.append(self._need_leaf(wb))                         # BR-05
        ow = self._clean(owner)
        if ow:
            sets.append("owner = ?")
            args.append(ow)
        nt = self._clean(note)
        if nt:
            sets.append("note = ?")
            args.append(nt)
        if cn:
            sets.append("change_no = ?")
            args.append(cn)
        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(act_no)
        self.db.execute("UPDATE activity SET " + ", ".join(sets) + " WHERE act_no = ?",
                        tuple(args))
        return self.get(act_no)

    def link(self, act_no: str, predecessor_no: str):
        """给活动加一条前置（逻辑链，完成→开始）。

        三道闸：前置必须存在（BR-03）· 不得成环（BR-03）· 不得冗余（BR-02 —— 材料 §5.5.8
        举的就是"A→B、B→C 时再连 A→C"这个例子）。
        """
        cur = self._need(act_no)
        pid = self._clean(predecessor_no)
        if not pid:
            raise FdeError("前置活动编号不能为空（BR-03）")
        if pid == act_no:
            raise FdeError("活动不能以自己为前置（BR-03）")
        self._assert_preds_exist([pid])
        preds = self._norm(cur["predecessors"])
        if pid in preds:
            raise FdeError(f"{act_no} 已经有前置 {pid} 了")
        self._assert_no_redundant(act_no, preds + [pid])             # BR-02（传完整集合）
        self._assert_acyclic(act_no, preds + [pid])                  # BR-03
        if cur["baseline_start"]:
            # 连逻辑链同样改变时间相位 ⇒ 与改工期同款闸门（BR-07）
            raise FdeError(
                f"活动 {act_no} 已基线，改逻辑链必须先走变更流程（先 change 挂变更号，BR-07）")
        self.db.execute("UPDATE activity SET predecessors = ? WHERE act_no = ?",
                        (",".join(preds + [pid]), act_no))
        return self.get(act_no)

    def unlink(self, act_no: str, predecessor_no: str):
        """断掉一条前置。已基线的活动同样要走变更流程（BR-07）。"""
        cur = self._need(act_no)
        pid = self._clean(predecessor_no)
        preds = self._norm(cur["predecessors"])
        if pid not in preds:
            raise FdeError(f"{act_no} 没有前置 {pid}")
        if cur["baseline_start"]:
            raise FdeError(f"活动 {act_no} 已基线，改逻辑链必须先走变更流程（BR-07）")
        preds.remove(pid)
        self.db.execute("UPDATE activity SET predecessors = ? WHERE act_no = ?",
                        (",".join(preds) or None, act_no))
        return self.get(act_no)

    def check_network(self):
        """网络体检：返回四类**图论可判**的问题 + 一类跨应用问题。

        · `open_ends`   开口端（非边界活动入度或出度为 0）—— §5.5.8 的 no "open ends"
        · `redundant`   冗余链接（直接边被传递闭包覆盖）—— §5.5.8 原文的例子
        · `cycles`      环 —— 有环就没有可行执行序
        · `bad_duration` 工期异常（里程碑 ≠ 0 / 活动 ≤ 0）
        · `non_leaf`    挂靠的 WBS 元素**已不是叶子**（元素下面长了新子元素）—— 跨应用读 `wbs`
        """
        rows = self.list()["items"]
        idx = {r["act_no"]: r for r in rows}
        edges = {r["act_no"]: self._norm(r["predecessors"]) for r in rows}

        open_ends = []
        for no, r in idx.items():
            # ⚠ 边界里程碑的豁免是**单向**的：`start` 只免"缺前置"、`finish` 只免"缺后续"。
            #   写成"两个 phase 一起跳过"会让边界里程碑的另一个开口端也不报（实测被抓）。
            if not edges[no] and r["phase"] != "start":
                open_ends.append({"act_no": no, "name": r["name"], "missing": "前置"})
            if not any(no in v for v in edges.values()) and r["phase"] != "finish":
                open_ends.append({"act_no": no, "name": r["name"], "missing": "后续"})

        redundant = []
        for no, preds in edges.items():
            for p in preds:
                # 判据：**去掉这条直连边之后**，p 是否仍是 no 的祖先（即还存在长度 ≥2 的路径）
                # ⚠ 不这么写就会把"环"误报成"冗余"（两者是不同的问题，报告里要分开）
                sub = dict(edges)
                sub[no] = [q for q in preds if q != p]
                if p in self._ancestors(no, sub):
                    redundant.append({"act_no": no, "predecessor": p})

        cycles = self._find_cycles(edges)

        bad_duration = [{"act_no": r["act_no"], "kind": r["kind"],
                         "duration_days": r["duration_days"]}
                        for r in rows
                        if (r["kind"] == "milestone" and r["duration_days"] != 0)
                        or (r["kind"] == "activity" and r["duration_days"] <= 0)]

        non_leaf = []
        for no, r in idx.items():
            if self._wbs_children(r["wbs_no"]):
                non_leaf.append({"act_no": no, "wbs_no": r["wbs_no"]})

        problems = len(open_ends) + len(redundant) + len(cycles) + len(bad_duration) + len(non_leaf)
        return {"total": problems, "activities": len(rows), "open_ends": open_ends,
                "redundant": redundant, "cycles": cycles, "bad_duration": bad_duration,
                "non_leaf": non_leaf}

    def schedule_view(self, project_start: str = None):
        """**派生排程**：正推最早日期、逆推最晚日期、算浮时、标关键路径。

        材料 §5.5.9.3：日期由**逻辑与工期**决定，而不是为凑某个完成日填的 —— 所以日期
        不落库、在这里现算。工期按**工作日**顺推（不含节假日与资源日历，本版已知限制）。
        前置为空的活动（开口端）从 `project_start` 起算，`check_network` 会把它们报出来。
        """
        rows = self.list()["items"]
        idx = {r["act_no"]: r for r in rows}
        edges = {r["act_no"]: [p for p in self._norm(r["predecessors"]) if p in idx]
                 for r in rows}
        order = self._topo(edges)
        start = self._parse_date(project_start) or _dt.date.today()

        # 正推：ES = max(EF(前置)+1)；EF = ES + 工期 - 1（里程碑工期 0 ⇒ EF = ES）
        es, ef = {}, {}
        for no in order:
            es[no] = max((ef[p] + 1 for p in edges[no]), default=0)
            ef[no] = es[no] + max(idx[no]["duration_days"] - 1, 0)
        finish = max(ef.values(), default=0)

        # 逆推：LF = min(LS(后续)-1)；LS = LF - 工期 + 1
        succ = {no: [m for m, ps in edges.items() if no in ps] for no in idx}
        ls, lf = {}, {}
        for no in reversed(order):
            lf[no] = min((ls[s] - 1 for s in succ[no]), default=finish)
            ls[no] = lf[no] - max(idx[no]["duration_days"] - 1, 0)

        out = []
        for no in order:
            r = idx[no]
            total = ls[no] - es[no]
            out.append(dict(r, early_start=self._date_at(start, es[no]),
                            early_finish=self._date_at(start, ef[no]),
                            late_start=self._date_at(start, ls[no]),
                            late_finish=self._date_at(start, lf[no]),
                            float_days=total, critical=(total == 0)))
        return {"project_start": start.isoformat(),
                "project_finish": self._date_at(start, finish),
                "total_days": len([d for d in range(finish + 1)]),
                "items": out}

    def critical_path(self):
        """只取关键路径（浮时为 0 的活动，按最早开始排序）。"""
        view = self.schedule_view()
        crit = [x for x in view["items"] if x["critical"]]
        return {"project_start": view["project_start"], "project_finish": view["project_finish"],
                "items": crit, "total": len(crit)}

    def baseline(self, act_nos, project_start: str = None):
        """建立进度基线：把**派生日期**冻进 `baseline_start` / `baseline_finish`。

        材料 §7.3 允许两种粒度（整条 IMS / 只基线化关键里程碑子集）—— 这里传哪几个就基线哪几个。
        已基线的活动重跑会覆盖（= 变更落实后的重新冻基线）。
        """
        nos = self._as_list(act_nos)
        if not nos:
            raise FdeError("要基线哪些活动？请给出 act_no（材料允许只基线化关键里程碑子集，§7.3）")
        # ⚠ `project_start` 必须透传：不透传就按"今天"算，冻下来的基线与用户看到的排程不是同一个基准
        view = {x["act_no"]: x for x in self.schedule_view(project_start)["items"]}
        done = []
        for no in nos:
            cur = self._need(no)
            x = view.get(no)
            if not x:
                raise FdeError(f"活动 {no} 不在排程视图里（可能挂在环上）")
            self.db.execute(
                "UPDATE activity SET baseline_start = ?, baseline_finish = ? WHERE act_no = ?",
                (x["early_start"], x["early_finish"], no))
            done.append(self.get(cur["act_no"]))
        return {"baselined": len(done), "items": done}

    def change(self, act_no: str, change_no: str, note: str = None):
        """对已基线的活动发起修订：挂上**已批准**的变更号（跨应用只读校验 `change_request.get`）。

        材料 §7.3：进度基线的维护受项目的变更控制过程控制。挂上变更号之后才允许 `update`
        （BR-07）；**实绩照旧可以随时回填**（那不动基线，§7.3 末句）。
        """
        cur = self._need(act_no)
        cn = self._clean(change_no)
        if not cn:
            raise FdeError("发起修订必须给出已批准的变更请求号（BR-07，材料 §7.3）")
        if not cur["baseline_start"]:
            raise FdeError(f"活动 {act_no} 还没基线，直接改即可（不需要变更流程，BR-07）")
        cr = self.fde.call("change_request", "get", cr_no=cn)
        if not cr:
            raise FdeError(f"变更请求 {cn} 不存在（BR-07）")
        if cr.get("status") != "approved":
            raise FdeError(f"变更请求 {cn} 当前为「{cr.get('status')}」，尚未批准 —— "
                           "已基线的活动只能按已批准的变更修订（BR-07）")
        sets, args = ["change_no = ?"], [cn]
        nt = self._clean(note)
        if nt:
            sets.append("note = ?")
            args.append(nt)
        args.append(act_no)
        self.db.execute("UPDATE activity SET " + ", ".join(sets) + " WHERE act_no = ?",
                        tuple(args))
        return self.get(act_no)

    def record_progress(self, act_no: str, percent_complete: int = None,
                        actual_start: str = None, actual_finish: str = None, note: str = None):
        """回填实绩：实际开始 / 完成 / 完成百分比。

        ⚠ **写集合里没有基线列**（BR-08）—— 材料 §7.3 原话：「This procedure does not change any
        baseline data … but reports actuals and current performance **against** that baseline」。
        状态由百分比派生：0 且无实际开始 → `planned`；100 且有实际完成 → `completed`；其余 `in_progress`。
        """
        cur = self._need(act_no)
        sets, args = [], []
        pct = cur["percent_complete"]
        if percent_complete is not None:
            pct = max(0, min(100, int(percent_complete)))
            sets.append("percent_complete = ?")
            args.append(pct)
        a_s = self._clean(actual_start)
        a_f = self._clean(actual_finish)
        if a_s:
            self._parse_date(a_s) or self._bad_date("actual_start", a_s)
            sets.append("actual_start = ?")
            args.append(a_s)
        if a_f:
            self._parse_date(a_f) or self._bad_date("actual_finish", a_f)
            sets.append("actual_finish = ?")
            args.append(a_f)
        st = "completed" if (pct >= 100 and (a_f or cur["actual_finish"])) else (
            "in_progress" if (pct > 0 or a_s or cur["actual_start"]) else "planned")
        sets.append("status = ?")
        args.append(st)
        nt = self._clean(note)
        if nt:
            sets.append("note = ?")
            args.append(nt)
        args.append(act_no)
        self.db.execute("UPDATE activity SET " + ", ".join(sets) + " WHERE act_no = ?",
                        tuple(args))
        return self.get(act_no)

    # ── 私有（非服务） ────────────────────────────────────

    @staticmethod
    def _clean(v):
        return str(v).strip() if v is not None else ""

    @staticmethod
    def _norm(v):
        """前置列表规范化：去空、去重、保序。`v` 可为逗号分隔串或 list。"""
        if v is None:
            return []
        parts = v if isinstance(v, (list, tuple)) else str(v).split(",")
        out = []
        for x in parts:
            x = str(x).strip()
            if x and x not in out:
                out.append(x)
        return out

    @staticmethod
    def _as_list(v):
        return Activity._norm(v)

    def _next_no(self):
        n = 1
        for r in self.db.execute("SELECT act_no FROM activity"):
            s = str(r["act_no"])
            if s.startswith("ACT-") and s[4:].isdigit():
                n = max(n, int(s[4:]) + 1)
        return f"ACT-{n:03d}"

    def _rows(self):
        return self.list()["items"]

    def _check_kind(self, kind: str):
        if kind not in KINDS:
            raise FdeError(f"类型只能是 {'/'.join(KINDS)} 之一"
                           f"（{'/'.join(KIND_CN[k] for k in KINDS)}）")

    def _check_duration(self, kind: str, d):
        """BR-04：里程碑工期恒 0；活动工期必须 > 0。"""
        try:
            d = int(d)
        except (TypeError, ValueError):
            raise FdeError("工期必须是整数（按工作日计，§5.5.9）")
        if kind == "milestone" and d != 0:
            raise FdeError(f"里程碑的工期必须为 0（它是**事件**不是工作，§5.5.7.1）；收到 {d}")
        if kind == "activity" and d <= 0:
            raise FdeError(f"活动的工期必须大于 0（收到 {d}）")
        if d < 0:
            raise FdeError("工期不能为负")
        return d

    def _check_name_free(self, name: str, exclude: str = None):
        for r in self.db.execute("SELECT act_no, name FROM activity WHERE name = ?", (name,)):
            if exclude and r["act_no"] == exclude:
                continue
            raise FdeError(f"已存在同名活动「{name}」（{r['act_no']}）—— "
                           "活动与里程碑的描述必须唯一可区分（BR-06，§5.5.5）")

    def _need(self, act_no: str):
        cur = self.get(act_no)
        if not cur:
            raise FdeError(f"活动编号 {self._clean(act_no) or '（空）'} 不存在")
        return cur

    def _assert_preds_exist(self, preds):
        for p in preds:
            if not self.get(p):
                raise FdeError(f"前置活动 {p} 不存在（BR-03：逻辑链必须完整）")

    def _wbs_children(self, wbs_no):
        try:
            r = self.fde.call("wbs", "list", parent_no=wbs_no, page=1, size=1)
        except Exception as e:
            raise FdeError(f"挂靠校验失败：wbs 应用不可用（{str(e)[:60]}）")
        return (r or {}).get("items") or []

    def _need_leaf(self, wbs_no: str):
        """BR-05：挂靠的 WBS 元素必须存在**且是叶子**（跨应用只读）。"""
        wbs_no = self._clean(wbs_no)
        if not wbs_no:
            raise FdeError("必须挂在某个 WBS 元素上（BR-05）")
        try:
            el = self.fde.call("wbs", "get", wbs_no=wbs_no)
        except Exception as e:
            raise FdeError(f"挂靠校验失败：wbs 应用不可用（{str(e)[:60]}）")
        if not el:
            raise FdeError(f"WBS 元素 {wbs_no} 不存在，请先在 WBS 台账里登记（BR-05）")
        kids = self._wbs_children(wbs_no)
        if kids:
            raise FdeError(
                f"WBS 元素 {wbs_no} 下面还有 {len(kids)} 个子元素 —— 活动只能挂在**最底层元素**上"
                f"（BR-05，材料 §4.3）；请挂到它的子元素上")
        return wbs_no

    def _edges(self, override=None, override_preds=None):
        """全表的前置边表；`override`/`override_preds` 用于"假设改成这样"的校验。"""
        edges = {r["act_no"]: self._norm(r["predecessors"]) for r in self._rows()}
        if override:
            edges[override] = list(override_preds or [])
        return edges

    @staticmethod
    def _ancestors(act_no, edges):
        """`act_no` 的全部祖先（前置的传递闭包）。

        ⚠ 别加"跳过某个节点"的参数：冗余判据恰恰要靠**那个节点出现在祖先集里**才算成立 ——
          早先写成 `skip_direct=p` 把它跳掉，冗余链接就永远拦不住了（实测被抓）。
        """
        seen, stack = set(), list(edges.get(act_no, []))
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(edges.get(x, []))
        return seen

    def _assert_no_redundant(self, act_no, preds):
        """BR-02：**前置集合里若有一条已被别的路径蕴含**，就是冗余链接。

        判据（一条式子覆盖两种入口）：
            p 冗余 ⟺ 集合里存在另一个 q，使得 **p 是 q 的祖先**（p → … → q）

        · 连边（link）：A→B、B→C 之后连 A→C —— 集合是 [B, A]，A 是 B 的祖先 ⇒ 冗余
          （材料 §5.5.8 原文举的就是这个例子）
        · 建活动（create）：一次性塞 [A, B] 而 A→B 已存在 —— 同上 ⇒ 冗余
        ⚠ 早先只按"新节点的祖先集"判，`create` 时新节点还不在图里 ⇒ 祖先集恒空、
          这条闸形同虚设（实测被抓）。
        """
        edges = {r["act_no"]: self._norm(r["predecessors"]) for r in self._rows()}
        for p in preds:
            for q in preds:
                if q == p:
                    continue
                if p in self._ancestors(q, edges):
                    raise FdeError(
                        f"{p} → {self._clean(act_no) or '（新活动）'} 是**冗余链接**："
                        f"{p} 已经通过 {q} 间接前置了它（BR-02，材料 §5.5.8 的例子："
                        "A→B、B→C 时 A→C 冗余）")

    def _pre_existing(self, act_no):
        cur = self.get(act_no)
        return cur["predecessors"] if cur else None

    def _assert_acyclic(self, act_no, preds):
        """BR-03：把 `act_no` 的前置设为 `preds` 后，网络不得成环。"""
        edges = self._edges(act_no, preds)
        if self._find_cycles(edges):
            raise FdeError(f"这条前置关系会让逻辑链成环（BR-03）：{self._find_cycles(edges)[:1]}")

    @staticmethod
    def _find_cycles(edges):
        WHITE, GREY, BLACK = 0, 1, 2
        color = dict.fromkeys(edges, WHITE)
        cycles = []

        def dfs(u, path):
            color[u] = GREY
            for v in edges.get(u, []):
                if v not in color:
                    continue
                if color[v] == GREY:
                    cycles.append(path + [u, v])
                elif color[v] == WHITE:
                    dfs(v, path + [u])
            color[u] = BLACK

        for n in list(edges):
            if color[n] == WHITE:
                dfs(n, [])
        return cycles

    @staticmethod
    def _topo(edges):
        """拓扑排序（Kahn）。有环时把剩下的按编号兜底拼上（体检会报环）。"""
        indeg = {n: 0 for n in edges}
        for n, ps in edges.items():
            for p in ps:
                if p in indeg:
                    indeg[n] += 1
        q = sorted([n for n, d in indeg.items() if d == 0])
        out = []
        while q:
            u = q.pop(0)
            out.append(u)
            for v, ps in edges.items():
                if u in ps:
                    indeg[v] -= 1
                    if indeg[v] == 0:
                        q.append(v)
                        q.sort()
        rest = [n for n in sorted(edges) if n not in out]
        return out + rest

    @staticmethod
    def _parse_date(s):
        s = (s or "").strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return _dt.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _bad_date(field, val):
        raise FdeError(f"{field} 不是合法日期（用 YYYY-MM-DD）：{val}")

    @staticmethod
    def _date_at(start: _dt.date, offset: int):
        """从 `start` 起按**工作日**顺推 `offset` 天（不含节假日，本版已知限制）。"""
        d, n = start, offset
        while n > 0:
            d += _dt.timedelta(days=1)
            if d.weekday() < 5:
                n -= 1
        while d.weekday() >= 5:            # 起点落在周末就顺延到下一个工作日
            d += _dt.timedelta(days=1)
        return d.isoformat()
