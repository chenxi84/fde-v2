# AgentScope 原生接入方案（不保留旧 agent）

> 状态：设计提案（未落地）· 日期 2026-08-21
> 目标：用 **AgentScope 2.0** 替换 FDE 现有 ReAct agent，作为平台的「编排 + 规划 + 自进化 skill」层；
> FDE 平台继续当「工具 + 身份 + 运行时」，核心解释器一行不碰。

---

## 0. 目标与原则

1. **AgentScope 是插拔组件**：像 auth / scheduler / llm 一样，以「import 失败即回落」或配置开关接入，可卸载。
2. **不保留旧 agent 的契约**：不硬套 `/api/agent/*` 请求/响应 + progress 轮询 + chatstore，直接采用 AgentScope 原生事件/状态/skill API，前端重建为薄客户端。
3. **FDE 的护城河不动**：`platform.call`（按名跨应用）、服务级授权、`ctx` 身份注入、内置文件工具、视图装配，全部保留。
4. **可回退**：旧 agent 代码先不删，用配置开关切回，灰度过审后再下线。

---

## 1. 删 / 留清单

### 删（旧 agent 的「壳」）
| 对象 | 理由 |
|---|---|
| `fde_platform/agent.py` 的 `AgentSession` | ReAct 循环、`MAX_ROUNDS`、`round_sigs` 死循环检测——AgentScope HarnessAgent 自带 |
| `/api/agent/progress` 轮询契约 | AgentScope 是事件流，硬套轮询要写 shim |
| `chatstore.py` 会话持久化 | AgentScope state（sessionId 跨进程恢复）取代 |
| `view/pages/agent.js/.html`、`agent_rail.js/.html` 旧实现 | 重建为 AgentScope 原生客户端 |
| `templates/chat_widget.html`（app 详情页聊天组件） | 同上 |

### 留（FDE 的编排资产，桥接进 AgentScope）
| 对象 | 去向 |
|---|---|
| system prompt 组装（服务目录 + 架构设计文档） | 注入 AgentScope 的 `sys_prompt` |
| 服务→工具定义 + 授权过滤（`all_mcp_tools` / `introspect.to_mcp_tool`） | 喂进 AgentScope 的 Toolkit |
| 工具执行 `platform.call(ctx=当前用户)` fail-closed | AgentScope 工具回调 |
| 内置文件工具 `builtin_tools`（parse/read/write/list） | 一并纳入 Toolkit |

---

## 2. 边界与职责

```
用户 / 前端（右栏 + 整页 + 管理页）
   ↓
AgentScope 2.0（插拔组件）
   ├─ HarnessAgent + Plan Mode（任务拆解 / 步骤决策）
   ├─ Skill 四层合成（自进化程序性记忆）
   ├─ 统一重试 + 备用模型（异常回退）
   ├─ Permission 三态（工具护栏，可接 FDE 授权）
   └─ 事件流 / HITL / 状态恢复
   ↓ 自定义 FDE Toolkit（桥接层）
FDE 平台（运行时）
   ├─ platform.call（按名跨应用 + 服务级授权 + ctx）
   ├─ builtin_tools（文件）
   └─ 视图装配 / 页面鉴权
```

**核心原则**：AgentScope 只负责「怎么编排 + 怎么记 skill」，FDE 负责「有哪些工具 + 谁有权调用 + 数据怎么读写」。

---

## 3. FDE Toolkit 桥接层（核心接缝）

这是整个改造里**唯一绕不开、也最需要做对**的部分。

1. **工具清单动态生成**：每次请求按**当前登录用户的服务授权**，用 `platform.all_mcp_tools()` + 授权过滤实时生成 Toolkit，**不能启动时缓存一次**（授权随用户变）。
2. **工具执行回调**：AgentScope 调工具 → 回调 `platform.call(app, service, ctx=当前用户, **args)`，返回结果喂回 AgentScope。
3. **身份/授权**：HTTP 入口由 FDE 的 auth gate 挡在前面（先登录、先过页面/服务授权）；AgentScope 内不重复鉴权，或把 AgentScope 的 Permission 三态映射到 FDE 服务级授权做「执行前拦截」。
4. **system prompt**：FDE 组装「当前身份可见的服务目录 + 各组架构设计文档」，注入 AgentScope 的 `sys_prompt`，让 AgentScope 跨应用编排有依据。

---

## 4. 前端重建

| 页面 | 做法 |
|---|---|
| **右栏 agent_rail** | 重建为对接 AgentScope 事件/SSE 的薄客户端：流式回复、工具调用事件、HITL 审批、skill「沉淀」按钮 |
| **整页 agent** | 可选，作「工作台」：会话、skill 库浏览、运行观测 |
| **管理页（新）** | 模型/备用模型、skill 库（草稿→审批→发布、评分、版本）、Permission 规则、会话/运行观测 |
| **壳事件** | 保留 `fde:agent-open` / `fde:agent-prompt`（流程总览的「Agent 分析下一步」仍可用），指向新客户端 |

---

## 5. 会话 / skill 库 / 模型归属

| 项 | 归属 | 说明 |
|---|---|---|
| 会话状态 | AgentScope state | sessionId 跨进程恢复；不再用 chatstore |
| skill 库 | AgentScope Skill 合成 + FDE 侧存储 | 半自动：agent 提议 → 人工审批 → 发布；评分/版本 |
| LLM 配置 | AgentScope 模型层 | Qwen / OpenAI 兼容 / Anthropic；复用 `.env` 或管理页 |
| 文件 | FDE builtin_tools | parse_table（新增，确定性解析）/ read / write / list |

---

## 6. 两个 PoC 验证用例

1. **智能问数**：自然语言「上月各物料销量」→ AgentScope 经 Toolkit 调 `sales_history.history_sequence` / `sales_forecast.get_summary` 求和 → 回答。验证：工具桥接、授权过滤、跨应用编排。
2. **文档导入 + skill 沉淀**：上传 xlsx/csv → AgentScope 调 `parse_table`（确定性解析）+ 列映射 + `import_orig_qty`；**第二次同类文件直接复用已沉淀的 skill**。验证：确定性解析、skill 沉淀/复用/进化。

---

## 7. 落地顺序（分阶段）

- **Phase 0 · PoC**：`agent_agentscope.py` 后端（FDE Toolkit 桥接 + platform.call 回调）+ 两条用例跑通。
- **Phase 1 · 前端重建**：右栏薄客户端 + 管理页；保留旧 agent 开关可切回。
- **Phase 2 · 治理**：skill 审批/版本/评分、会话迁移、Permission 规则。
- **Phase 3 · 灰度替换**：切默认后端为 AgentScope → 下线旧 agent。

---

## 8. 风险与回退

| 风险 | 对策 |
|---|---|
| 工具清单动态刷新的性能 | 按用户授权结果缓存 + 授权变更失效；PoC 压测 |
| AgentScope 版本耦合（2.0 是 breaking 大版本） | 锁定版本，封装在 `agent_agentscope.py` 内 |
| 桥接层 bug 影响全平台 agent | 配置开关切回旧 agent；新旧并行灰度过审 |
| skill 自动沉淀质量（成功≠正确） | 半自动：草稿 → 人工审批 → 发布，永不无审批直接执行 |
