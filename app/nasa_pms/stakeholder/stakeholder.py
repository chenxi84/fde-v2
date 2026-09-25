from __future__ import annotations

from fde import FdeError

# 相关方类型字典（架构卡片 11 的「类型（客户/承包商/内部组织）」；业务名逐字取自《术语表.md》
# 的「客户」/「承包商」两行与材料 TABLE 4.1-1 的 stakeholder 举例）
SH_TYPES = ("customer", "contractor", "internal_org")
# 期望类别字典（材料 §4.1.1.2.3 Identify Needs, Goals, and Objectives + §4.1.1.2.6 Measures of
# Effectiveness + §4.1.1.2.2 的 constraints）—— 业务名见同目录 `新增术语.md`
EXPECTATION_KINDS = ("need", "goal", "objective", "moe", "constraint")

_SH_TYPE_CN = {"customer": "客户", "contractor": "承包商", "internal_org": "内部组织"}
_KIND_CN = {"need": "需要", "goal": "目标", "objective": "指标",
            "moe": "度量有效性（MOE）", "constraint": "约束"}

# 主档字段清单 —— `get` 与 `list` **共用同一份**，杜绝两处口径漂移（CONVENTION §7）
_MAIN_COLS = "sh_no, name, sh_type, duty, org, contact, project_no"
# 期望子表字段清单 —— 详情子表与派生计数共用（写入路径逐列对应，无隐藏列）
_EXP_COLS = "seq, statement, kind, source, moe, committed, note"
# 可选描述性字段（`upsert` 的部分更新语义只作用于这四个；None = 不改 / 空串 = 清空，见 BR-08）
_OPTIONAL_FIELDS = ("duty", "org", "contact", "project_no")


class Stakeholder:
    """利益相关者聚合根。项目相关方（机构或人员）及其**期望清单**。

    数据来源类型：**外部同步（机构与人员）** —— 相关方本体由外部主数据同步进来，
    本系统**只读引用、不维护源数据**（`architecture.md` 聚合根卡 11「来源」一栏）。
    由此派生的三条形态特征，是本页与同组其它页的**语义差**（照抄别的页会同时错三处）：

      1. **没有 `create`** —— 唯一写主档的入口是 `upsert`：编号由外部来源给定，
         存在即更新（幂等），不存在才新增。编号落库不可变（BR-01）。
      2. **没有 `delete`** —— 主数据只读引用，且期望一旦记录就是"当时谈过什么"的留痕
         （材料 §4.1.1.2.10 Capture Work Products）。同步源删掉一条，本系统也**不**跟着删。
      3. **没有状态机** —— 卡片 11 写明「状态机：无」。本聚合的写轴只有两条：
         **主档 = 幂等同步**（`upsert`）与 **期望 = 随相关方维护 + 承诺后冻结**
         （`add_expectation` / `update_expectation`，BR-07）。

    一致性边界（见 `architecture.md` 聚合根卡 11）：
      · **I-1 期望必须挂在本聚合内（期望随相关方维护，无独立标识）** —— 期望并入本聚合，
        没有独立业务编号（`(sh_no, seq)` 复合主键）。推论有三：
        ① 任何期望的读写都必须带 `sh_no`，且先校验该相关方**存在**（不存"孤儿期望"）；
        ② `get` 一次带回期望清单，不存在"另开一张期望台账"的读法；
        ③ **跨相关方的期望汇总视图也不给** —— 材料 §4.1.1.2.7 要求期望"可追溯到来源"，
           那是**逐条**的属性（`source` 字段），不是把期望拉平成一个独立清单的理由。

    业务规则落点：BR-01 编号由外部给定且不可变 / BR-02 名称必填 / BR-03 类型受字典约束 /
                 BR-04 期望必须挂在本聚合内（I-1）/ BR-05 期望的陈述·类别·来源必填且类别受字典约束 /
                 BR-06 MOE 类期望必须有度量口径 / BR-07 已获承诺的期望冻结（可撤回后解锁）/
                 BR-08 upsert 的部分更新语义（None = 不改 / 空串 = 清空）。
    """

    # ── 服务（公共方法即服务） ──────────────────────────────

    def upsert(self, sh_no: str, name: str, sh_type: str, duty=None, org=None,
               contact=None, project_no=None):
        """**外部同步落库**：`sh_no` 已存在则更新，不存在则新增（幂等）。

        这是本应用**唯一**写主档的入口 —— 没有 `create`（编号由外部来源给定，不是本系统生成），
        也没有 `delete`（相关方被源系统移除时，本系统保留引用，见类文档）。外部同步是**增量**推送，
        故四个描述性字段走**部分更新**语义（BR-08）：
          · 传 `None`（不传）= **不改**该字段（同步方"本次不涉及"）；
          · 传空串 = **清空**该字段（同步方"确实没有"）；
        这比"全量覆盖"安全：同步载荷少给一个字段，不会静默抹掉本系统里已有的内容。

        `sh_no` / `name` / `sh_type` 三项**必填**（BR-01/02/03）：编号是外部业务键，
        名称与类型是相关方的识别信息 —— 同步一条"没有名字"或"不知道是哪一类"的相关方无意义。
        """
        sh_no = self._clean(sh_no)
        if not sh_no:
            raise FdeError("利益相关者编号不能为空（编号由外部来源系统给定，本系统不生成）")
        name = self._clean(name)
        if not name:
            raise FdeError("利益相关者名称不能为空")
        sh_type = self._clean(sh_type)
        self._check_type(sh_type)                                   # BR-03

        # 选填字段先全部清洗：None 保留为 None（= 不改），其余取清洗后的值（空串 = 清空）
        opts = {f: (None if v is None else self._clean(v))
                for f, v in zip(_OPTIONAL_FIELDS, (duty, org, contact, project_no))}

        if self._exists(sh_no):                                     # 存在即更新（幂等）
            sets, args = ["name = ?", "sh_type = ?"], [name, sh_type]
            for col in _OPTIONAL_FIELDS:
                if opts[col] is not None:
                    sets.append(f"{col} = ?")
                    args.append(opts[col])
            args.append(sh_no)
            self.db.execute(
                "UPDATE stakeholder SET " + ", ".join(sets) + " WHERE sh_no = ?", tuple(args))
        else:
            self.db.execute(
                "INSERT INTO stakeholder (sh_no, name, sh_type, duty, org, contact, project_no)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sh_no, name, sh_type, opts["duty"], opts["org"], opts["contact"],
                 opts["project_no"]),
            )
        return self.get(sh_no)

    def add_expectation(self, sh_no: str, statement: str, kind: str, source: str,
                        moe=None, committed=None, note=None):
        """登记一条期望（期望并入本聚合，无独立标识 —— 卡片 I-1）。

        这是"期望从哪来"的落点。材料 §4.1.1.2.5 要求把期望写成**可接受的陈述**
        （"Expectations in Acceptable Statements"），§4.1.1.2.7 要求**记下来源**
        （"should also capture the source of the expectation"），§4.1.1.2.6 要求对
        **度量有效性类**的期望给出度量口径 —— 本服务把这四件事落在一次调用里。

        `sh_no` 先校验：**期望必须挂在本聚合内**（I-1），不存在"没有相关方的期望"。
        序号 `seq` 在本相关方内递增（无独立业务编号）。
        """
        self._need(sh_no)                                           # I-1 / BR-04
        statement = self._clean(statement)
        if not statement:
            raise FdeError("期望陈述不能为空")
        kind = self._clean(kind)
        self._check_kind(kind)                                      # BR-05
        source = self._clean(source)
        if not source:
            raise FdeError("期望来源不能为空（材料 §4.1.1.2.7 要求记下期望的来源）")
        moe = self._clean(moe)
        self._check_moe(kind, moe)                                  # BR-06

        flag = self._flag(committed)
        self.db.execute(
            "INSERT INTO stakeholder_expectation (sh_no, seq, statement, kind, source, moe,"
            " committed, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sh_no, self._next_seq(sh_no), statement, kind, source, moe,
             0 if flag is None else flag, self._clean(note)),
        )
        return self.get(sh_no)

    def update_expectation(self, sh_no: str, seq, statement=None, kind=None, source=None,
                           moe=None, committed=None, note=None):
        """维护一条期望（改陈述 / 类别 / 来源 / 度量口径 / 承诺 / 备注）。

        **BR-07 是本服务的核心**：**已获相关方承诺**（`committed = 1`）的期望，
        其**陈述 / 类别 / 来源 / 度量口径**不可改写 —— 材料 §4.1.1.2.8
        "Obtain Stakeholder Commitments to the Validated Set of Expectations" 的语义是
        **双方达成一致并签字**（"signatures or other forms of commitment are obtained"），
        签过字的那句话再被单方面改掉，承诺就不成立了。

        冻结是**可解锁**的（与同组 `technical_measure` 的 `rebaseline` 同形）：
        把 `committed` 传 `0`（撤回承诺）后即可改写；**撤回与改写允许在同一次调用完成**
        （`committed=0` + 新陈述）—— 前端"先取消勾选、字段随即解锁、一并保存"就是这一条。
        `note` **不受冻结影响**（"列入验证计划"这类跟踪留痕本来就该在承诺之后还能写）。

        序号 `seq` 必须命中本相关方的期望；本相关方内没有跨相关方的期望可改（I-1）。
        """
        self._need(sh_no)                                           # I-1 / BR-04
        seq = self._seq_int(seq)
        row = self._exp_row(sh_no, seq)
        if row is None:
            raise FdeError(f"利益相关者 {sh_no} 没有序号为 {seq} 的期望")

        # 守卫顺序 = 安全边界：**冻结排最前**（口径字段一动就直接拒，不进入后续校验）
        target_committed = (int(row["committed"]) if committed is None
                            else self._flag(committed))
        frozen_touched = any(v is not None for v in (statement, kind, source, moe))
        if frozen_touched and int(row["committed"]) and target_committed:
            raise FdeError(
                f"相关方 {sh_no} 第 {seq} 条期望已获相关方承诺（材料 §4.1.1.2.8），"
                "陈述 / 类别 / 来源 / 度量口径不可改写 —— 要改请先撤回承诺（committed=0，BR-07）")

        sets, args = [], []
        if statement is not None:
            statement = self._clean(statement)
            if not statement:
                raise FdeError("期望陈述不能为空")
            sets.append("statement = ?")
            args.append(statement)
        if kind is not None:
            kind = self._clean(kind)
            self._check_kind(kind)                                  # BR-05
            sets.append("kind = ?")
            args.append(kind)
        if source is not None:
            source = self._clean(source)
            if not source:
                raise FdeError("期望来源不能为空（材料 §4.1.1.2.7 要求记下期望的来源）")
            sets.append("source = ?")
            args.append(source)
        if moe is not None:
            sets.append("moe = ?")
            args.append(self._clean(moe))
        if committed is not None:
            sets.append("committed = ?")
            args.append(target_committed)
        if note is not None:
            sets.append("note = ?")
            args.append(self._clean(note))

        # BR-06 要在**合并后**的口径上判：只改类别（goal → moe）而库里没有度量口径，同样得拦
        eff_kind = self._clean(kind) if kind is not None else row["kind"]
        eff_moe = self._clean(moe) if moe is not None else self._clean(row["moe"])
        self._check_moe(eff_kind, eff_moe)

        if not sets:
            raise FdeError("没有要修改的内容")
        args += [sh_no, seq]
        self.db.execute("UPDATE stakeholder_expectation SET " + ", ".join(sets)
                        + " WHERE sh_no = ? AND seq = ?", tuple(args))
        return self.get(sh_no)

    def get(self, sh_no: str):
        """按相关方编号查询（含期望清单 `expectations`）；未命中返回 None，不抛异常。

        计数 `expectation_total` / `committed_total` 与 `list` 同口径
        （前端「期望 已承诺/总」列读它）。
        """
        sh_no = self._clean(sh_no)
        if not sh_no:
            return None
        row = self.db.execute(
            "SELECT " + _MAIN_COLS + " FROM stakeholder WHERE sh_no = ?", (sh_no,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["expectations"] = [dict(r) for r in self.db.execute(
            "SELECT " + _EXP_COLS + " FROM stakeholder_expectation"
            " WHERE sh_no = ? ORDER BY seq", (sh_no,)).fetchall()]
        out.update(self._counts(out["expectations"]))
        return out

    def list(self, sh_type: str = None, keyword: str = None, project_no: str = None,
             page: int = None, size: int = None):
        """按类型 / 关键字 / 所属项目筛选，**分页返回 `{items, total}`**，默认按编号升序。

        `keyword` 是**跨字段模糊**匹配（编号 / 名称 / 所属机构 / 职责）—— 主数据页最常见的查法是
        "我记得名字里有个『航天』"，逼用户先判断"这算名称还是算机构"是没必要的。
        `sh_type` 与 `project_no` 是**精确**匹配（字典值与归属键，模糊匹配没有意义）。

        ⚠ `page`/`size` 与 `{items, total}` 是**前端 `pageable` 的契约**（CONVENTION §7 / VIEW_CONVENTION）——
        少了它们，前端拿到的 `items` 恒为空、页面静默显示空态而**不报错**（同组实测踩过）。
        返回项与 `get` 同字段口径（`_MAIN_COLS` 共用 + 同一份计数）；
        期望**明细只在 `get`**（列表不需要 N+1 取子表）。
        """
        where, args = [], []
        for col, val in (("sh_type", sh_type), ("project_no", project_no)):
            val = self._clean(val)
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        kw = self._clean(keyword)
        if kw:
            where.append("(sh_no LIKE ? OR name LIKE ? OR org LIKE ? OR duty LIKE ?)")
            args += [f"%{kw}%"] * 4

        sql = "SELECT " + _MAIN_COLS + " FROM stakeholder"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY sh_no"
        rows = []
        for r in self.db.execute(sql, tuple(args)).fetchall():
            d = dict(r)
            d.update(self._counts_by_no(d["sh_no"]))
            rows.append(d)

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
    def _flag(v):
        """承诺标记归一：None → None（不改 / 用默认）、真值 → 1、假值 → 0，其余拒绝。

        前端复选框给的是布尔（`true` / `false`），REST/同步方可能给 `"1"` / `"是"` ——
        两种都要认；认不出的**拒绝**而不是猜（静默把 `"no"` 当 1 是最糟的错法）。
        """
        if v is None:
            return None
        if isinstance(v, bool):
            return 1 if v else 0
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "y", "是"):
            return 1
        if s in ("0", "false", "no", "n", "否", ""):
            return 0
        raise FdeError(f"「已获相关方承诺」只能是 true / false，当前为「{v}」")

    @staticmethod
    def _seq_int(v) -> int:
        """期望序号必须是正整数（聚合内子表的序号，不是业务编号）。"""
        s = str(v).strip() if v is not None else ""
        if not s:
            raise FdeError("期望序号不能为空")
        try:
            n = int(s)
        except ValueError:
            raise FdeError(f"期望序号必须是正整数，当前为「{s}」") from None
        if n <= 0:
            raise FdeError(f"期望序号必须是正整数，当前为「{s}」")
        return n

    @staticmethod
    def _check_type(sh_type: str):
        if not sh_type:
            raise FdeError("相关方类型不能为空")
        if sh_type not in SH_TYPES:
            raise FdeError(
                "相关方类型只能是 customer/contractor/internal_org 之一"
                f"（{' / '.join(_SH_TYPE_CN[t] for t in SH_TYPES)}，BR-03）")

    @staticmethod
    def _check_kind(kind: str):
        if not kind:
            raise FdeError("期望类别不能为空")
        if kind not in EXPECTATION_KINDS:
            raise FdeError(
                "期望类别只能是 need/goal/objective/moe/constraint 之一"
                f"（{' / '.join(_KIND_CN[k] for k in EXPECTATION_KINDS)}，BR-05）")

    @staticmethod
    def _check_moe(kind: str, moe: str):
        """BR-06：标为「度量有效性（MOE）」的期望必须给出**度量口径**。

        材料 §4.1.1.2.6 的活动名就叫 "Analyze Expectations Statements for **Measures of
        Effectiveness**" —— MOE 的定义是"代表成功判据的可度量期望"（§4.1.1.3 Outputs：
        "a set of MOEs is developed based on the stakeholder expectations"）。
        标成 MOE 却不写口径，等于没有分析过 —— 它和 goal 就没有区别了。
        """
        if kind == "moe" and not moe:
            raise FdeError(
                "类别为「度量有效性（MOE）」的期望必须填写度量口径 —— 可度量的成功判据（BR-06）")

    def _counts(self, expectations: list):
        """由期望清单推导计数 —— `get` 与 `list` 共用同一算法（口径不漂移）。"""
        return {"expectation_total": len(expectations),
                "committed_total": sum(1 for e in expectations if int(e["committed"] or 0))}

    def _counts_by_no(self, sh_no: str):
        r = self.db.execute(
            "SELECT (SELECT COUNT(*) FROM stakeholder_expectation WHERE sh_no = ?) AS ex,"
            " (SELECT COUNT(*) FROM stakeholder_expectation WHERE sh_no = ? AND committed = 1)"
            " AS cm",
            (sh_no, sh_no),
        ).fetchone()
        return {"expectation_total": int(r["ex"] or 0), "committed_total": int(r["cm"] or 0)}

    def _need(self, sh_no: str):
        sh_no = self._clean(sh_no)
        if not sh_no:
            raise FdeError("利益相关者编号不能为空")
        cur = self.get(sh_no)
        if not cur:
            raise FdeError(
                f"利益相关者 {sh_no} 不存在 —— 期望必须挂在本聚合内（卡片 I-1）；"
                "请先经 upsert 同步该相关方")
        return cur

    def _exists(self, sh_no: str) -> bool:
        return self.db.execute("SELECT 1 FROM stakeholder WHERE sh_no = ?",
                               (sh_no,)).fetchone() is not None

    def _exp_row(self, sh_no: str, seq: int):
        return self.db.execute(
            "SELECT " + _EXP_COLS + " FROM stakeholder_expectation"
            " WHERE sh_no = ? AND seq = ?", (sh_no, seq)).fetchone()

    def _next_seq(self, sh_no: str) -> int:
        """期望序号：本相关方内递增（`(sh_no, seq)` 是复合主键，无全局标识 —— 卡片 I-1）。"""
        mx = 0
        for r in self.db.execute(
                "SELECT seq FROM stakeholder_expectation WHERE sh_no = ?", (sh_no,)).fetchall():
            mx = max(mx, int(r["seq"]))
        return mx + 1
