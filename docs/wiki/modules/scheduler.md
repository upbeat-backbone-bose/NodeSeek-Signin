# 模块说明: scheduler.py

## 角色

定时调度器，负责在指定时间点触发 `nodeseek_sign.py`，并维护心跳与单实例约束。

## 时间配置解析

- 固定模式：`HH:MM`
- 随机区间：`HH:MM-HH:MM`（支持跨午夜，如 `22:00-02:00`）
- `RUN_AT` 未设置时使用 `09:00-21:00`
- `RUN_AT` 设置但格式非法时回退 `08:00-10:59`
- 启动时若已处于随机区间内，会立即执行一次；执行完成后等待下一个窗口，避免宽窗口内重复签到。

## 核心函数

- `get_run_config()`: 解析运行模式和配置值。
- `calculate_next_run_time(mode, value, now=None, rng=None, allow_immediate=True)`: 计算下一次运行时刻（GMT+8）；`allow_immediate=False` 时即使当前处于随机区间内也跳过本窗口。
- `_sleep_until(target)`: 分段休眠，期间写心跳并检查停止信号。
- `run_checkin_task()`: 通过 `subprocess.Popen` 执行签到，带 `TASK_TIMEOUT` 与信号转发。
- `_acquire_lock()`: POSIX `flock` 单实例锁；非 POSIX 平台为空操作。
- `main()`: 无限循环调度。

## 实现细节

- 时区固定为 `GMT+8`（`timezone(timedelta(hours=8))`）。
- 随机区间通过 Unix 时间戳随机，保证分钟级随机分布。
- 子进程使用脚本绝对路径和仓库目录作为 cwd，避免工作目录漂移。
- 每次休眠分段、任务运行期间以及任务前后都会更新 `HEARTBEAT_FILE`。
- 收到 SIGTERM/SIGINT 会终止子进程后退出。

## 使用注意

- 该模块设计为长期运行进程，不适合一次性命令任务。
- Docker Compose 默认即运行此模块，健康检查依赖心跳文件。
- 单实例锁仅在有 `fcntl` 的平台生效。
