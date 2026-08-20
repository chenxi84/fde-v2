from fde import FdeError
import json


class CommonPartAggregation:
    """通用件汇总修正表——总量层去重修正，对抗公地悲剧。仅通用件经过。"""

    def _init_db(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS d07_header (
                agg_no       TEXT PRIMARY KEY,
                part_no      TEXT NOT NULL,
                period       TEXT NOT NULL,
                sum_qty      REAL NOT NULL DEFAULT 0,
                anchor_ref   TEXT NOT NULL DEFAULT '{}',
                dedup_qty    REAL,
                dedup_pct    REAL,
                dedup_reason TEXT,
                split_qty    TEXT,
                status       TEXT NOT NULL DEFAULT '待汇总',
                reviser      TEXT,
                revise_time  TEXT
            );
            CREATE TABLE IF NOT EXISTS d07_detail (
                agg_no        TEXT NOT NULL,
                oem_code      TEXT NOT NULL,
                owner_sales   TEXT NOT NULL,
                approved_qty  REAL NOT NULL,
                evidence_qty  REAL NOT NULL DEFAULT 0,
                verbal_qty    REAL NOT NULL DEFAULT 0,
                deducted_qty  REAL NOT NULL DEFAULT 0,
                split_result  REAL,
                PRIMARY KEY (agg_no, oem_code),
                FOREIGN KEY (agg_no) REFERENCES d07_header(agg_no)
            );
        """)

    def create(self, part_no: str, period: str):
        """新建汇总单，拉取各客户D04核定值。"""
        from datetime import datetime
        now = datetime.now().strftime("%Y%m%d%H%M%S")
        agg_no = f"AGG-{now[:6]}-{now[6:]}"
        self.db.execute(
            "INSERT INTO d07_header (agg_no, part_no, period) VALUES (?,?,?)",
            (agg_no, part_no, period)
        )
        # D04核定值需跨应用获取；此处预留结构，实际场景由调用方逐客户 add_detail
        return {"agg_no": agg_no, "part_no": part_no, "period": period}

    def add_detail(self, agg_no: str, oem_code: str, owner_sales: str, approved_qty: float,
                   evidence_qty: float = 0, verbal_qty: float = 0):
        """添加客户份额明细"""
        header = self._get_header(agg_no)
        if header["status"] != "待汇总":
            raise FdeError("仅待汇总状态可添加明细")
        self.db.execute(
            """INSERT OR REPLACE INTO d07_detail (agg_no, oem_code, owner_sales, approved_qty, evidence_qty, verbal_qty)
               VALUES (?,?,?,?,?,?)""",
            (agg_no, oem_code, owner_sales, approved_qty, evidence_qty, verbal_qty)
        )
        # 更新汇总合计
        total = self.db.execute(
            "SELECT SUM(approved_qty) AS s FROM d07_detail WHERE agg_no=?", (agg_no,)
        ).fetchone()["s"] or 0
        self.db.execute("UPDATE d07_header SET sum_qty=? WHERE agg_no=?", (total, agg_no))
        return {"agg_no": agg_no, "oem_code": oem_code}

    def get(self, agg_no: str):
        header = self._get_header(agg_no)
        details = self.db.execute("SELECT * FROM d07_detail WHERE agg_no=?", (agg_no,)).fetchall()
        return {"header": dict(header), "details": [dict(d) for d in details]}

    def list(self, part_no: str = None, period: str = None, status: str = None):
        sql = "SELECT * FROM d07_header WHERE 1=1"
        params = []
        if part_no:
            sql += " AND part_no=?"
            params.append(part_no)
        if period:
            sql += " AND period=?"
            params.append(period)
        if status:
            sql += " AND status=?"
            params.append(status)
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def set_dedup(self, agg_no: str, dedup_qty: float, dedup_reason: str, anchor_ref: dict = None):
        """去重修正：差异化折减"""
        header = self._get_header(agg_no)
        if header["status"] not in ("待汇总",):
            raise FdeError("仅待汇总状态可修正")
        if not dedup_reason.strip():
            raise FdeError("折减必须有依据（无锚、无证据清单不得拍脑袋折减）")
        sum_qty = header["sum_qty"]
        dedup_pct = (dedup_qty - sum_qty) / max(abs(sum_qty), 0.01) if sum_qty else 0
        # 承诺量保护：汇总函件加码部分，确保不低于承诺量
        total_evidence = self.db.execute(
            "SELECT SUM(evidence_qty + approved_qty - evidence_qty - verbal_qty) AS s FROM d07_detail WHERE agg_no=?",
            (agg_no,)
        ).fetchone()["s"] or 0
        if dedup_qty < total_evidence:
            raise FdeError(f"修正总量 {dedup_qty} 低于已承诺量 {total_evidence}，违反承诺量保护")
        if anchor_ref:
            self.db.execute("UPDATE d07_header SET anchor_ref=? WHERE agg_no=?",
                            (json.dumps(anchor_ref, ensure_ascii=False), agg_no))
        self.db.execute(
            "UPDATE d07_header SET dedup_qty=?, dedup_pct=?, dedup_reason=?, status='已修正', reviser=?, revise_time=datetime('now','localtime') WHERE agg_no=?",
            (dedup_qty, dedup_pct, dedup_reason, self.ctx["userno"], agg_no)
        )
        return {"agg_no": agg_no, "dedup_qty": dedup_qty, "dedup_pct": dedup_pct}

    def set_split(self, agg_no: str, split_detail: list):
        """拆回分配：修正总量落回客户维度"""
        header = self._get_header(agg_no)
        if header["status"] != "已修正":
            raise FdeError("仅已修正状态可拆回分配")
        for item in split_detail:
            self.db.execute(
                "UPDATE d07_detail SET deducted_qty=?, split_result=? WHERE agg_no=? AND oem_code=?",
                (item.get("deducted_qty", 0), item.get("split_result"), agg_no, item["oem_code"])
            )
        self.db.execute("UPDATE d07_header SET split_qty=? WHERE agg_no=?",
                        (json.dumps(split_detail, ensure_ascii=False), agg_no))
        return {"agg_no": agg_no}

    def confirm(self, agg_no: str):
        """确认转D08"""
        header = self._get_header(agg_no)
        if header["status"] != "已修正":
            raise FdeError("仅已修正状态可确认")
        self.db.execute("UPDATE d07_header SET status='已确认' WHERE agg_no=?", (agg_no,))
        return {"agg_no": agg_no, "status": "已确认"}

    def _get_header(self, agg_no: str):
        row = self.db.execute("SELECT * FROM d07_header WHERE agg_no=?", (agg_no,)).fetchone()
        if not row:
            raise FdeError(f"汇总单 {agg_no} 不存在")
        return row
