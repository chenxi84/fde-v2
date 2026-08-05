# 快速上手

## 一、创建应用

### 1.1 准备业务说明

在 `app/` 下创建应用组目录（英文 snake_case，如 `my_app`），并在其中创建 `brd/` 子目录，放入业务说明文件（Markdown / HTML / 图片均可，内容越完整越好）：

```
app/
└── my_app/              # 你的应用组
    └── brd/             # 业务说明放这里
        └── 业务需求.md   # 背景、主流程、涉及数据、角色等
```

> 参考：`app/e2e/` 是一个完整的样例，含架构设计、应用代码、前端页面等，可对照理解产物长什么样。

### 1.2 用 AI 代理构建应用

将下面这句话发给 Claude Code 或其他 AI 代理工具：

```
按 design/工具链使用说明.md 逐步执行，为应用组 my_app 构建完整的后端和前端。
业务说明在 app/my_app/brd/ 里。
```

AI 代理会按九步法自动推进（架构设计 → 应用详设 → 编码 → 测试 → 前端设计 → 前端编码 → 前端测试），只需在第①步（应用划分）和第②步（字段/规则）两处把关确认即可。

---

## 二、运行

```bash
# 1. （可选）配置 LLM——复制模板并按需填写，不配置也不影响基本使用
cp config/.env.example config/.env

# 2. 启动
python main.py
```

浏览器访问 **http://127.0.0.1:4000**，默认账号 **admin / admin**（首次登录后建议改密）。

---

## 三、Docker 部署（可选）

适合部署到 Linux 服务器，无需手动安装 Python 和依赖。

### 内网 HTTP（简单）

```bash
docker build -t fde-v2 .
docker run -d --restart=always -p 4000:4000 \
  -v $(pwd)/app:/app/app -v $(pwd)/config:/app/config \
  --name fde-v2 fde-v2
```

### 带 HTTPS（nginx 反向代理）

```bash
# 1. 生成自签证书
bash scripts/gen-cert.sh

# 2. 启动（FDE + nginx 两个容器）
docker compose up -d
```

访问 `https://<服务器IP>`。自签证书浏览器会提示不安全，点「继续访问」即可；有域名的话把真实证书放到 `certs/` 下替换。

### 更新代码

```bash
docker compose down
docker compose up -d --build
```

> 如果服务器在国内且 Docker Hub 连接超时，需先配置镜像加速（见 Dockerfile 和 daemon.json）。

---

## 四、使用

| 入口 | 地址 / 方式 | 用途 |
|---|---|---|
| Web 控制台 | `http://127.0.0.1:4000` | 应用清单、手工调用服务、管理用户/角色、定时任务 |
| AI Agent | 控制台内 `/agent` 页 | 对话式操作应用（需配置 LLM） |
| MCP 服务 | `python -m fde_platform.mcp_server` | 供外部 AI 工具通过 MCP 协议调用应用 |
| REST API | `http://127.0.0.1:4000/api/<应用>/<服务>` | 程序化调用 |

---

## 附：目录结构速览

```
fde-v2/
├── main.py                  # 启动入口
├── app/                     # 所有应用（你创建的也在这）
│   └── e2e/                 #   参考样例
├── design/                  # 九步法工具链规格
│   ├── CONVENTION.md        #   后端编码约定
│   ├── VIEW_CONVENTION.md   #   前端编码约定
│   └── 工具链使用说明.md     #   ★ 构建操作手册
├── config/
│   └── .env.example         # 配置模板
└── fde_platform/            # 平台引擎（一般不动）
```
