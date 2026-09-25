from __future__ import annotations

import re

from fde import FdeError

# 验证方法 —— 材料 §5.3.1.2「METHODS OF VERIFICATION」的四种，与 requirement.METHODS 同字典
METHODS = ("inspection", "analysis", "demonstration", "test")
# 验证阶段 —— 材料附录 D TABLE D-1 的「Phases」列（1..8），即验证发生在哪个执行序列位置
PHASES = ("pre_development", "box_functional", "box_environmental", "system_environmental",
          "system_functional", "end_to_end", "integrated_vehicle", "on_orbit")
# 判定结果 —— 验证矩阵一行的结论（材料 TABLE D-1 的 Result 列）
RESULTS = ("pass", "fail")
# 终态：关闭之后一律不得再改（BR-03）
_TERMINAL = ("closed",)
# 已判定：验证方法与验证阶段是判定的事实前提，判定后不得改写（BR-03）
_DECIDED = ("passed", "failed")
_STATUS_CN = {"planned": "规划", "executing": "执行中", "passed": "通过",
              "failed": "不通过", "closed": "关闭"}
_RESULT_CN = {"pass": "通过", "fail": "不通过"}


class Verification:
    """验证项聚合根。验证矩阵的一行（需求 × 验证方法 × 结果）。

    数据来源类型：**跨应用派生** —— 一行验证项由一条已存在的需求派生而来，
    需求是它的**强关联**上游（与 `risk` 的受影响需求这种"弱引用、可留空"截然不同）。

    一致性边界（见 `architecture.md` 聚合根卡 6）：
      · **验证项必须挂在一条需求上** —— `req_no` 是必填入参且写入时经
        `requirement.get` 校验存在（BR-01，跨应用只读、非同一事务）；
        它**不在 `update` 的字段白名单里**：换需求等于换矩阵的一行，应另建验证项；
      · **判定与其证据同事务落库** —— 判定为「不通过」时后续处置也必须在同一次调用里给出
        （BR-02），不允许出现"已判定、无证据"的空洞行；
      · **验证的执行节奏与需求基线不同** —— 需求基线一次、验证多轮，故二者分属两个聚合
        （架构 §④ 决策 6）；本聚合不复制需求内容，也不回写需求状态。

    业务规则落点：BR-01 必须挂需求且需求须存在 / BR-02 判定须有证据、不通过须有后续处置 /
                 BR-03 判定不可重复且关单为终态 / BR-04 编号唯一不可变 /
                 BR-05 方法 / 阶段受字典约束 / BR-06 状态机守卫。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def create(self, req_no: str, method: str, phase: str,
               criteria: str = None, owner: str = None, project_no: str = None):
        """规划一条验证项（验证矩阵的一行），落库为「规划」状态。

        `req_no` **必填**（BR-01）：验证项是"对某条需求的验证"，没有需求就没有矩阵行；
        且该需求必须真实存在 —— 经 `requirement.get` 跨应用校验（目标应用已建成）。
        """
        req_no = self._clean(req_no)
        method = self._clean(method)
        phase = self._clean(phase)
        if not req_no:
            raise FdeError("对应需求不能为空：验证项必须挂在一条需求上（BR-01）")
        self._assert_requirement_exists(req_no)                 # BR-01（跨应用）
        self._check_method(method)                              # BR-05
        self._check_phase(phase)                                # BR-05

        ver_no = self._next_no()
        self.db.execute(
            "INSERT INTO verification (ver_no, req_no, method, phase, status,"
            " criteria, owner, project_no)"
            " VALUES (?, ?, ?, ?, 'planned', ?, ?, ?)",
            (ver_no, req_no, method, phase, self._clean(criteria),
             self._clean(owner), self._clean(project_no)),
        )
        return self.get(ver_no)

    def start(self, ver_no: str, owner: str = None):
        """开始执行：规划 → 执行中（`planned → executing`）。

        只有**规划**状态能开始执行 —— 已判定的验证项再"开始执行"意味着推翻已有结论，
        而验证结论是矩阵的对外输出（材料附录 D：每行都要有 Result），不能原地抹掉。
        """
        cur = self._need(ver_no)
        if cur["status"] == "executing":
            raise FdeError(f"验证项 {ver_no} 已在执行中")
        if cur["status"] != "planned":
            raise FdeError(
                f"验证项 {ver_no} 当前为「{self._status_cn(cur['status'])}」，"
                "只有规划状态才能开始执行（BR-06）")
        sets, args = ["status = 'executing'"], []
        owner = self._clean(owner)
        if owner:
            sets.append("owner = ?")
            args.append(owner)
        args.append(ver_no)
        self.db.execute("UPDATE verification SET " + ", ".join(sets) + " WHERE ver_no = ?",
                        tuple(args))
        return self.get(ver_no)

    def record_result(self, ver_no: str, result: str, evidence: str, follow_up: str = None):
        """记录判定结果：执行中 → 通过 / 不通过。

        三条不变量落在本服务上：
          · **只有执行中的验证项能判定**（BR-06）—— 没执行就判等于凭空下结论；
          · **判定必须有证据**（BR-02）—— 材料 TABLE D-1 的「Results Indicator」是
            "the report/document that contains the evidence that the requirement was satisfied"，
            没有证据的判定不是判定；
          · **判定为「不通过」必须同时记录后续处置**（BR-02，聚合根卡 6 的 I-2）——
            材料 §5.3.1.2.3 要求分析验证结果时给出 nonconformance 的 disposition
            与 planned retest，处置与判定同事务落库，不允许"先判后议"。
        """
        cur = self._need(ver_no)
        self._check_mutable(cur)                                # BR-03 终态
        if cur["status"] in _DECIDED:
            raise FdeError(
                f"验证项 {ver_no} 已判定为「{self._result_cn(cur['result'])}」，"
                "不能重复判定（需重新验证请另建验证项，BR-03）")
        if cur["status"] != "executing":
            raise FdeError(
                f"验证项 {ver_no} 当前为「{self._status_cn(cur['status'])}」，"
                "请先开始执行再记录判定（BR-06）")
        result = self._clean(result)
        if result not in RESULTS:
            raise FdeError(f"判定结果只能是 {'/'.join(RESULTS)} 之一"
                           "（pass = 通过 / fail = 不通过，BR-05）")
        evidence = self._clean(evidence)
        if not evidence:
            raise FdeError(f"验证项 {ver_no} 的判定必须有证据：请填写验证数据或报告出处（BR-02）")
        follow_up = self._clean(follow_up)
        if result == "fail" and not follow_up:
            raise FdeError(
                f"验证项 {ver_no} 判定为「不通过」，必须同时记录后续处置"
                "（整改 / 复验 / 豁免，BR-02）")

        status = "passed" if result == "pass" else "failed"
        self.db.execute(
            "UPDATE verification SET status = ?, result = ?, evidence = ?, follow_up = ?"
            " WHERE ver_no = ?", (status, result, evidence, follow_up, ver_no))
        return self.get(ver_no)

    def close(self, ver_no: str, note: str = None):
        """关闭验证项：**已判定**（通过 / 不通过）→ 关闭（终态）。

        只有已判定的验证项能关闭 —— 关闭是给判定收尾；规划中 / 执行中就关闭，会让验证矩阵里
        出现"有行无结论"的空洞（材料附录 D 的矩阵每行都要有 Result）。
        关闭后**不删除**：矩阵是交付物，记录必须留存且不可再改。
        `note` **落库**到 `close_note`（2026-09-25 起留痕；与 `risk.close` / `review.close` 同口径）。
        """
        cur = self._need(ver_no)
        if cur["status"] == "closed":
            raise FdeError(f"验证项 {ver_no} 已经是关闭状态")
        if cur["status"] not in _DECIDED:
            raise FdeError(
                f"验证项 {ver_no} 当前为「{self._status_cn(cur['status'])}」，"
                "只有已判定的验证项才能关闭（BR-06）")
        self.db.execute("UPDATE verification SET status = 'closed', close_note = ? WHERE ver_no = ?",
                        (self._clean(note) or None, ver_no))
        return self.get(ver_no)

    def update(self, ver_no: str, method: str = None, phase: str = None,
               criteria: str = None, owner: str = None):
        """修改验证项的规划信息（验证方法 / 验证阶段 / 成功判据 / 责任人）。

        ⚠ **`req_no` 不在字段白名单里**（BR-01）—— 与需求的挂接是这一行的身份，
        换需求等于换一行，应另建验证项；**`status` / `result` / `evidence` 同理**：
        它们只能经 `start` / `record_result` / `close` 流转（BR-06）。

        已关闭（`closed`）是终态，任何修改都拒绝（BR-03）；
        已判定（`passed` / `failed`）时**不得改写验证方法与验证阶段**（BR-03）——
        二者是判定的事实前提，判定后改写等于篡改记录（成功判据与责任人仍可补充）。
        """
        cur = self._need(ver_no)
        self._check_mutable(cur)                                # BR-03 终态
        if cur["status"] in _DECIDED and (method is not None or phase is not None):
            raise FdeError(
                f"验证项 {ver_no} 已判定为「{self._result_cn(cur['result'])}」，"
                "不能改写验证方法与验证阶段（BR-03）")

        sets, args = [], []
        if method is not None:
            method = self._clean(method)
            self._check_method(method)                          # BR-05
            sets.append("method = ?")
            args.append(method)
        if phase is not None:
            phase = self._clean(phase)
            self._check_phase(phase)                            # BR-05
            sets.append("phase = ?")
            args.append(phase)
        if criteria is not None:
            sets.append("criteria = ?")
            args.append(self._clean(criteria))
        if owner is not None:
            sets.append("owner = ?")
            args.append(self._clean(owner))
        if not sets:
            raise FdeError("没有要修改的内容")
        args.append(ver_no)
        self.db.execute("UPDATE verification SET " + ", ".join(sets) + " WHERE ver_no = ?",
                        tuple(args))
        return self.get(ver_no)

    def get(self, ver_no: str):
        """按验证项编号查询；未命中返回 None，不抛异常。"""
        ver_no = self._clean(ver_no)
        if not ver_no:
            return None
        row = self.db.execute(
            "SELECT ver_no, req_no, method, phase, status, result, evidence, follow_up, close_note,"
            " criteria, owner, project_no"
            " FROM verification WHERE ver_no = ?", (ver_no,),
        ).fetchone()
        return dict(row) if row else None

    def list(self, req_no: str = None, method: str = None, status: str = None,
             phase: str = None, page: int = None, size: int = None):
        """按对应需求 / 验证方法 / 状态 / 验证阶段筛选，**分页返回 `{items, total}`**，默认按编号升序。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（见 VIEW_CONVENTION）——
        少了它们，前端拿到的 `items` 恒为空、页面静默显示空态而**不报错**（同组实测踩过：
        后端返回裸数组时，页面显示「暂无数据」却 0 error）。
        返回项与 `get` 同口径（全字段），列表只显示关键列是**视图层**的事。
        """
        where, args = [], []
        for col, val in (("req_no", req_no), ("method", method),
                         ("status", status), ("phase", phase)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        sql = ("SELECT ver_no, req_no, method, phase, status, result, evidence, follow_up, close_note,"
               " criteria, owner, project_no FROM verification")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ver_no"
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
    def _check_method(method: str):
        if not method:
            raise FdeError("验证方法不能为空（BR-05）")
        if method not in METHODS:
            raise FdeError(f"验证方法只能是 {'/'.join(METHODS)} 之一（BR-05）")

    @staticmethod
    def _check_phase(phase: str):
        if not phase:
            raise FdeError("验证阶段不能为空（BR-05）")
        if phase not in PHASES:
            raise FdeError(f"验证阶段只能是 {'/'.join(PHASES)} 之一（BR-05）")

    @staticmethod
    def _status_cn(status: str) -> str:
        return _STATUS_CN.get(status, status or "—")

    @staticmethod
    def _result_cn(result: str) -> str:
        return _RESULT_CN.get(result, result or "—")

    @staticmethod
    def _check_mutable(cur: dict):
        if cur["status"] in _TERMINAL:
            raise FdeError(
                f"验证项 {cur['ver_no']} 已关闭（终态），不能再修改（BR-03）")

    def _need(self, ver_no: str):
        ver_no = self._clean(ver_no)
        if not ver_no:
            raise FdeError("验证项编号不能为空")
        cur = self.get(ver_no)
        if not cur:
            raise FdeError(f"验证项 {ver_no} 不存在")
        return cur

    def _assert_requirement_exists(self, req_no: str):
        """跨应用校验强关联：对应需求必须真实存在（BR-01，只读调用，非同一事务）。"""
        try:
            found = self.fde.call("requirement", "get", req_no=req_no)
        except FdeError:
            raise FdeError(f"对应需求 {req_no} 不存在") from None
        except Exception:
            raise FdeError(f"对应需求 {req_no} 校验失败（requirement 应用不可用）") from None
        if not found:
            raise FdeError(f"对应需求 {req_no} 不存在，请先在需求台账中录入（BR-01）")

    def _next_no(self) -> str:
        """生成下一个验证项编号：VER-<三位序号>（唯一且不可变，BR-04）。"""
        rows = self.db.execute("SELECT ver_no FROM verification").fetchall()
        mx = 0
        for r in rows:
            m = re.match(r"^VER-(\d+)$", str(r["ver_no"]))
            if m:
                mx = max(mx, int(m.group(1)))
        return f"VER-{mx + 1:03d}"
