# 系统架构

## 1. 架构风格

项目采用“单仓库脚本 + 多运行环境适配”模式：

- 业务核心：`nodeseek_sign.py`
- 调度层：`scheduler.py`
- 能力插件：`turnstile_solver.py`、`yescaptcha.py`、`notify.py`
- 部署层：GitHub Actions、Docker Compose、青龙
- 独立实现：`nodeseek-cloudflare-worker.js`（Cloudflare Worker 方案）

不依赖 Web 服务框架或消息队列，主要通过环境变量驱动行为。

## 2. 关键组件

### 2.1 签到核心（nodeseek_sign.py）

- 读取账号、Cookie、验证码与运行配置。
- 支持多账号：`USER/PASS` 与 `USER1/PASS1...`。
- 支持多 Cookie：`NS_COOKIE` 可用 `&` 或换行分隔。
- 优先 Cookie 签到，失败后走“验证码 + 登录 + 重试签到”。
- 查询近 30 天签到收益并拼接通知内容。
- 按运行环境回写最新 Cookie。

### 2.2 调度器（scheduler.py）

- 循环运行，不退出。
- 支持固定时间（`HH:MM`）或随机区间（`HH:MM-HH:MM`）。
- 默认读取 `RUN_AT=09:00-21:00`（代码默认值）。
- 每次触发通过 `subprocess.run([sys.executable, "nodeseek_sign.py"])` 执行签到。

### 2.3 验证码求解器

- `TurnstileSolver`: 对接自建兼容 API（如 CloudFreed 风格 `/createTask`、`/getTaskResult`）。
- `YesCaptchaSolver`: 对接 YesCaptcha 托管服务。
- 统一通过 `CLIENTT_KEY`（双 T）读取密钥。

### 2.4 通知模块（notify.py）

- 作为可选依赖动态导入：`from notify import send`。
- 导入失败不阻断签到主流程。
- 支持大量渠道，统一受 `TIMEOUT` 与相关环境变量控制。

## 3. 运行时数据流

1. 加载配置：环境变量 + Docker Cookie 文件（若 `IN_DOCKER=true`）。
2. 账号对齐：账号数组与 Cookie 数组按索引补齐。
3. 对每个账号执行：
   - `sign(cookie)`
   - 如失败且有账号密码：`session_login(...) -> sign(new_cookie)`
4. 成功后执行 `get_signin_stats(cookie, 30)`。
5. 若有更新，统一调用 `save_cookie("NS_COOKIE", ...)`。
6. 可选发送通知。

## 4. 外部依赖边界

- NodeSeek API（签到、登录、积分流水）。
- 验证码服务 API（Turnstile/YesCaptcha）。
- GitHub API（更新 Actions Variables，条件触发）。
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
  - 周期性扫描 `actions/*` 版本并生成升级报告。

## 6. 设计特征与约束

- 指纹降级：签到请求支持 `impersonate` 候选链路重试，缓解 Cloudflare 挑战。
- 容错优先：多数异常会降级为日志输出，不直接中断所有账号。
- 配置即行为：运行方式和存储介质完全由环境变量决定。
- 安全约束：调试日志提供脱敏输出；默认关闭 debug。
