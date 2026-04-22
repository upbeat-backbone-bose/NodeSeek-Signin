# 接口说明

## 1. 运行入口接口

- 一次性签到：`python nodeseek_sign.py`
- 加载 `.env` 的本地验证：`python test_run.py`
- 定时循环调度：`python scheduler.py`
- Docker Compose 默认命令：`python scheduler.py`
- Cloudflare Worker 入口：`fetch()` / `scheduled()`（`nodeseek-cloudflare-worker.js`）

## 2. 环境变量接口

### 2.1 账号与 Cookie

- `NS_COOKIE`: 多账号 Cookie，支持 `&` 或换行分隔。
- `USER` / `PASS`: 主账号用户名密码。
- `USER1/PASS1`, `USER2/PASS2`...: 多账号扩展。

### 2.2 验证码

- `SOLVER_TYPE`: `turnstile` 或 `yescaptcha`，默认 `turnstile`。
- `API_BASE_URL`: 验证码服务地址（turnstile 模式必需）。
- `CLIENTT_KEY`: 验证码服务密钥（名称固定，双 T）。

### 2.3 网络与调试

- `TIMEOUT`: 请求超时秒数，默认 15。
- `DEBUG`: 调试开关（`true/1/yes` 为开启）。
- `NS_IMPERSONATE`: 首选浏览器指纹版本，默认 `chrome146`。

### 2.4 调度与运行环境

- `RUN_AT`: 调度时间配置，支持 `HH:MM` 或 `HH:MM-HH:MM`。
- `IN_DOCKER=true`: 启用 Docker 模式 Cookie 文件读写。
- `GITHUB_ACTIONS`, `GITHUB_REPOSITORY`, `GH_PAT`: 用于 GitHub 环境识别与回写变量。

### 2.5 通知

`notify.py` 读取大量推送变量（如 `TG_BOT_TOKEN`、`TG_USER_ID`、`BARK_PUSH`、`PUSH_KEY` 等），并提供统一 `send(title, content)` 对外接口。

## 3. 文件接口

- Docker Cookie 文件：`cookie/NS_COOKIE.txt`
- 读取条件：`IN_DOCKER=true`
- 写入触发：Cookie 更新后调用 `save_cookie(...)`

## 4. 对外 HTTP API（被调用）

### 4.1 NodeSeek

- `POST https://www.nodeseek.com/api/account/signIn`
  - 用途：账号密码 + Turnstile token 登录
- `POST https://www.nodeseek.com/api/attendance?random=<value>`
  - 用途：签到
- `GET https://www.nodeseek.com/api/account/credit/page-<n>`
  - 用途：查询积分流水并统计签到收益

### 4.2 验证码服务

- Turnstile 通用：
  - `POST <API_BASE_URL>/createTask`
  - `POST <API_BASE_URL>/getTaskResult`
- YesCaptcha：同路径语义，载荷格式按 YesCaptcha 规范。

### 4.3 GitHub API

- `PATCH /repos/{owner}/{repo}/actions/variables/{name}`
- `POST /repos/{owner}/{repo}/actions/variables`
- 用途：更新或创建 `NS_COOKIE` 变量。

## 5. 子流程调用接口

- `scheduler.py -> nodeseek_sign.py`: `subprocess.run`
- `nodeseek_sign.py -> notify.py`: 动态导入 `send`
- `nodeseek_sign.py -> solver`: `TurnstileSolver.solve()` / `YesCaptchaSolver.solve()`

## 6. CI 接口（GitHub Actions）

- 工作流文件：`.github/workflows/*.yml`
- 主要行为：
  - 触发 `nodeseek_sign.py` 执行签到
  - 构建并可选推送 Docker 镜像
  - 生成 actions 版本升级报告
