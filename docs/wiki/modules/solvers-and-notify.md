# 模块说明: solvers-and-notify

## 1. turnstile_solver.py

- 提供 `TurnstileSolver`，面向兼容 `/createTask` 与 `/getTaskResult` 的服务。
- 初始化时校验 `API_BASE_URL` 必须为 http(s)。
- 轮询策略：默认最多 20 次、每次间隔 6 秒，并受总时限约束。
- 超时策略：默认读取 `TIMEOUT`（15 秒）。
- 兼容两种返回格式：`status=completed` + `result.response.token` 与 `status=ready` + `solution.token`。
- 遇到 `failed` / `error` / `invalid` 等终态立即抛出 `TurnstileSolverError`。
- 异常类型：`TurnstileSolverError`、`TurnstileSolverTimeout`、`TurnstileSolverNetworkError`。

## 2. yescaptcha.py

- 提供 `YesCaptchaSolver`，默认 API 为 `https://api.yescaptcha.com`。
- 支持普通任务与 `advanced`（M1）模式。
- 轮询策略：默认最多 20 次、每次间隔 3 秒，并受总时限约束。
- 终态错误立即抛出 `YesCaptchaSolverError`，不再继续轮询。
- 异常类型：`YesCaptchaSolverError`、`YesCaptchaSolverTimeout`、`YesCaptchaSolverNetworkError`。

## 3. 求解器异常分类

- 异常分类：`TurnstileSolverTimeout` / `YesCaptchaSolverTimeout` 表示求解总时限已到，`TurnstileSolverNetworkError` / `YesCaptchaSolverNetworkError` 表示验证码服务请求失败（网络/传输层），其余为验证码本身未解出。
- 失败原因会写进异常消息并由 `nodeseek_sign.py` 原样输出，便于区分"密钥无效""余额不足"等问题。

## 4. notify.py

- 对外统一接口：`send(title, content)`。
- 内部支持多渠道推送（Telegram、Bark、PushPlus、邮件等）。
- 与主脚本共享 `config.py` 中的 `TIMEOUT` 和 `DEBUG`。
- 每个渠道在线程中独立运行，异常隔离；主流程等待时间受 `NOTIFY_THREAD_TIMEOUT` 限制。
- SMTP 默认 SSL，`SMTP_SSL=false` 时强制 STARTTLS，不会明文登录。
- 支持 `NOTIFY_CONFIG_JSON` 批量覆盖配置。
- `one()` 获取一言失败时返回空字符串，不影响主通知。

## 5. 依赖关系

- `nodeseek_sign.py` 根据 `SOLVER_TYPE` 选择验证码求解器。
- `notify.py` 为可选模块；导入失败时主流程继续执行。

## 6. 修改建议

- 修改超时或默认值时，务必同步检查三个模块与 `config.py` 的一致性。
- 新增通知渠道时，优先复用 `push_config` 与统一发送入口，避免在主脚本写分支逻辑。
- 新增渠道需要同时更新 `push_config` 和 `add_notify_function()`。
