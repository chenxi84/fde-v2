# FDE v2 待改造任务清单

## ✅ 已完成

| 项目 | 说明 |
|---|---|
| 数据库双模 | SQLite ↔ PostgreSQL，DDL 翻译 + cursor wrapper |
| 日志系统 | `config/logs/fde.log`，按天轮转保留 30 天 |
| Session 密钥 | 未配置时自动生成随机密钥持久化 |
| 首次改密 | admin/admin 登录后强制跳转改密页 |
| HTTP→HTTPS | nginx 反向代理 + 自签证书 |
| Docker 部署 | docker-compose：FDE + PostgreSQL + nginx |
| 应急部署 | docker-compose-simple.yml：单容器，零外部依赖 |
| PG 连接重试 | 启动时等待 PG 就绪（5 次 × 3 秒） |
| 启动横幅 | 显示数据库模式、版本号 |
| /groupbuild 移除 | 删除平台构建功能，保留 design/ 手工轨 |

---

## 🔴 P0 — 国际化（平台层）

| # | 任务 | 文件 | 工作量 |
|---|---|---|---|
| I1 | 新增 `view/lib/i18n.js` | 翻译函数 + 语言检测 | ~50 行 |
| I2 | 平台模板国际化 | login/base/users/scheduler/index/error 等 8 个模板 | ~80 处替换 |
| I3 | 平台错误消息国际化 | auth.py / users.py / runtime.py 的 `"xxx"` 中文消息 | ~30 处 |
| I4 | 新增 `fde_platform/i18n.py` | 翻译字典（zh/en 初稿） | ~100 行 |
| I5 | 语言切换 UI | `view_shell.html` 加语言切换器 + base.html 导航 | ~15 行 |

---

## 🟡 P1 — 生产就绪

| # | 任务 | 说明 | 工作量 |
|---|---|---|---|
| P1 | 登录限流 | 5 次/分钟/IP，防暴力破解 | Flask-Limiter ~20 行 |
| P2 | 密码强度 | 至少 8 位 + 字符类型混用 | users.py ~10 行 |
| P3 | CSRF 保护 | Cookie `SameSite=Strict` + 表单 token | auth.py ~30 行 |
| P4 | 健康检查端点 | `/health` 返回 200 + DB 连通性 | web.py ~15 行 |
| P5 | favicon | 加个图标，去掉 404 | 1 个文件 |
| P6 | CONVENTION 英文版 | `design/CONVENTION_EN.md` | 翻译 |
| P7 | i18n 应用层支持 | 应用 view.js 可选加载翻译表 | 已有 i18n.js，应用改 5 行 |

---

## 🟢 P2 — 运维体验

| # | 任务 | 说明 | 工作量 |
|---|---|---|---|
| O1 | 部署脚本 `scripts/deploy.sh` | git pull → build → health check → 告警 | ~30 行 |
| O2 | 数据库备份脚本 | SQLite `.backup` + PG `pg_dump` 定时执行 | ~40 行 |
| O3 | 错误追踪 | Sentry SDK 可选接入 | ~20 行 |
| O4 | 页面标题动态化 | `<title>` 跟随 `PLATFORM_TITLE` 环境变量 | web.py ~5 行 |

---

## 🔵 P3 — 体验优化

| # | 任务 | 说明 |
|---|---|---|
| U1 | 会话超时 | Flask session 持久化 + 过期时间 |
| U2 | 批量操作 | 用户管理支持批量导 CSV |
| U3 | API 文档 | 内省自动生成 Swagger |
| U4 | 移动端适配 | 响应式 CSS 优化 |
