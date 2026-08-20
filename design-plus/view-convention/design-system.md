# 设计系统（Design System）

工业控制台气质：墨青侧栏 + 暖纸画布 + 蓝图网格底纹；正文系统黑体，**数据/单号一律等宽字体**（`var(--mono)` + tabular-nums）。

**规范表 = `fde_platform/static/fde.css`（全局唯一一份）**：令牌 + SPA 组件 + 平台渲染页组件层（末段，裸元素样式以 `.pf` 作用域隔离）。两类消费者：平台渲染页（base.html 族，含登录页——登录在鉴权之前，样式必须经 `/static/` 白名单可达）直接引用；view/ SPA 经 `view/lib/styles.css` 的**一行 `@import` 别名**引用。新增组件类追加在规范表（属公共层演进，向用户说明），勿在别名文件或模板内联样式里扩写。

## 令牌（:root）

```css
--ink: #0e1b2a      /* 侧栏/模态头带 墨青 */     --ink-2: #14263a
--canvas: #f1f3ef   /* 画布 暖纸 */              --card: #fff
--line: #dde2d9     /* 分隔线 */                 --fg: #1c2733  --muted: #69758a
--prime: #175e54    /* 主操作 松绿 */            --prime-deep: #0f4a42
--amber: #d97706    /* 强调/同步按钮 熔琥珀 */    --amber-soft: #fdf3e3
--mono: ui-monospace, "Cascadia Code", "JetBrains Mono", Consolas, monospace
--sans: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", …
```

状态色语义：`green`=完成/成功、`amber`=进行中/待办（带 pulse 动画）、`red`=失败/退回/已撤回、`blue`=流程中态（已提交/审批中）、`teal`=入库/内销类、`slate`=中性。

## 布局骨架

- `body` flex：`aside.rail`（212px 墨青侧栏，sticky 100vh）+ `.stage`（flex:1）。
- `.stage` 底纹 = 双色微光 radial + 双向 24px 网格线 + canvas 底色（分层氛围背景，勿删）。
- `header.top`：页面标题（20px/800）+ `.crumb` 副题 + 右侧 `.uchip` 用户胶囊；sticky + 半透明 blur。
- `main`：max-width 1280 居中。
- 侧栏项 `.nav-item`：左 3px 透明边条，`.on` 态 = 琥珀底 + 左边条 + 加粗。

## 组件目录（类名 → 用途）

| 类 | 用途 / 要点 |
|---|---|
| `.card` + `.hd`/`.bd` | 白色圆角 12 卡片；`.hd` 标题行（h3 14px/800 + `.hint` + 右侧按钮），`.bd` 内容 |
| `.kv` + `.k`/`.v` | 键值网格（auto-fit 158px 列）；`.v.mono` 数据值；长字段 `grid-column: span 2` |
| `.sec` | 模态/区块内小节标题（11px 字距加宽 muted） |
| `.tbl` / `.tbl.tight` | 表格；`.tight` 5px/8px 紧凑版（子账本用）；行 `.data` hover 高亮 + `.rowact` 行内操作（默认淡化 opacity .35，hover 提至 1） |
| `.b-link` | 单号链接按钮（松绿加粗等宽，hover 下划线变琥珀）——**所有可点单号统一用它** |
| `.modal-mask`/`.modal` | 遮罩（rgba 墨青 + blur，fade-in）+ 面板（900px，modalin 缩放浮起）；`.modal-hd` 墨青头带（`.docno` 21px 等宽 + `.sub` + `.x` 关闭钮 hover 旋转 90°）；`.modal-bd`（68vh 滚动）；`.modal-ft` 浅底操作条 |
| `.loadbox` + `.spin` | 模态加载态（居中旋转 ◌） |
| `.st` + `.st-<色>` | 状态徽章（圆点 + 文字，`.st-live`/amber 点带 pulse） |
| `.fchip` | 过滤 chip；`.on` = 墨青底琥珀字 |
| `.badge-grade` | 客户等级小徽章（蓝底等宽） |
| `label.f` + `.req` | 表单标签（11.5px muted 加粗；红星 `.req`） |
| `.frow` | 表单网格（auto-fit 150px 列） |
| `.collapse` + `.open` | 折叠面板（max-height 过渡）——「更多字段 ▾」/新建表单容器 |
| `.tagline` | 行内 flex 布局（标题行/操作行，`.right` 靠右） |
| `.chipline` + `.chip` | 行内标签串（DN 清单等） |
| `pre.json` + `details.raw` | 原始数据折叠块（深底等宽） |
| 按钮族 | `.b-pri`(松绿) `.b-amb`(琥珀) `.b-ghost`(白描边) `.b-dng`(红描边) `.b-sm`(小)；active 缩放 .97 |
| `.toast` | 右下角提示（墨青底，左边条按 kind 变色，slide-in） |
| `.empty` | 表格空态文案 |
| `[x-cloak]` | 未初始化隐藏（模态必加） |

## 动效约定

- 页面切换：`.page-in`（fade + 上移 10px，.28s）——平台通用壳的单一挂载点已给每页包好。
- 模态：maskin（.18s）+ modalin（.24s 缩放浮起）。
- 卡片/管道列 hover：上浮 2px + 阴影；按钮 hover 亮度/描边变化 + active 缩放。
- 进行中状态点 pulse；加载 `.spin` 旋转。
- 新增动效保持同一缓动 `cubic-bezier(.22,.9,.36,1)`、时长 ≤ .3s，勿做花哨转场。

## 排版对比

- 页面标题 20px/800、卡片标题 14px/800、正文 13.5px、标签 11.5px、小节标题 11px 字距 .16em——**大重量标题 + 小字距标签**是主要对比手段。
- 单号/数值/时间一律 `.mono` + `font-variant-numeric: tabular-nums`。

## 禁忌（勿引入）

紫/靛渐变、玻璃拟态全站化、纯黑+霓虹、Inter 单字体、居中 hero 三件套——本系统是工具型工作台，保持信息密度与克制。
