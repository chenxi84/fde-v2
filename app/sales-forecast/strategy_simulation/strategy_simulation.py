from fde import FdeError


class StrategySimulation:
    """策略仿真拟合表——基线方法的"军火库"。回测选优，输出方法+参数。"""

    def _init_db(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS d10_header (
                fit_no         TEXT PRIMARY KEY,
                part_no        TEXT NOT NULL,
                veh_model      TEXT NOT NULL,
                demand_shape   TEXT NOT NULL,
                data_range     TEXT,
                backtest_spec  TEXT,
                status         TEXT NOT NULL DEFAULT '拟合中',
                fitter         TEXT,
                fit_date       TEXT
            );
            CREATE TABLE IF NOT EXISTS d10_candidate (
                fit_no        TEXT NOT NULL,
                cand_no       INTEGER NOT NULL,
                strategy      TEXT NOT NULL,
                inv_policy    TEXT NOT NULL,
                mape          REAL,
                bias          REAL,
                service_level REAL,
                inv_cost      REAL,
                score         REAL,
                rank          INTEGER,
                selected      INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (fit_no, cand_no),
                FOREIGN KEY (fit_no) REFERENCES d10_header(fit_no)
            );
        """)

    def create(self, part_no: str, veh_model: str, demand_shape: str, data_range: str = None):
        """新建拟合任务"""
        from datetime import datetime
        now = datetime.now()
        quarter = f"{(now.month-1)//3+1}"
        fit_no = f"D10-{now.year}Q{quarter}-{now.strftime('%d%H%M')}"
        self.db.execute(
            "INSERT INTO d10_header (fit_no, part_no, veh_model, demand_shape, data_range, fitter, fit_date) VALUES (?,?,?,?,?,?,date('now'))",
            (fit_no, part_no, veh_model, demand_shape, data_range, self.ctx["userno"])
        )
        return {"fit_no": fit_no}

    def add_candidate(self, fit_no: str, strategy: str, inv_policy: str):
        """添加候选策略"""
        header = self._get_header(fit_no)
        if header["status"] != "拟合中":
            raise FdeError("仅拟合中状态可添加候选")
        max_cand = self.db.execute(
            "SELECT COALESCE(MAX(cand_no),0) AS m FROM d10_candidate WHERE fit_no=?", (fit_no,)
        ).fetchone()["m"] + 1
        self.db.execute(
            "INSERT INTO d10_candidate (fit_no, cand_no, strategy, inv_policy) VALUES (?,?,?,?)",
            (fit_no, max_cand, strategy, inv_policy)
        )
        return {"fit_no": fit_no, "cand_no": max_cand}

    def run_backtest(self, fit_no: str):
        """执行滚动回测（简化：实际需历史数据+时间序列回测引擎）"""
        header = self._get_header(fit_no)
        if header["status"] != "拟合中":
            raise FdeError("仅拟合中状态可执行回测")
        candidates = self.db.execute(
            "SELECT * FROM d10_candidate WHERE fit_no=?", (fit_no,)
        ).fetchall()
        if not candidates:
            raise FdeError("无候选策略，请先添加")
        # 简化：使用默认打分（实际应基于历史数据回测）
        results = []
        for c in candidates:
            mape = 10.0 + (c["cand_no"] * 2)  # 模拟
            bias = 1.0 + (c["cand_no"] * 0.5)
            service_level = 96.0 - (c["cand_no"] * 1)
            inv_cost = 100 + (c["cand_no"] * 20)
            score = 100 - mape - abs(bias) * 2 - (100 - service_level) * 0.5 - inv_cost * 0.01
            self.db.execute(
                "UPDATE d10_candidate SET mape=?, bias=?, service_level=?, inv_cost=?, score=? WHERE fit_no=? AND cand_no=?",
                (mape, bias, service_level, inv_cost, score, fit_no, c["cand_no"])
            )
            results.append({"cand_no": c["cand_no"], "mape": mape, "score": score})
        # 排名
        ranked = sorted(results, key=lambda x: x["score"], reverse=True)
        for rank, r in enumerate(ranked, 1):
            self.db.execute(
                "UPDATE d10_candidate SET rank=? WHERE fit_no=? AND cand_no=?",
                (rank, fit_no, r["cand_no"])
            )
        self.db.execute("UPDATE d10_header SET status='已选定' WHERE fit_no=?", (fit_no,))
        return {"fit_no": fit_no, "rankings": ranked}

    def select_strategy(self, fit_no: str, cand_no: int):
        """选定策略"""
        header = self._get_header(fit_no)
        if header["status"] not in ("已选定", "拟合中"):
            raise FdeError(f"状态 {header['status']} 不可选定")
        # 检查综合分
        cand = self.db.execute(
            "SELECT * FROM d10_candidate WHERE fit_no=? AND cand_no=?", (fit_no, cand_no)
        ).fetchone()
        if not cand:
            raise FdeError(f"候选 {cand_no} 不存在")
        if cand["score"] and cand["score"] < 60:
            raise FdeError(f"候选综合分 {cand['score']} 低于可接受线(60)，建议转借用基线D05")
        # 清除旧选定
        self.db.execute("UPDATE d10_candidate SET selected=0 WHERE fit_no=?", (fit_no,))
        # 标记选定
        self.db.execute(
            "UPDATE d10_candidate SET selected=1 WHERE fit_no=? AND cand_no=?", (fit_no, cand_no)
        )
        self.db.execute("UPDATE d10_header SET status='生效中' WHERE fit_no=?", (fit_no,))
        return {"fit_no": fit_no, "selected_cand": cand_no, "strategy": cand["strategy"]}

    def get(self, fit_no: str):
        header = self._get_header(fit_no)
        candidates = self.db.execute(
            "SELECT * FROM d10_candidate WHERE fit_no=? ORDER BY rank", (fit_no,)
        ).fetchall()
        return {"header": dict(header), "candidates": [dict(c) for c in candidates]}

    def get_strategy(self, part_no: str, veh_model: str):
        """供D04调用：获取当前生效策略"""
        row = self.db.execute(
            """SELECT h.fit_no, c.strategy, c.inv_policy
               FROM d10_header h JOIN d10_candidate c ON h.fit_no=c.fit_no
               WHERE h.part_no=? AND h.veh_model=? AND h.status='生效中' AND c.selected=1
               ORDER BY h.fit_date DESC LIMIT 1""",
            (part_no, veh_model)
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def list(self, part_no: str = None, status: str = None):
        sql = "SELECT * FROM d10_header WHERE 1=1"
        params = []
        if part_no:
            sql += " AND part_no=?"
            params.append(part_no)
        if status:
            sql += " AND status=?"
            params.append(status)
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def _get_header(self, fit_no: str):
        row = self.db.execute("SELECT * FROM d10_header WHERE fit_no=?", (fit_no,)).fetchone()
        if not row:
            raise FdeError(f"拟合单 {fit_no} 不存在")
        return row
