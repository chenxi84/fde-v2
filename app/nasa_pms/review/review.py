from __future__ import annotations

import re

from fde import FdeError

# 评审类型字典（术语表已收 MCR/SRR/SDR/PDR/CDR/TRR/PRR/SIR 八种；
# ORR/FRR/SAR 取自材料附录 A 缩略语表与 §6.7 TABLE 6.7-1 的生命周期评审清单 —— 本步回填）
REVIEW_TYPES = ("mcr", "srr", "sdr", "pdr", "cdr", "sir", "trr", "prr", "orr", "frr", "sar")
# 阶段字典：术语表的 Pre-Phase A / Phase A..E（阶段在本聚合里是**枚举属性**，不独立成聚合）
PHASES = ("pre_a", "a", "b", "c", "d", "e")
# 评审结论：材料 §6.7.1.2.2 的 success criteria 判定结果；「有条件通过」即卡片 I-1 的「通过（有条件）」
CONCLUSIONS = ("pass", "conditional", "fail")
# 行动项状态（聚合内子表，无独立标识）
ACTION_OPEN = "open"
ACTION_DONE = "done"
# 硬终态：到达后一律拒（BR-06 后半）；已结论后的两个状态是「内容冻结」而非终态（BR-06 前半）
_TERMINAL = "closed"
_FROZEN = ("concluded", "tracking")
_STATUS_CN = {"planned": "计划", "in_progress": "进行中", "concluded": "已结论",
              "tracking": "行动项跟踪中", "closed": "已关闭"}
_CONCLUSION_CN = {"pass": "通过", "conditional": "有条件通过", "fail": "不通过"}
# 主档字段清单 —— `get` 与 `list` **共用同一份**，杜绝两处口径漂移（CONVENTION §7）
_MAIN_COLS = ("review_no, title, review_type, phase, subject, plan_no, status,"
              " conclusion, minutes, close_note, owner, project_no")


class Review:
    """评审聚合根。一次技术评审，含评审项清单、结论与行动项。数据来源类型：独立创建。

    一致性边界（见 `architecture.md` 聚合根卡 5）：
      · **行动项并入本聚合**（卡片「并入说明」）—— 它随 `conclude` 与结论**同事务**落库，
        没有独立标识（`(review_no, seq)` 复合主键，seq 只在评审内唯一）；
        跨评审的「行动项汇总」由 `list_actions` 这个**查询视图**提供，不是独立聚合。
      · **评审项清单**同属聚合内（`add_item`），结论前必须逐项对应；
      · **结论是快照**：`conclude` 之后主档内容与评审项清单一起冻结（BR-06），
        评审项与行动项的后续变化只发生在「行动项跟踪中」这一个状态内。
      · 评审依据的计划（`plan_no`）是**弱引用**（可留空、可悬空）——本版按文本处理，
        **不做跨应用校验**（前端只拿 `tech_plan.list` 当候选建议，不动存的是文本；见详设 §6.3）。

    业务规则落点：BR-01 有条件通过须有行动项 / BR-02 行动项须有责任人与期限 /
                 BR-03 评审项清单为空不得结论 / BR-04 编号唯一且不可变 /
                 BR-05 类型·阶段·结论受字典约束 / BR-06 已结论冻结·已关闭终态 /
                 BR-07 行动项未清零不得关闭评审。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, title: str, review_type: str, phase: str, subject: str,
               plan_no: str = None, owner: str = None, project_no: str = None):
        """新建一次评审，落库为「计划」状态，编号自动生成（`RV-001` 起）。

        四个必填项逐个校验非空：标题 / 评审类型 / 阶段 / 评审对象 —— 类型、阶段还要过字典（BR-05）。
        `plan_no`（评审依据的计划）为弱引用，选填文本。
        """
        title = self._clean(title)
        subject = self._clean(subject)
        review_type = self._clean(review_type)
        phase = self._clean(phase)
        if not title:
            raise FdeError("评审标题不能为空")
        if not subject:
            raise FdeError("评审对象不能为空")
        self._check_type(review_type)                              # BR-05
        self._check_phase(phase)                                   # BR-05

        review_no = self._next_no()
        self.db.execute(
            "INSERT INTO review (review_no, title, review_type, phase, subject,"
            " plan_no, status, owner, project_no)"
            " VALUES (?, ?, ?, ?, ?, ?, 'planned', ?, ?)",
            (review_no, title, review_type, phase, subject, self._clean(plan_no),
             self._clean(owner), self._clean(project_no)),
        )
        return self.get(review_no)

    def add_item(self, review_no: str, item: str, criterion: str = None):
        """往评审项清单里加一条评审项（计划 / 进行中都可加，已结论后冻结，BR-06）。

        评审项是「本次评审要逐项判的东西」——材料 §6.7.1.2.2 把 "establishing each review's
        purpose, objective, and entry and success criteria" 列为评审的必备动作；
        `criterion` 即该项的判据（选填）。
        """
        cur = self._need(review_no)
        self._check_frozen(cur)                                    # BR-06
        item = self._clean(item)
        if not item:
            raise FdeError("评审项内容不能为空")

        seq = self._next_seq("review_item", review_no)
        self.db.execute(
            "INSERT INTO review_item (review_no, seq, item, criterion) VALUES (?, ?, ?, ?)",
            (review_no, seq, item, self._clean(criterion)),
        )
        return self.get(review_no)

    def start(self, review_no: str):
        """启动评审：计划 → 进行中（`planned → in_progress`）。

        评审「开起来」的标志 —— 材料 §6.7.1.2.2 的 "(1) identifying, planning, and conducting
        phase-to-phase technical reviews"：先有计划，再有执行，故 `create` 后不能直接出结论。
        """
        cur = self._need(review_no)
        # 守卫顺序 = 安全边界：硬终态排最前（否则 archived 类状态能被后续分支绕过）
        if cur["status"] == _TERMINAL:
            raise FdeError(f"评审 {review_no} 已关闭（终态），不能再启动")
        if cur["status"] == "in_progress":
            raise FdeError(f"评审 {review_no} 已经处于进行中")
        if cur["status"] != "planned":
            raise FdeError(
                f"评审 {review_no} 当前为「{self._status_cn(cur['status'])}」，只有计划状态才能启动")
        self.db.execute("UPDATE review SET status = 'in_progress' WHERE review_no = ?", (review_no,))
        return self.get(review_no)

    def conclude(self, review_no: str, conclusion: str, minutes: str = None, actions=None):
        """出结论：进行中 → 已结论 / 行动项跟踪中（`in_progress → concluded | tracking`）。

        这是本聚合**唯一**写结论的入口（BR-06），也是行动项的**唯一**产生点 ——
        行动项与结论**同事务**落库（卡片「并入说明」），要么一起成功、要么一起失败。

        三条不变量同时落在这里：
          · **BR-03** 评审项清单为空**不得结论** —— 结论必须逐项对应评审项；
          · **BR-01** 结论为「有条件通过」时**必须有行动项**（卡片 I-1）；
          · **BR-02** 每条行动项必须指定**责任人与期限**（卡片 I-2）。

        状态落点：带行动项 → 「行动项跟踪中」；无行动项 → 「已结论」（结论为「通过」且无需整改）。
        """
        cur = self._need(review_no)
        if cur["status"] == _TERMINAL:
            raise FdeError(f"评审 {review_no} 已关闭（终态），不能再出结论")
        if cur["status"] in _FROZEN:
            raise FdeError(
                f"评审 {review_no} 已经出过结论（{self._conclusion_cn(cur['conclusion'])}），不能重复结论")
        if cur["status"] != "in_progress":
            raise FdeError(f"评审 {review_no} 当前为「计划」，须先启动评审（start）再出结论")

        conclusion = self._clean(conclusion)
        if not conclusion:
            raise FdeError(f"评审结论不能为空：只能是 {'/'.join(CONCLUSIONS)} 之一（BR-05）")
        if conclusion not in CONCLUSIONS:                          # BR-05
            raise FdeError(f"评审结论只能是 {'/'.join(CONCLUSIONS)} 之一（BR-05）")
        if not cur["items"]:                                       # BR-03
            raise FdeError(f"评审 {review_no} 的评审项清单为空，不能出结论（BR-03）")

        rows = self._clean_actions(actions)                        # BR-02（逐条校验）
        if conclusion == "conditional" and not rows:               # BR-01（卡片 I-1）
            raise FdeError("评审结论为「有条件通过」时必须给出行动项（BR-01）")

        for a in rows:
            seq = self._next_seq("review_action", review_no)
            self.db.execute(
                "INSERT INTO review_action (review_no, seq, content, owner, due_date, status)"
                " VALUES (?, ?, ?, ?, ?, 'open')",
                (review_no, seq, a["content"], a["owner"], a["due_date"]),
            )
        status = "tracking" if rows else "concluded"
        self.db.execute(
            "UPDATE review SET status = ?, conclusion = ?, minutes = ? WHERE review_no = ?",
            (status, conclusion, self._clean(minutes), review_no),
        )
        return self.get(review_no)

    def close_action(self, review_no: str, seq, note: str = None):
        """完成一条行动项：未完成 → 已完成（`open → done`）。

        材料 §6.7.1.2.2 的第 (4) 条是 "identifying and **resolving** action items" ——
        行动项要能被"了结"，否则评审永远收不了尾（BR-07 靠它清零）。
        """
        cur = self._need(review_no)
        if cur["status"] == _TERMINAL:
            raise FdeError(f"评审 {review_no} 已关闭（终态），不能再动它的行动项")
        if cur["status"] != "tracking":
            raise FdeError(
                f"评审 {review_no} 当前为「{self._status_cn(cur['status'])}」，不在行动项跟踪中")
        s = self._int(seq, "行动项序号")
        target = [a for a in cur["actions"] if int(a["seq"]) == s]
        if not target:
            raise FdeError(f"评审 {review_no} 没有序号为 {s} 的行动项")
        if target[0]["status"] != ACTION_OPEN:
            raise FdeError(f"评审 {review_no} 的第 {s} 条行动项已经是完成状态")

        self.db.execute(
            "UPDATE review_action SET status = 'done', close_note = ?"
            " WHERE review_no = ? AND seq = ?",
            (self._clean(note), review_no, s),
        )
        return self.get(review_no)

    def close(self, review_no: str, note: str = None):
        """关闭评审：已结论 / 行动项跟踪中 → 已关闭（`→ closed`，硬终态）。

        关闸条件是 **BR-07：行动项必须全部完成** —— 只要有未了结的行动项，
        评审就不算收尾（材料 TABLE 6.7-1 的 "Results of Review" 一列把"问题已处置"当作
        评审成功的结果之一）。计划 / 进行中的评审**不能跳过结论**直接关闭。
        """
        cur = self._need(review_no)
        if cur["status"] == _TERMINAL:
            raise FdeError(f"评审 {review_no} 已经是关闭状态")
        if cur["status"] not in _FROZEN:
            raise FdeError(
                f"评审 {review_no} 当前为「{self._status_cn(cur['status'])}」，"
                "只有已结论或行动项跟踪中的评审才能关闭（须先出结论）")
        if cur["action_open"]:                                     # BR-07
            raise FdeError(
                f"评审 {review_no} 还有 {cur['action_open']} 条行动项未完成，不能关闭评审（BR-07）")

        self.db.execute(
            "UPDATE review SET status = 'closed', close_note = ? WHERE review_no = ?",
            (self._clean(note), review_no),
        )
        return self.get(review_no)

    def update(self, review_no: str, title: str = None, review_type: str = None,
               phase: str = None, subject: str = None, plan_no: str = None, owner: str = None):
        """修改评审的描述性内容（标题 / 类型 / 阶段 / 评审对象 / 依据计划 / 责任人）。

        **结论与纪要不在字段白名单里**：结论只能经 `conclude` 写入（BR-06），
        编号落库不可变（BR-04）—— 没有参数可传，也就无从改起。
        已结论（`concluded` / `tracking`）后内容冻结、已关闭为终态，两者都拒绝（BR-06）。
        """
        cur = self._need(review_no)
        self._check_frozen(cur)                                    # BR-06

        sets, args = [], []
        if title is not None:
            title = self._clean(title)
            if not title:
                raise FdeError("评审标题不能为空")
            sets.append("title = ?")
            args.append(title)
        if review_type is not None:
            review_type = self._clean(review_type)
            self._check_type(review_type)                          # BR-05
            sets.append("review_type = ?")
            args.append(review_type)
        if phase is not None:
            phase = self._clean(phase)
            self._check_phase(phase)                               # BR-05
            sets.append("phase = ?")
            args.append(phase)
        if subject is not None:
            subject = self._clean(subject)
            if not subject:
                raise FdeError("评审对象不能为空")
            sets.append("subject = ?")
            args.append(subject)
        if plan_no is not None:
            sets.append("plan_no = ?")
            args.append(self._clean(plan_no))
        if owner is not None:
            sets.append("owner = ?")
            args.append(self._clean(owner))
        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(review_no)
        self.db.execute("UPDATE review SET " + ", ".join(sets) + " WHERE review_no = ?",
                        tuple(args))
        return self.get(review_no)

    def get(self, review_no: str):
        """按评审编号查询（含评审项清单 `items` 与行动项清单 `actions`）；未命中返回 None，不抛异常。

        行动项计数 `action_total` / `action_open` 与 `list` 同口径（前端"行动项 x/y"与
        "能否关闭"都读它）。
        """
        review_no = self._clean(review_no)
        if not review_no:
            return None
        row = self.db.execute(
            "SELECT " + _MAIN_COLS + " FROM review WHERE review_no = ?", (review_no,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["items"] = [dict(r) for r in self.db.execute(
            "SELECT seq, item, criterion FROM review_item WHERE review_no = ? ORDER BY seq",
            (review_no,)).fetchall()]
        out["actions"] = [dict(r) for r in self.db.execute(
            "SELECT seq, content, owner, due_date, status, close_note FROM review_action"
            " WHERE review_no = ? ORDER BY seq", (review_no,)).fetchall()]
        out.update(self._counts(out["actions"]))
        return out

    def list(self, review_type: str = None, phase: str = None, status: str = None,
             conclusion: str = None, plan_no: str = None, page: int = None, size: int = None):
        """按类型 / 阶段 / 状态 / 结论 / 依据计划筛选，**分页返回 `{items, total}`**，默认按编号升序。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（见 VIEW_CONVENTION）——
        少了它们，前端拿到的 `items` 恒为空、页面静默显示空态而**不报错**（同组实测踩过）。
        返回项与 `get` 同字段口径（`_MAIN_COLS` 共用 + 同一份行动项计数）；
        评审项 / 行动项**明细只在 `get`**（列表不需要 N+1 取子表）。
        """
        where, args = [], []
        for col, val in (("review_type", review_type), ("phase", phase), ("status", status),
                         ("conclusion", conclusion), ("plan_no", plan_no)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = "SELECT " + _MAIN_COLS + " FROM review"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY review_no"
        rows = []
        for r in self.db.execute(sql, tuple(args)).fetchall():
            d = dict(r)
            d.update(self._counts_by_no(d["review_no"]))
            rows.append(d)

        total = len(rows)
        if size:
            p = max(int(page or 1), 1)
            n = max(int(size), 1)
            rows = rows[(p - 1) * n: p * n]
        return {"items": rows, "total": total}

    def list_actions(self, review_no: str = None, owner: str = None, status: str = None,
                     page: int = None, size: int = None):
        """**跨评审的行动项汇总**（卡片「并入说明」明确它是**查询视图**，不是独立聚合）。

        汇总行把所属评审的类型 / 阶段 / 标题一并带出（前端"行动项看板"一屏看全），
        并按 `{items, total}` 分页 —— 与 `list` 同一契约口径。
        """
        where, args = [], []
        for col, val in (("a.review_no", review_no), ("a.owner", owner), ("a.status", status)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = ("SELECT a.review_no, a.seq, a.content, a.owner, a.due_date, a.status, a.close_note,"
               " r.review_type, r.phase, r.title AS review_title"
               " FROM review_action a JOIN review r ON r.review_no = a.review_no")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY a.review_no, a.seq"
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
    def _check_type(review_type: str):
        if not review_type:
            raise FdeError("评审类型不能为空")
        if review_type not in REVIEW_TYPES:
            raise FdeError(f"评审类型只能是 {'/'.join(REVIEW_TYPES)} 之一（BR-05）")

    @staticmethod
    def _check_phase(phase: str):
        if not phase:
            raise FdeError("所属阶段不能为空")
        if phase not in PHASES:
            raise FdeError(f"所属阶段只能是 {'/'.join(PHASES)} 之一（BR-05）")

    @staticmethod
    def _status_cn(status: str) -> str:
        return _STATUS_CN.get(status, status or "—")

    @staticmethod
    def _conclusion_cn(conclusion: str) -> str:
        return _CONCLUSION_CN.get(conclusion, conclusion or "—")

    @staticmethod
    def _check_frozen(cur: dict):
        """已关闭为硬终态、已结论后内容冻结 —— 两者都不许再改主档或评审项（BR-06）。"""
        if cur["status"] == _TERMINAL:
            raise FdeError(f"评审 {cur['review_no']} 已关闭（终态），不能再修改（BR-06）")
        if cur["status"] in _FROZEN:
            raise FdeError(
                f"评审 {cur['review_no']} 已出结论（结论是快照），不能再修改内容或增删评审项（BR-06）")

    def _clean_actions(self, actions) -> list:
        """把行动项入参规整为 `[{content, owner, due_date}]`，逐条校验非空与期限格式（BR-02）。

        卡片 I-2「行动项必须指定责任人与期限」在这里落成三次非空校验 + 一次格式校验；
        期限上界不校验（材料没有给口径），只保证是可排序的 `YYYY-MM-DD`。
        """
        if actions is None:
            return []
        if not isinstance(actions, (list, tuple)):
            raise FdeError("行动项必须是一个列表")
        out = []
        for i, a in enumerate(actions, 1):
            if not isinstance(a, dict):
                raise FdeError(f"第 {i} 条行动项的格式不正确（应为对象）")
            content = self._clean(a.get("content"))
            owner = self._clean(a.get("owner"))
            due = self._clean(a.get("due_date"))
            if not content:
                raise FdeError(f"第 {i} 条行动项的内容不能为空")
            if not owner:
                raise FdeError(f"第 {i} 条行动项必须指定责任人（BR-02）")
            if not due:
                raise FdeError(f"第 {i} 条行动项必须指定期限（BR-02）")
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
                raise FdeError(f"第 {i} 条行动项的期限格式必须是 YYYY-MM-DD（BR-02）")
            out.append({"content": content, "owner": owner, "due_date": due})
        return out

    def _counts(self, actions: list):
        """由行动项清单推导 `{action_total, action_open}` —— `get` 与 `list` 共用同一算法。"""
        return {"action_total": len(actions),
                "action_open": sum(1 for a in actions if a["status"] == ACTION_OPEN)}

    def _counts_by_no(self, review_no: str):
        row = self.db.execute(
            "SELECT COUNT(*) AS total,"
            " SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_n"
            " FROM review_action WHERE review_no = ?", (review_no,),
        ).fetchone()
        return {"action_total": int(row["total"] or 0), "action_open": int(row["open_n"] or 0)}

    def _need(self, review_no: str):
        review_no = self._clean(review_no)
        if not review_no:
            raise FdeError("评审编号不能为空")
        cur = self.get(review_no)
        if not cur:
            raise FdeError(f"评审 {review_no} 不存在")
        return cur

    def _next_no(self) -> str:
        """生成下一个评审编号：RV-<三位序号>（BR-04：编号唯一且不可变）。"""
        rows = self.db.execute("SELECT review_no FROM review").fetchall()
        mx = 0
        for r in rows:
            m = re.match(r"^RV-(\d+)$", str(r["review_no"]))
            if m:
                mx = max(mx, int(m.group(1)))
        return f"RV-{mx + 1:03d}"

    def _next_seq(self, table: str, review_no: str) -> int:
        """聚合内子表的序号：本评审内递增（`(review_no, seq)` 是复合主键，无全局标识）。"""
        rows = self.db.execute(
            f"SELECT seq FROM {table} WHERE review_no = ?", (review_no,)).fetchall()
        mx = 0
        for r in rows:
            mx = max(mx, int(r["seq"]))
        return mx + 1
