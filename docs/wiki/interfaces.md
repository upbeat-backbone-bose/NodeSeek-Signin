# 接口说明

## 1. 运行入口接口

- 一次性签到：`python nodeseek_sign.py`（失败时返回非零退出码）
- 加载 `.env` 的本地验证：`python test_run.py`
- 定时循环调度：`python scheduler.py`
- Docker Compose 默认命令：`python scheduler.py`
- Cloudflare Worker 入口：`fetch()` / `scheduled()`（`nodeseek-cloudflare-worker.js`）

## 2. 环境变量接口

所有 Python 模块通过 `config.py` 读取变量，避免各自的默认值漂移。

### 2.1 账号与 Cookie

- `NS_COOKIE`: 多账号 Cookie，支持 `&` 或换行分隔；空槽位（`a&&c`）会保留。
  末尾多余的分隔符会被忽略，不会多出账号。
- `USER` / `PASS`: **第 1 个账号**的用户名密码。
- `USER1/PASS1`, `USER2/PASS2`...: 第 2、第 3... 个账号，与 Cookie 列表按索引对应，
  必须连续设置。若未设置 `USER`/`PASS`，则 `USER1` 即为第 1 个账号。
  账号数量与 Cookie 数量不一致时脚本会打印错位告警；账号数多于 Cookie 数时，
  多出来的账号没有可信的槽位身份，直接计为失败且不进入验证码登录流程。

### 2.2 验证码

- `SOLVER_TYPE`: `turnstile` 或 `yescaptcha`，默认 `turnstile`。
- `API_BASE_URL`: 验证码服务地址（必须是 http/https）。
- `CLIENT_KEY`: 验证码服务密钥。

### 2.3 网络、指纹与调试

- `TIMEOUT`: 请求超时秒数，默认 15。
- `DEBUG`: 调试开关（`true/1/yes/on` 为开启）。
- `NS_IMPERSONATE`: 首选浏览器指纹版本，默认 `chrome146`。
- `NS_IMPERSONATE_ATTEMPTS`: 指纹尝试次数，默认 3，范围 1-5。
- `MAX_LOGIN_ATTEMPTS`: 单次运行最多重新登录次数。
- `STATS_MAX_PAGES`: 签到统计最多查询页数，默认 20，范围 1-20。调低会截断窗口，结果会标注"数据不完整"。

### 2.4 调度与运行环境

- `RUN_AT`: 调度时间配置，支持 `HH:MM` 或 `HH:MM-HH:MM`。
- `TASK_TIMEOUT`: 签到子进程最长运行时间，默认 1800 秒。
- `SCHEDULER_SLEEP_CHUNK`: 调度器分段休眠时长，默认 60 秒。
- `HEARTBEAT_FILE`: 心跳文件路径，默认 `./cookie/heartbeat`。
- `SCHEDULER_LOCK_FILE`: 单实例锁文件路径。
- `IN_DOCKER=true`: 启用 Docker 模式 Cookie 文件读写。
- `GITHUB_ACTIONS`, `GITHUB_REPOSITORY`, `GH_PAT`: 用于 GitHub 环境识别与加密 Secret 回写。
- `GH_COOKIE_WRITEBACK`: 默认 `false`；设为 `true` 才启用回写。

### 2.5 通知

`notify.py` 读取大量推送变量（如 `TG_BOT_TOKEN`、`TG_USER_ID`、`BARK_PUSH`、`PUSH_KEY` 等），并提供统一 `send(title, content)` 对外接口。`NOTIFY_CONFIG_JSON` 可一次性覆盖多个渠道配置（仅覆盖 `push_config` 中已存在的键；新增渠道必须先在 `push_config` 中登记），`NOTIFY_THREAD_TIMEOUT` 控制单渠道最长等待时间。

## 3. 文件接口

- Docker Cookie 文件：`cookie/NS_COOKIE.txt`
- 读取条件：`IN_DOCKER=true`
- 写入方式：原子替换，权限 `0600`
- 调度器心跳：`cookie/heartbeat`（默认路径，用于 Docker healthcheck）

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

- `GET /repos/{owner}/{repo}/actions/secrets/public-key`
- `PUT /repos/{owner}/{repo}/actions/secrets/{name}`
- 用途：使用公钥加密后更新 `NS_COOKIE` Secret；默认关闭。

### 4.4 青龙 API

- 通过任务预加载注入的全局 `QLAPI` 调用 `getEnvs` / `deleteEnvs` / `createEnv`；不可用时跳过。

## 5. 子流程调用接口

- `scheduler.py -> nodeseek_sign.py`: `subprocess.Popen`（绝对路径、带超时与信号转发）
- `nodeseek_sign.py -> notify.py`: 动态导入 `send`
- `nodeseek_sign.py -> solver`: `TurnstileSolver.solve()` / `YesCaptchaSolver.solve()`
- `nodeseek_sign.py -> cookie_store.py`: 解析、对齐与原子持久化 Cookie

## 6. CI 接口（GitHub Actions）

- 工作流文件：`.github/workflows/*.yml`
- 主要行为：
  - 触发 `nodeseek_sign.py` 执行签到
  - 构建并可选推送 Docker 镜像
  - 运行 pytest（Python 3.11 / 3.14）
  - 校验 Actions 是否固定到 commit SHA
