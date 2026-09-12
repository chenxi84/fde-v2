"""psc 组：哪些服务**不给智能体调**（组级下沉声明，与 _roles.py 同一套约定）。

为什么要有这份声明
------------------
AgentScope 会把应用的每个公共服务都变成一个工具，而工具数直接决定选择准确率——
外部证据（arXiv:2605.24660）显示单次呈现超过 ~60 个工具即进入塌陷区，且**多余的
候选会主动伤害**准确率。所以工具面要主动收：agent 永远不该调的服务不该出现在它的
工具表里。

用黑名单而不是白名单：白名单要为 180 个服务逐一表态，加应用就要同步改，维护不动；
而「agent 不该碰」的服务是少数、稳定、有明确特征（下面三类）。

三类该摘的服务
--------------
1. **内部回填** —— 由别的应用在流程中调用。agent 绕过流程直接调是错的，
   比如直接改物料拟合参数，会让 `strategy_fitting` 的「建议→复核→生效」链路失去意义。
2. **外部回执** —— ERP / 周边系统回调进来的入口，不是 agent 发起的动作。
3. **被 batch 版取代的单行版** —— agent 该用批量接口；逐行调既慢，又容易只改一半。

**只影响 agent 的工具表，不影响 `self.fde.call` 的跨应用调用**——
应用之间该怎么调还怎么调，这里管的是「模型能不能看到」。

加新条目
--------
服务名写**公共方法名**（不带应用前缀）。摘错了会让 agent 少一条路，
不确定的宁可不摘——塌陷是概率问题，功能缺失是确定问题。
"""
HIDDEN_FROM_AGENT = {
    # ── 内部回填：由其他应用在流程中调用 ──
    "psc/md_material": [
        "set_fit_params",        # 由 strategy_fitting.approve 回填，agent 直接改会跳过复核
    ],
    "psc/master_plan": [
        "import_plan",           # 线下产能平衡结果导回，是人工/外部动作，不是 agent 动作
    ],

    # ── 外部回执：ERP / 周边系统回调入口 ──
    "psc/demand_pool": [
        "on_workorder_started",  # ERP 回传工单开工
        "on_inbound",            # ERP 回传入库
    ],

    # ── ERP 冗余回写：数据该由同步服务整体拉，不该逐条 upsert ──
    "psc/sales_history": [
        "upsert",                # 单条回写
        "attach_forecast",       # 预测侧推送，由 sales_forecast 调
        "sync_forecast",         # 批量回填 forecast_qty，由 attainment 调
    ],
    "psc/attainment": [
        "upsert",                # ERP 统计回写
    ],

    # ── 被 batch 版取代的单行版 / 内部投影 ──
    "psc/sales_forecast": [
        "calc_baseline",              # agent 用 calc_baseline_batch
        "decide",                     # agent 用 decide_batch
        "fill_customer",              # 单行填数；agent 用 import_orig_qty（内部仍会走它）
        "customer_forecast_history",  # 供 attainment 算达成率的投影，不是 agent 的动作
    ],
    "psc/inventory_projection": [
        "refresh",               # agent 用 refresh_batch
    ],
}
