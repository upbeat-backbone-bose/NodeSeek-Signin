# NodeSeek-Signin

<div align="center">
  
![NodeSeek](https://img.shields.io/badge/NodeSeek-自动签到-green)
![GitHub stars](https://img.shields.io/github/stars/upbeat-backbone-bose/NodeSeek-Signin?style=flat)
![Python](https://img.shields.io/badge/Language-Python-blue)
![License](https://img.shields.io/github/license/upbeat-backbone-bose/NodeSeek-Signin)

</div>


## 📝 项目介绍

这是一个用于 NodeSeek 论坛自动签到的工具，支持通过 GitHub Actions、青龙面板或 Docker Compose 进行定时自动签到操作。签到模式默认为随机签到，帮助用户轻松获取论坛每日"鸡腿"奖励。


## ✨ 功能特点

- 📅 支持 GitHub Actions 自动运行
- 🦉 支持青龙面板定时任务
- 🐳 支持 Docker Compose 一键部署
- 🍪 支持 Cookie 或账号密码登录方式
- 👥 支持多账号批量签到
- 🔐 支持多种验证码解决方案
  - 自建 CloudFreed 服务（免费）
  - YesCaptcha 商业服务（付费/赠送）
- 📱 支持多种通知推送渠道(需在blank.yml添加对应变量)

##  快速开始

1. **获取代码**：Fork/Clone 本仓库，或在青龙面板/Cloudflare Worker 等环境中拉取脚本。
2. **选择部署方式**：根据自己的运行环境（GitHub Actions、Docker、青龙、Cloudflare Worker）跳转到对应文档完成部署。
3. **配置变量**：按照 [`docs/configuration/config.md`](docs/configuration/config.md) 填写 `NS_COOKIE`、`USERn/PASSn`、验证码与通知变量；验证码方案差异见 [`docs/configuration/solutions.md`](docs/configuration/solutions.md)。
4. **验证运行**：在目标环境触发一次任务（或运行 `python test_run.py`）确认签到与通知均正常。

## 🧱 部署方式一览

| 场景 | 文档 | 说明 |
| --- | --- | --- |
| GitHub Actions | [`docs/deployment/github-actions.md`](docs/deployment/github-actions.md) | 适合纯云端运行，可结合 `GH_PAT` 自动回写 Cookie |
| Docker Compose / 本地服务器 | [`docs/deployment/docker-compose.md`](docs/deployment/docker-compose.md) | 支持 `RUN_AT` 定时和 `IN_DOCKER` 持久化 Cookie |
| 青龙面板 | [`docs/deployment/qinglong-panel.md`](docs/deployment/qinglong-panel.md) | 与青龙定时任务深度集成，沿用面板通知 |
| Cloudflare Worker | [`docs/deployment/cloudflare-worker.md`](docs/deployment/cloudflare-worker.md) | 适合无服务器场景，可配合第三方验证码服务 |

> 🎯 以上文档包含详细步骤、示例命令及截图，README 仅保留概览。

## 配置小抄

### 账户与认证

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `NS_COOKIE` | 建议 | - | NodeSeek 论坛的用户 Cookie，多账号使用 `&` 或换行符分隔 |
| `USER`、`PASS` | 可选 | - | 单账号用户名和密码，Cookie 失效时自动登录 |
| `USER1`、`USER2`... | 可选 | - | 多账号用户名，当 Cookie 失效时使用 |
| `PASS1`、`PASS2`... | 可选 | - | 多账号密码 |

### 签到配置

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `NS_RANDOM` | 可选 | true | 是否随机签到（true/false） |
| `RUN_AT` | 可选 | `09:00-21:00` | **仅 Docker Compose 可用**。设置定时任务执行时间，支持固定时间 `10:30` 或时间范围 `10:00-18:00` |
| `TIMEOUT` | 可选 | 15 | 网络请求超时时间（秒），避免目标服务异常时请求卡死 |
| `NS_IMPERSONATE` | 可选 | chrome146 | 浏览器指纹版本，用于绕过 Cloudflare 检测 |
| `DEBUG` | 可选 | false | 开启后输出详细调试信息（异常详情、API 响应等），**默认关闭以保护敏感信息安全** |

### 验证码配置

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `SOLVER_TYPE` | 可选 | turnstile | 验证码解决方案（turnstile/yescaptcha） |
| `API_BASE_URL` | 条件必需 | - | CloudFreed 服务地址，当 `SOLVER_TYPE=turnstile` 时必填 |
| `CLIENTT_KEY` | 必需 | - | 验证码服务客户端密钥 |

### 运行环境

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `IN_DOCKER` | 可选 | - | 设为 `true` 启用 Docker 环境，持久化 Cookie 到文件 |
| `GITHUB_ACTIONS` | 自动 | - | 由 GitHub Actions 自动设置，标识运行环境 |
| `GITHUB_REPOSITORY` | 自动 | - | 由 GitHub Actions 自动设置，格式为 `owner/repo` |

### 高级功能

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `GH_PAT` | 可选 | - | GitHub Personal Access Token，用于自动更新 Cookie 变量至仓库 [Actions Variables](docs/deployment/github-actions.md) |

### 通知配置

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `HITOKOTO` | 可选 | true | 启用一言（随机句子）作为通知前缀 |
| `CONSOLE` | 可选 | false | 启用控制台输出通知 |
| `SKIP_PUSH_TITLE` | 可选 | - | 跳过包含指定标题的通知，多个标题用换行分隔 |

支持的推送渠道：Bark、钉钉机器人、飞书机器人、go-cqhttp、gotify、iGot、serverJ、PushDeer、PushPlus、微加机器人、Qmsg、企业微信机器人、企业微信应用、Telegram、智能微秘书、SMTP 邮件、PushMe、CHRONOCAT、自定义 WebHook。详见 [`notify.py`](notify.py)。

> 完整变量说明请参阅 [配置文档](docs/configuration/config.md)。

## ⚠️ 免责声明

本项目仅供学习交流使用，请遵守 NodeSeek 论坛的相关规定和条款。
