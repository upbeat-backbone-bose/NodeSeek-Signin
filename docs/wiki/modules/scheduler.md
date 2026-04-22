# 模块说明: scheduler.py

## 角色

定时调度器，负责在指定时间点触发 `nodeseek_sign.py`。

## 时间配置解析

- 固定模式：`HH:MM`
- 随机区间：`HH:MM-HH:MM`
- `RUN_AT` 未设置时使用 `09:00-21:00`
- `RUN_AT` 设置但格式非法时回退 `08:00-10:59`

## 核心函数

- `get_run_config()`: 解析运行模式和配置值。
- `calculate_next_run_time(mode, value)`: 计算下一次运行时刻（GMT+8）。
- `run_checkin_task()`: 调用 Python 子进程执行签到脚本。
- `main()`: 无限循环调度。

## 实现细节

- 时区固定为 `GMT+8`（`timezone(timedelta(hours=8))`）。
- 随机区间通过 Unix 时间戳随机，保证分钟级随机分布。
- 如果计算出的时间已过，先等待 60 秒再重算，避免空转。

## 使用注意

- 该模块设计为长期运行进程，不适合一次性命令任务。
- Docker Compose 默认即运行此模块。
