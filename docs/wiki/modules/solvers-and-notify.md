# 模块说明: solvers-and-notify

## 1. turnstile_solver.py

- 提供 `TurnstileSolver`，面向兼容 `/createTask` 与 `/getTaskResult` 的服务。
- 轮询策略：默认最多 20 次、每次间隔 6 秒。
- 超时策略：默认读取 `TIMEOUT`（15 秒）。
- 异常类型：`TurnstileSolverError`。

## 2. yescaptcha.py

- 提供 `YesCaptchaSolver`，默认 API 为 `https://api.yescaptcha.com`。
- 支持普通任务与 `advanced`（M1）模式。
- 轮询策略：默认最多 20 次、每次间隔 3 秒。
- 异常类型：`YesCaptchaSolverError`。

## 3. notify.py

- 对外统一接口：`send(title, content)`。
- 内部支持多渠道推送（Telegram、Bark、PushPlus、邮件等）。
- 使用线程锁保障多线程日志输出顺序。
- 与主脚本共享 `TIMEOUT` 和 `DEBUG` 环境变量语义。

## 4. 依赖关系

- `nodeseek_sign.py` 根据 `SOLVER_TYPE` 选择验证码求解器。
- `notify.py` 为可选模块；导入失败时主流程继续执行。

## 5. 修改建议

- 修改超时默认值时，务必同步检查三个模块的一致性。
- 新增通知渠道时，优先复用 `push_config` 与统一发送入口，避免在主脚本写分支逻辑。
