# psc 销量预测引擎选型报告

> 目标：在 fde-v2 的 psc 应用组中，基于零件历史销量数据预测下月销量
> 日期：2026-09-04
> 结论：**statsforecast 作为引擎 + AutoTheta 为主力 + 统计模型集成 + 逐序列回测选型**

---

## 一、结论摘要

| 问题 | 结论 |
|---|---|
| 用哪个组件 | **statsforecast**（Apache-2.0，当前 2.0.3） |
| 用哪个模型 | **AutoTheta(season_length=12)** 为主力；有余力上三模型集成 |
| 间歇需求（零星出库） | **CrostonOptimized / TSB**，与常规序列分赛道处理 |
| 多模型结果怎么取 | **滚动回测（cross_validation）+ 逐序列按 MASE 选 winner** |
| 是否需要基础模型（Chronos/TimesFM） | **现阶段不引入**：需 GPU、黑盒、间歇需求场景表现差 |
| 后续升级路径 | 有协变量后上 **MLForecast + LightGBM**，统计模型永久保留为兜底 |

---

## 二、约束条件（决定了选型边界）

选型不是选「最先进」，而是选「最贴合约束」。本场景的硬约束：

1. **嵌入形态**：fde-v2 是 Flask + Waitress + SQLite 单体后端，组件必须能以普通 Python 包形式 pip 安装，不能引入独立服务、GPU、消息队列
2. **数据形态**：月度销量，零件 × 客户构成序列；存在大量零星出库的长尾序列（间歇需求）
3. **算力**：纯 CPU
4. **可解释性**：预测结果要给计划员看，需要能说明「为什么是这个数」
5. **可审计**：需记录每条序列用了什么模型、回测误差多少

---

## 三、组件选型：为什么是 statsforecast

### 3.1 候选对比

| 方案 | 部署形态 | 月度序列适配 | 间歇需求 | 批量速度 | 判定 |
|---|---|---|---|---|---|
| **statsforecast** | pip 包，numba 内核 | 优（AutoTheta/AutoARIMA/AutoETS） | **优（Croston/TSB）** | 极快（序列级并行） | **选用** |
| statsmodels | pip 包 | 良 | 无 | 慢（Python 循环） | 兜底备选 |
| Prophet | pip 包 | 良（节假日效应） | 无 | 慢（per-series Stan 拟合） | 否 |
| Darts | 拖 PyTorch | 良 | 无 | 中 | 否（过重） |
| MLForecast + LightGBM | pip 包 | 优（需协变量） | 中 | 快 | **二期引入** |
| 时序基础模型（Chronos/TimesFM） | 需 GPU 推理 | 中 | 差 | 快（GPU 下） | 否（约束冲突） |

### 3.2 statsforecast 的运行原理

四层结构，性能来源是 **JIT 编译 + 序列级并行**，而非新算法：

1. **API 层**：`StatsForecast` 类做纯编排，长表输入（`unique_id / ds / y`），模型列表是声明式
2. **调度层**：经典统计模型均为单变量模型，序列之间无耦合 → 天然可并行，`n_jobs=-1` 多进程 map
3. **内核层**：每个模型是 numba `@jit` 修饰的纯数值函数，首次调用编译为机器码，之后无 Python 解释器开销
4. **输出层**：点预测 + 预测区间（模型方差或 conformal）

**关键认识**：ARIMA/ETS 是几十年的老算法，statsforecast 的创新在于把**执行方式**重做——编译下沉 + 并行摊开，使得「每条序列单独拟合调参」从算力上变得可行。

### 3.3 三个坑

- **首次调用有 numba JIT 预热**（几秒），应在应用启动时预热，避免首个 API 请求背锅
- **`season_length` 填观测点数而非日历单位**：月度填 12，日度填 7
- **长表格式必须正确**（`unique_id / ds / y`），这是最常见的报错来源

---

## 四、fev-bench：榜单数据与其正确读法

### 4.1 榜单是什么

AutoGluon 团队（AWS，Shchur et al. 2025，arXiv 2509.26468）发布的时序预测基准：**100 个预测任务 / 96 个真实数据集 / 7 个业务域**，46 个任务带协变量，采用**滚动原点（rolling-origin）多窗口验证**，点预测用 MASE、概率预测用 SQL 评分。**统计基线由 StatsForecast 实现**（已核对论文原文）。

### 4.2 当前排名（MASE Skill Score，越高越好，共 31 个模型）

| 排名 | 模型 | Skill Score | Win Rate | 推理 s/100 | 失败任务 |
|---|---|---|---|---|---|
| 1 | TimesFM-3 | 37.42 | 84.97 | 3.68 | 0 |
| 2 | Chronos-2 | 35.50 | 79.27 | 0.84 | 0 |
| 3 | TiRex-2 | 33.74 | 75.17 | 0.27 | 0 |
| 20 | CatBoost | 23.69 | 43.00 | 0.31 | 0 |
| 21 | LightGBM | 21.69 | 40.63 | 0.27 | 0 |
| 24 | DeepAR | 17.52 | 29.75 | 1.26 | 3 |
| **25** | **Stat. Ensemble** | **16.44** | 37.87 | 146.94 | 4 |
| **26** | **AutoARIMA** | **11.63** | 26.93 | 20.14 | 4 |
| **27** | **AutoTheta** | **10.99** | 25.13 | **3.28** | **0** |
| **28** | **AutoETS** | **2.26** | 27.22 | 3.48 | 3 |
| 29 | Seasonal Naive | 0.00 | 15.07 | 0.48 | 0 |

### 4.3 如何正确读这份榜单

排名低 ≠ 你的场景差，有三个结构性前提必须扣除：

1. **46/100 任务带协变量**，而统计模型基本无法利用协变量，这是其掉队的最大结构性原因——本场景（纯历史销量、无促销/价格特征）恰好避开该劣势区
2. **频率覆盖分钟级到年度级**，月度这个统计模型的主场被稀释在平均里
3. **间歇需求任务代表性不足**，且 **Croston 系列根本未进入榜单**——而它恰恰是统计模型的独有优势

**反向印证**：有 2026 年实测在 148 条澳大利亚月度零售数据上，ETS+ARIMA 组合比 Chronos-Bolt 准确率高 14-16%（MASE 0.52 vs 1.34）。月度、强趋势、强季节的数据正是统计模型的主场（该测试为单数据集单窗口，属例证而非定论）。

### 4.4 榜单对方案的真正价值

不是推翻 statsforecast，而是指出**「单模型 + AutoETS 优先」是错的配法**：

- AutoETS 仅 2.26，近乎无效 → 降级为对照项
- AutoTheta 零失败 + 3.28s/100 → 升为主力
- Stat. Ensemble（16.44）优于任何单统计模型 → 集成优先

---

## 五、三类范式辨析：不是升级关系，是交叠关系

| 维度 | 统计模型 | 机器学习模型 | 基础模型（TSFM） |
|---|---|---|---|
| 知识来源 | 这一条序列自己 | 你的全部历史数据 | 预训练的海量语料 |
| 拟合方式 | 每条序列单独估参 | 全局模型 · 靠特征工程 | 零样本直接推断 |
| 算力 | CPU，秒级 | CPU，分钟级 | GPU 推理 |
| 可解释性 | 高（参数可读） | 中（特征重要性） | 低（黑盒） |
| 代表 | ARIMA · ETS · Theta | LightGBM · CatBoost | Chronos · TimesFM |

### 5.1 机器学习不是统计模型的强化版

表达能力上 ML 确实更宽（带滞后特征的线性回归 ≈ AR），但有几个能力 ML 不是「更强」而是**没有**：

- **树模型无法外推**：预测值永远落在训练集 y 区间内。销量从 1000 稳步涨到 3000 的零件，LightGBM 预测不出 3500——统计模型的趋势项是外推的
- **预测区间不免费**：统计模型方差自带；ML 需额外做分位数回归或 conformal
- **短序列易过拟合**：24 个月、15 个月为零的序列上，3 参数的 Croston 比几万参数的树模型稳

### 5.2 分水岭是「有没有协变量」

- **M4（无协变量）**：纯 ML 表现平平，冠军是 **ES-RNN**（指数平滑 + LSTM 混合）
- **M5（有协变量）**：ML 比最优统计基准准 **22.4%**

同一批算法，胜负反转 → 决定用谁的是数据里有没有外部信息，不是技术代差。

### 5.3 结论：组合优于升级

工业界有效系统的常见形态：

- **分解残差法**：STL/ETS 剥掉趋势季节，ML 预测残差
- **特征注入法**：统计模型的输出作为 ML 的输入特征
- **直接集成**：统计模型平均（Stat. Ensemble 即此思路）

---

## 六、推荐模型配置

### 6.1 分流规则

| 数据特征 | 模型 | 说明 |
|---|---|---|
| 历史 ≥ 24 月，非零占比 ≥ 30% | **AutoTheta(12)** | 月度数据上精度/速度/稳定性综合最优 |
| 同上，需更高精度 | **AutoTheta + AutoARIMA + AutoETS 平均** | 集成显著优于单模型 |
| 非零占比 < 30%（零星出库） | **CrostonOptimized / TSB** | 统计模型独有能力 |
| 历史 12~24 月 | **SeasonalNaive + Theta 对照** | 数据不足，回测说了算 |
| 历史 < 12 月 | 不预测，走安全库存规则 | 任何模型都是猜 |
| 全程保留 | **SeasonalNaive** | 可预测性标尺（MASE > 1 即不可信） |

### 6.2 模型选择依据（两个独立基准交叉验证）

| 来源 | AutoTheta | AutoARIMA | AutoETS | 统计集成 |
|---|---|---|---|---|
| fev-bench（Skill Score，越高越好） | **10.99** | 11.63 | 2.26 | **16.44** |
| M4-Monthly（sMAPE，越低越好） | **10.33** | 12.03 | 11.19 | **9.76** |

两套完全不同的评测口径，AutoTheta 均为最佳单统计模型。

### 6.3 代码骨架

```python
from statsforecast import StatsForecast
from statsforecast.models import (AutoTheta, AutoARIMA, AutoETS,
                                  CrostonOptimized, SeasonalNaive)

# 常规序列赛道
sf = StatsForecast(
    models=[AutoTheta(season_length=12),        # 主力
            AutoARIMA(season_length=12),        # 集成成员
            AutoETS(season_length=12),          # 集成成员 + 对照
            SeasonalNaive(season_length=12)],   # 标尺
    freq="MS", n_jobs=-1)

# 间歇序列单独开一组，不与常规序列混跑
sf_sparse = StatsForecast(models=[CrostonOptimized(), TSB(...)], freq="MS")

# 滚动回测：留最近 3~6 个月逐月截断验证
cv = sf.cross_validation(df, h=1, n_windows=3)
```

---

## 七、psc 接入方案

### 7.1 应用设计：新建 `psc/forecast_engine`

仿照 `strategy_fitting` 的「拟合版本」概念（版本号格式 YYYYMM），对外暴露三个服务：

| 服务 | 职责 |
|---|---|
| `fit(version)` | 拉数 → 预处理 → 回测 → 选型 → 落库 |
| `list_results(version)` | 查预测结果 + 每条序列的 winner 及其回测误差 |
| `get_series(part_id, version)` | 单零件明细：用了什么模型、为什么 |

### 7.2 数据流

1. 从 `sales_history.history_sequence` 拉数，按「零件 × 客户」组装长表
2. 预处理：月度聚合、补齐缺失月份、计算非零占比
3. 按非零占比分流：常规赛道 / 间歇赛道
4. 候选模型池全部跑一遍
5. `cross_validation` 滚动回测
6. **逐序列按 MASE 选 winner** → 写审计表
7. winner 模型用全量数据 refit → `predict(h=1)` 出下月预测 + 区间
8. 结果写入 `sales_forecast`，挂月度版本号（与 `md_monthly_version` 版本管理对齐）

### 7.3 审计表（关键设计）

| 字段 | 说明 |
|---|---|
| 序列 ID（零件/客户） | 主键 |
| winner 模型名 | AutoTheta / AutoARIMA / Croston… |
| 模型参数 | 记录实际拟合参数 |
| 回测 MASE | 选型依据 |
| 非零占比 | 分流依据 |
| 版本号 | YYYYMM |

**这张表是业务敢用预测值的前提**——计划员看到的不是黑盒数字，而是「零件 A：AutoTheta，近 3 月回测 MASE 0.62，80% 区间 [380, 460]」。

### 7.4 与既有应用的关系

预测结果作为「系统建议值」写入 `sales_forecast`，保留人工覆盖能力（供应链落地中这一步几乎不可省）。

---

## 八、落地注意事项

1. **评估指标用 MASE，不用 MAE / MAPE**
   - MASE 除以季节朴素基线误差 → 跨序列可比（零件 A 月销 1 万与零件 B 月销 50 可横比）
   - 对零值序列稳健（MAPE 会除零崩溃）
   - 可回答「哪些零件的预测最不可靠」
2. **滚动原点多窗口验证**：`n_windows=3` 起步，历史充足时扩到 3~6，避免单一切分的偶然性
3. **每个模型包 try/except**：fev-bench 上 AutoARIMA 有 4 个失败任务、AutoETS 有 3 个，单条序列失败时降级到 SeasonalNaive，避免整批中断
4. **winner 模型必须用全量数据 refit**：回测只用于判断「谁配赢」
5. **回测结果按版本留存**：下月重跑时 winner 可能换模型，需可追溯，否则业务会质疑
6. **间歇序列不与常规序列混跑**：两条赛道的指标口径不同
7. **保留 SeasonalNaive 作标尺**：某零件所有模型 MASE > 1 → 该序列不可预测 → 按安全库存处理

---

## 九、演进路径

| 阶段 | 动作 | 触发条件 |
|---|---|---|
| 一期 | AutoTheta + 三模型集成 + Croston 分流 + 回测选型 | 立即可做 |
| 二期 | 引入 MLForecast + LightGBM 进候选池 | 促销/价格等协变量数据齐备 |
| 三期 | 时序基础模型（Chronos-Bolt）加入候选池 | 有 GPU 推理预算 |

**核心原则**：模型池设计成可插拔，任何新模型进来都要和其他模型在回测中公平竞争，胜者留下——而不是赌某个组件「最优」。

---

## 十、参考来源

- fev-bench 论文：Shchur et al., 2025，arXiv 2509.26468（统计基线由 StatsForecast 实现）
- fev-bench 实时榜单：https://tsfm.ai/benchmarks/fev-bench（12 小时刷新一次）
- fev-bench 深度解读：https://tsfm.ai/blog/fev-bench-deep-dive
- M4 竞赛：冠军为 ES-RNN（指数平滑 + LSTM 混合）
- M5 竞赛：最优 ML 比最优统计基准准 22.4%（Makridakis et al., 2022）
- statsforecast：Apache-2.0，Nixtla，当前版本 2.0.3
- 2026 月度零售实测：ETS+ARIMA 组合 vs Chronos-Bolt，前者准确率高 14-16%（单数据集例证）
