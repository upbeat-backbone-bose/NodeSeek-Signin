# NodeSeek-Signin

<div align="center">
  
![NodeSeek](https://img.shields.io/badge/NodeSeek-自动签到-green)
![GitHub stars](https://img.shields.io/github/stars/upbeat-backbone-bose/NodeSeek-Signin?style=flat)
![Python](https://img.shields.io/badge/Language-Python-blue)
![License](https://img.shields.io/github/license/upbeat-backbone-bose/NodeSeek-Signin)

</div>


## 📝 项目介绍

这是一个用于 NodeSeek 论坛自动签到的工具，支持通过 GitHub Actions、青龙面板或 Docker Compose 进行定时自动签到操作，帮助用户轻松获取论坛每日"鸡腿"奖励。


## ✨ 功能特点

- 📅 支持 GitHub Actions 自动运行
- 🦉 支持青龙面板定时任务
- 🐳 支持 Docker Compose 一键部署
- 🍪 支持 Cookie 或账号密码登录方式
- 👥 支持多账号批量签到
- 🔐 支持多种验证码解决方案
  - 自建 CloudFreed 服务（免费）
  - YesCaptcha 商业服务（付费/赠送）
- 📱 支持多种通知推送渠道（可用 `NOTIFY_CONFIG_JSON` 一次性配置）

##  快速开始

1. **获取代码**：Fork/Clone 本仓库，或在青龙面板/Cloudflare Worker 等环境中拉取脚本。
2. **选择部署方式**：根据自己的运行环境（GitHub Actions、Docker、青龙、Cloudflare Worker）跳转到对应文档完成部署。
3. **配置变量**：按照 [`docs/configuration/config.md`](docs/configuration/config.md) 填写 `NS_COOKIE`、`USERn/PASSn`、验证码与通知变量；验证码方案差异见 [`docs/configuration/solutions.md`](docs/configuration/solutions.md)。
4. **验证运行**：在目标环境触发一次任务确认签到与通知均正常。`python test_run.py` 会执行真实签到并可能消耗验证码额度，请勿作为单元测试反复运行。

## 🧱 部署方式一览

| 场景 | 文档 | 说明 |
| --- | --- | --- |
| GitHub Actions | [`docs/deployment/github-actions.md`](docs/deployment/github-actions.md) | 适合纯云端运行；可选加密 Secret 回写（默认关闭） |
| Docker Compose / 本地服务器 | [`docs/deployment/docker-compose.md`](docs/deployment/docker-compose.md) | 支持 `RUN_AT` 定时和 `IN_DOCKER` 持久化 Cookie |
| 青龙面板 | [`docs/deployment/qinglong-panel.md`](docs/deployment/qinglong-panel.md) | 与青龙定时任务深度集成，沿用面板通知 |
| Cloudflare Worker | [`docs/deployment/cloudflare-worker.md`](docs/deployment/cloudflare-worker.md) | 适合无服务器场景，可配合第三方验证码服务 |
| Docker 镜像构建发布 | [`docs/deployment/docker.md`](docs/deployment/docker.md) | 发布 Release 时自动构建并推送到 Docker Hub |

> 🎯 以上文档包含详细步骤、示例命令及截图，README 仅保留概览。

## 📚 文档站（GitHub Pages）

仓库已提供 MkDocs 配置与 Pages 工作流：

- 配置文件：`mkdocs.yml`
- 发布工作流：`.github/workflows/docs-pages.yml`
- 文档目录：`docs/`（含 `docs/wiki/`）

首次启用请在 GitHub 仓库中设置：

1. 进入 `Settings -> Pages`
2. `Build and deployment` 选择 `GitHub Actions`

本地预览命令：

```bash
pip install -r requirements-dev.txt
mkdocs serve
```

## 配置小抄

### 账户与认证

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `NS_COOKIE` | 建议 | - | NodeSeek 论坛的用户 Cookie，多账号使用 `&` 或换行符分隔 |
| `USER`、`PASS` | 可选 | - | **第 1 个账号**的用户名和密码，Cookie 缺失或明确失效时自动登录 |
| `USER1`、`USER2`... | 可选 | - | 第 2、第 3... 个账号的用户名（必须连续设置） |
| `PASS1`、`PASS2`... | 可选 | - | 对应账号的密码 |

> 账号与 Cookie 按下标一一对应：`USER`/`PASS` 是第 1 个账号，`USER1`/`PASS1` 是第 2 个，以此类推。若只配置了 `USER1`/`PASS1`，则 `USER1` 就是第 1 个账号。数量不一致时脚本会打印告警。

### 签到配置

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `NS_RANDOM` | 可选 | false | 原样传给签到接口的 `random` 查询参数（不是布尔解析） |
| `RUN_AT` | 可选 | 09:00-21:00 | 每日运行时间，固定时间（`HH:MM`）或随机区间（`HH:MM-HH:MM`） |
| `TIMEOUT` | 可选 | 15 | 单次网络请求超时时间（秒） |
| `NS_IMPERSONATE` | 可选 | chrome146 | 首选浏览器指纹版本 |
| `NS_IMPERSONATE_ATTEMPTS` | 可选 | 3 | 指纹尝试次数（1-5），仅在 Cloudflare 挑战时切换 |
| `MAX_LOGIN_ATTEMPTS` | 可选 | 账号数与 Cookie 数中的较大者 | 每次运行最多重新登录次数，避免持续消耗验证码 |
| `STATS_MAX_PAGES` | 可选 | 20 | 签到统计最多查询页数（1-20）；窗口被截断时结果会标注"数据不完整" |
| `DEBUG` | 可选 | false | 开启后输出详细调试信息，**可能包含敏感上下文，默认关闭** |

### 验证码配置

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `SOLVER_TYPE` | 可选 | turnstile | 验证码解决方案（turnstile/yescaptcha） |
| `API_BASE_URL` | 条件必需 | - | CloudFreed 服务地址，当 `SOLVER_TYPE=turnstile` 时必填 |
| `CLIENT_KEY` | 必需 | - | 验证码服务客户端密钥 |

### 运行环境

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `IN_DOCKER` | 可选 | - | 设为 `true` 启用 Docker 环境，持久化 Cookie 到文件 |
| `GITHUB_ACTIONS` | 自动 | - | 由 GitHub Actions 自动设置，标识运行环境 |
| `GITHUB_REPOSITORY` | 自动 | - | 由 GitHub Actions 自动设置，格式为 `owner/repo` |

### 高级功能

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `GH_PAT` | 可选 | - | GitHub Personal Access Token，仅在开启加密 Secret 回写时需要 |
| `GH_COOKIE_WRITEBACK` | 可选 | false | 设为 `true` 后通过 GitHub Secrets API 加密更新 `NS_COOKIE`，不再写入明文 Variable |

### 通知配置

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `HITOKOTO` | 可选 | true | 启用一言（随机句子）作为通知后缀；请求失败不会影响主通知 |
| `CONSOLE` | 可选 | false | 启用控制台输出通知 |
| `NOTIFY_CONFIG_JSON` | 可选 | - | 用 JSON 一次性传入多个通知渠道配置，适合 CI |
| `NOTIFY_THREAD_TIMEOUT` | 可选 | 30 | 单个通知渠道最长等待时间（秒） |
| `SKIP_PUSH_TITLE` | 可选 | - | 跳过标题完全匹配的通知，多个标题用换行分隔 |

支持的推送渠道：Bark、钉钉机器人、飞书机器人、go-cqhttp、gotify、iGot、serverJ、PushDeer、Synology Chat、PushPlus、微加机器人、Qmsg、企业微信机器人、企业微信应用、Telegram、智能微秘书、SMTP 邮件、PushMe、CHRONOCAT、自定义 WebHook。详见 [`notify.py`](notify.py)。

> 完整变量说明请参阅 [配置文档](docs/configuration/config.md)。

## 🔐 安全说明

- `NS_COOKIE` 等同账号会话，请只放在 `.env`、系统环境变量或 GitHub **Secrets** 中，不要提交到仓库或写入 Actions Variables。
- GitHub 自动回写默认关闭；需要时设置 `GH_COOKIE_WRITEBACK=true`，脚本会通过 Secrets API 使用公钥加密后更新。
- Docker 容器以 UID/GID `1000` 运行，宿主机 `./cookie` 目录需允许该用户写入（例如 `sudo chown -R 1000:1000 ./cookie`）。
- Cloudflare Worker 的 `/checkin` 需要 `TRIGGER_TOKEN`；未配置时 HTTP 触发会返回 503。建议绑定 KV 以持久化 Cookie 并启用并发锁。

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。

- ✅ 允许分发和销售
- ✅ 允许修改和衍生作品
- ✅ 允许商业使用
- ⚠️ 必须保留原作者版权声明
- ⚠️ 本软件按"原样"提供，不提供任何担保

## ⚠️ 免责声明

本项目仅供学习交流使用，请遵守 NodeSeek 论坛的相关规定和条款。
