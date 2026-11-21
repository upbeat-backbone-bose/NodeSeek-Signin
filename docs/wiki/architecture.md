# 系统架构

## 1. 架构风格

项目采用“单仓库脚本 + 多运行环境适配”模式：

- 业务核心：`nodeseek_sign.py`
- 共享配置：`config.py`
- Cookie 存储：`cookie_store.py`
- 调度层：`scheduler.py`
- 能力插件：`turnstile_solver.py`、`yescaptcha.py`、`notify.py`
- 部署层：GitHub Actions、Docker Compose、青龙
- 独立实现：`nodeseek-cloudflare-worker.js`（Cloudflare Worker 方案）

不依赖 Web 服务框架或消息队列，主要通过环境变量驱动行为。

## 2. 关键组件

### 2.1 签到核心（nodeseek_sign.py）

- 读取账号、Cookie、验证码与运行配置。
- 支持多账号：`USER/PASS` 与 `USER1/PASS1...`。
- 支持多 Cookie：`NS_COOKIE` 可用 `&` 或换行分隔，空槽位会保留。
- 优先 Cookie 签到；只有 Cookie 明确失效时才走“验证码 + 登录 + 重试签到”。
- 查询近 30 天签到收益并拼接通知内容。
- 按运行环境回写最新 Cookie；GitHub 回写默认关闭并使用加密 Secret。

### 2.2 调度器（scheduler.py）

- 循环运行，不退出。
- 支持固定时间（`HH:MM`）或随机区间（`HH:MM-HH:MM`）。
- 默认读取 `RUN_AT=09:00-21:00`（代码默认值）；格式错误回退 `08:00-10:59`。
- 启动时若已处于随机区间内，会立即执行一次；执行完成后等待下一个窗口，不会在宽窗口内反复签到。
- 通过 `subprocess.Popen` 执行签到，带 `TASK_TIMEOUT`、信号转发、心跳文件和单实例锁。

### 2.3 验证码求解器

- `TurnstileSolver`: 对接自建兼容 API（如 CloudFreed 风格 `/createTask`、`/getTaskResult`）。
- `YesCaptchaSolver`: 对接 YesCaptcha 托管服务。
- 统一通过 `CLIENT_KEY` 读取密钥，校验 `API_BASE_URL`，终态错误立即退出。

### 2.4 通知模块（notify.py）

- 作为可选依赖动态导入：`from notify import send`。
- 导入失败不阻断签到主流程。
- 支持大量渠道，统一受 `TIMEOUT` 与相关环境变量控制；单个渠道失败或超时不影响其他渠道。

## 3. 运行时数据流

1. 加载配置：环境变量 + Docker Cookie 文件（若 `IN_DOCKER=true`）。
2. 账号对齐：账号数组与 Cookie 数组按索引补齐，保留空 Cookie 槽位。
3. 对每个账号执行：
   - `sign(cookie)`
   - 仅当状态为 `invalid` 且配置了账号密码时：`session_login(...) -> sign(new_cookie)`
4. 成功后执行 `get_signin_stats(cookie, 30)`。
5. 重新登录并重新签到成功后立即持久化；结束时再次统一保存。
6. 输出 `RESULT` JSON 汇总（`succeeded`/`already`/`failed` 互斥计数，
   `success` 为是否全部成功的布尔值）；存在失败账号时返回非零退出码。

## 4. 外部依赖边界

- NodeSeek API（签到、登录、积分流水）。
- 验证码服务 API（Turnstile/YesCaptcha）。
- GitHub API（更新加密 Actions Secret，条件触发）。
- 青龙 API（变量增删，条件触发）。
- 各通知服务 API（条件触发）。

## 5. 自动化与发布层

- `.github/workflows/blank.yml`
  - 每日定时 + 手动触发运行签到脚本。
  - 在运行器中注入账号、Cookie、验证码、通知相关环境变量。
- `.github/workflows/docker-publish.yml`
  - 在 Release 发布或手动触发时构建 Docker 镜像。
  - 可按输入参数控制是否推送到远程镜像仓库。
- `.github/workflows/update-actions.yml`
  - 校验 workflow 中的 action 是否固定到完整 commit SHA（要求 40 位十六进制）。
- `.github/workflows/docs-pages.yml`
  - 构建并发布 GitHub Pages 文档站（`mkdocs build --strict`）。
- `.github/workflows/tests.yml`
  - 在 Python 3.11 / 3.14 上运行 pytest，并运行 Worker 的 `node --test`。

## 6. 设计特征与约束

- 指纹降级：仅在 Cloudflare 挑战时切换有限的 `impersonate` 候选（默认最多 3 个）。
- 容错优先：单账号失败不阻断其他账号；传输异常不会重复提交签到 POST。
- 配置即行为：运行方式和存储介质完全由环境变量决定。
- 安全约束：默认关闭 debug；Cookie 原子写入且权限为 0600；GitHub 回写默认关闭。
