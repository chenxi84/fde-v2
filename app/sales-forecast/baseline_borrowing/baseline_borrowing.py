from fde import FdeError


class BaselineBorrowing:
    """基线借用台账——历史不足零件的基线例外登记。

    标识（主键）：jy_no（编码规则 JY-YYYYMM-NNN）
    五种借法（先导指标/类比/模板拟合/上移/池化）保证"借来的基线"可复核、可回溯。
    与 strategy_simulation 分工：历史充足→D10 选策略；历史不足→本表借基线。
    """

    def _init_db(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS baseline_borrowing (
                jy_no          TEXT PRIMARY KEY,
                part_no        TEXT NOT NULL,
                veh_model      TEXT NOT NULL,
                hist_months    INTEGER NOT NULL,
                borrow_method  TEXT NOT NULL,
                borrow_source  TEXT NOT NULL,
                source_params  TEXT NOT NULL,
                calibration    TEXT,
                derived_qty    TEXT NOT NULL DEFAULT '{}',
                proc_batch     TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT '待审核',
                reviewer       TEXT,
                review_date    TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_bb_part_no ON baseline_borrowing (part_no);
            CREATE INDEX IF NOT EXISTS idx_bb_status ON baseline_borrowing (status);
            CREATE INDEX IF NOT EXISTS idx_bb_proc_batch ON baseline_borrowing (proc_batch);
        """)

    # -----------------------------------------------------------------
    # 公开方法
    # -----------------------------------------------------------------

    def create(self, part_no: str, veh_model: str, hist_months: int,
               borrow_method: str, borrow_source: str, source_params: str,
               derived_qty: str, proc_batch: str, calibration: str = None):
        """新建基线借用单。

        part_no: 零件号
        veh_model: 适用车型
        hist_months: 可用清洗历史月数
        borrow_method: 先导指标/类比/模板拟合/上移/池化
        borrow_source: 借用来源（相似车型/模板编号/OEM预测版本/平台层级）
        source_params: 来源参数（峰值/衰减率/分摊权重，JSON 或文本）
        derived_qty: 推导基线 M0~M+N 各期值（JSON）
        proc_batch: 关联 D04 加工批次
        calibration: 早期校准记录（有早期数据时必填）

        跨应用调用：
        - 先导指标法可能调用 demand_collection.get 获取 OEM 预测
        - 可能调用 vehicle_part_mapping.get 获取形态/生命周期信息
        """
        part_no = self._clean(part_no)
        veh_model = self._clean(veh_model)
        borrow_method = self._clean(borrow_method)
        borrow_source = self._clean(borrow_source)
        source_params = self._clean(source_params)
        derived_qty = self._clean(derived_qty) if derived_qty else "{}"
        proc_batch = self._clean(proc_batch)
        calibration = self._clean(calibration) if calibration else None

        if not part_no:
            raise FdeError("零件号必填")
        if not veh_model:
            raise FdeError("适用车型必填")
        if not borrow_source:
            raise FdeError("借用来源必填")
        if not source_params:
            raise FdeError("来源参数必填")
        if not proc_batch:
            raise FdeError("关联加工批次必填")

        self._validate_borrow_method(borrow_method)
        if isinstance(hist_months, str):
            try:
                hist_months = int(hist_months)
            except (TypeError, ValueError):
                raise FdeError("历史月数必须为整数")

        # BR-02: 有早期数据必须校准参数
        if hist_months > 0 and not calibration:
            raise FdeError("有自身早期数据必须校准参数，纯照搬模板不予通过")

        # 先导指标法：可选跨应用调用 demand_collection 获取 true_qty
        if borrow_method == "先导指标":
            try:
                self.fde.call("demand_collection", "get", collect_no=borrow_source)
            except FdeError:
                pass  # 弱依赖，不阻断创建
            except Exception:
                pass

        # 可选跨应用调用 vehicle_part_mapping 获取形态/生命周期信息
        try:
            self.fde.call("vehicle_part_mapping", "get", part_no=part_no, veh_model=veh_model)
        except FdeError:
            pass  # 弱依赖，不阻断创建
        except Exception:
            pass

        jy_no = self._generate_jy_no()

        self.db.execute(
            "INSERT INTO baseline_borrowing (jy_no, part_no, veh_model, hist_months, borrow_method, "
            "borrow_source, source_params, calibration, derived_qty, proc_batch, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (jy_no, part_no, veh_model, hist_months, borrow_method, borrow_source,
             source_params, calibration, derived_qty, proc_batch, "待审核")
        )
        return self.get(jy_no)

    def get(self, jy_no: str):
        """获取借用单详情。"""
        jy_no = self._clean(jy_no)
        if not jy_no:
            raise FdeError("借用单号必填")
        row = self.db.execute(
            "SELECT * FROM baseline_borrowing WHERE jy_no = ?", (jy_no,)
        ).fetchone()
        if not row:
            raise FdeError(f"借用单 {jy_no} 不存在")
        return dict(row)

    def list(self, part_no: str = None, status: str = None,
             borrow_method: str = None):
        """按条件列表查询。"""
        sql = "SELECT * FROM baseline_borrowing WHERE 1=1"
        params = []
        if part_no:
            sql += " AND part_no = ?"
            params.append(part_no)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if borrow_method:
            sql += " AND borrow_method = ?"
            params.append(borrow_method)
        sql += " ORDER BY jy_no DESC"
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def review(self, jy_no: str, approved: bool, comment: str):
        """审核借用单——通过或驳回。

        BR-02 校验：有早期数据但无校准记录→驳回。
        approved=True 时状态→生效；approved=False 时驳回（状态回退至待审核，供修改重报）。
        """
        jy_no = self._clean(jy_no)
        comment = self._clean(comment)
        if not comment:
            raise FdeError("审核意见必填")

        record = self.get(jy_no)
        if record["status"] != "待审核":
            raise FdeError(f"仅待审核借用单可审核，当前状态：{record['status']}")

        reviewer = self.ctx.userno if hasattr(self, "ctx") else "系统"
        from datetime import datetime, timezone
        review_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if approved:
            # BR-02: 有早期数据必须校准，纯照搬模板不予审核通过
            if record["hist_months"] > 0 and not record["calibration"]:
                raise FdeError("有早期数据但无校准记录——驳回：有早期数据必须校准参数，纯照搬模板不予审核通过")
            self.db.execute(
                "UPDATE baseline_borrowing SET status = '生效', reviewer = ?, review_date = ? WHERE jy_no = ?",
                (reviewer, review_date, jy_no)
            )
        else:
            # 驳回——状态回到待审核（保留驳回意见在 calibration 中追加记录）
            rejection_note = f"[驳回] {review_date} {reviewer}: {comment}"
            new_cal = (record["calibration"] or "") + "\n" + rejection_note if record["calibration"] else rejection_note
            self.db.execute(
                "UPDATE baseline_borrowing SET calibration = ?, reviewer = ?, review_date = ? WHERE jy_no = ?",
                (new_cal, reviewer, review_date, jy_no)
            )

        return self.get(jy_no)

    def calibrate(self, jy_no: str, calibration_data: str):
        """早期校准更新——有自身历史数据后修正借用参数。

        calibration_data: 校准记录（含峰值调整/衰减率修正/偏差分析等）。
        BR-02：纯照搬模板不予审核通过，已生效借用单可追补校准。
        """
        jy_no = self._clean(jy_no)
        calibration_data = self._clean(calibration_data)
        if not calibration_data:
            raise FdeError("校准数据必填")

        record = self.get(jy_no)
        if record["status"] not in ("待审核", "生效"):
            raise FdeError(f"仅待审核/生效借用单可校准，当前状态：{record['status']}")

        # 合并校准记录
        new_cal = (record["calibration"] or "") + "\n" + calibration_data if record["calibration"] else calibration_data
        self.db.execute(
            "UPDATE baseline_borrowing SET calibration = ? WHERE jy_no = ?",
            (new_cal.strip(), jy_no)
        )
        return self.get(jy_no)

    def close(self, jy_no: str, reason: str):
        """关闭借用单——历史转充足后切换自产策略，或不再使用该借用。

        状态→已转自产（历史转充足）或已关闭（不再使用）。
        reason 记录关闭原因与切换依据。
        """
        jy_no = self._clean(jy_no)
        reason = self._clean(reason)
        if not reason:
            raise FdeError("关闭原因必填")

        record = self.get(jy_no)
        if record["status"] == "已关闭":
            raise FdeError("借用单已关闭")
        if record["status"] == "已转自产":
            raise FdeError("借用单已转自产，无需重复关闭")

        # 判定关闭类型：含"转自产"关键词→已转自产，否则→已关闭
        if "转自产" in reason or "历史充足" in reason or "切换" in reason:
            new_status = "已转自产"
        else:
            new_status = "已关闭"

        self.db.execute(
            "UPDATE baseline_borrowing SET status = ? WHERE jy_no = ?",
            (new_status, jy_no)
        )
        return self.get(jy_no)

    def get_derived_baseline(self, jy_no: str):
        """获取推导基线值——返回 derived_qty 中各期基线数据。"""
        record = self.get(jy_no)
        if record["status"] in ("已关闭",):
            raise FdeError(f"借用单已关闭，推导基线不可用")
        import json
        try:
            derived = json.loads(record["derived_qty"])
        except (json.JSONDecodeError, TypeError):
            raise FdeError("推导基线数据格式异常")
        return {
            "jy_no": jy_no,
            "part_no": record["part_no"],
            "veh_model": record["veh_model"],
            "borrow_method": record["borrow_method"],
            "derived_qty": derived,
        }

    # -----------------------------------------------------------------
    # 内部辅助
    # -----------------------------------------------------------------

    def _clean(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _validate_borrow_method(self, method):
        valid = ["先导指标", "类比", "模板拟合", "上移", "池化"]
        if method not in valid:
            raise FdeError(f"借用方法只能为：{'/'.join(valid)}")

    def _generate_jy_no(self):
        """生成借用单号 JY-YYYYMM-NNN。"""
        from datetime import datetime, timezone
        yyyymm = datetime.now(timezone.utc).strftime("%Y%m")
        for _ in range(5):
            max_no = self.db.execute(
                "SELECT jy_no FROM baseline_borrowing WHERE jy_no LIKE ? ORDER BY jy_no DESC LIMIT 1",
                (f"JY-{yyyymm}-%",)
            ).fetchone()
            if max_no:
                try:
                    seq = int(max_no["jy_no"].split("-")[-1]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            jy_no = f"JY-{yyyymm}-{seq:03d}"
            if not self.db.execute(
                "SELECT 1 FROM baseline_borrowing WHERE jy_no = ?", (jy_no,)
            ).fetchone():
                return jy_no
        raise FdeError("借用单号生成失败，请重试")
