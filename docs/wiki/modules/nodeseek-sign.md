# 模块说明: nodeseek_sign.py

## 角色

项目核心执行模块，负责：账号装配、签到、失败重试登录、收益统计、通知、Cookie 持久化。

## 关键函数

- `_request_with_impersonate_fallback(...)`: 统一请求入口；仅在明确的 Cloudflare 挑战时切换有限指纹，传输异常不重试。
- `detect_environment()`: 区分 `docker` / `qinglong` / `github` / `unknown`。
- `session_login(...)`: 先解验证码，再调用登录接口并提取 Cookie。
- `sign(ns_cookie, ns_random)`: 调用签到接口并归一化结果状态。
- `get_signin_stats(ns_cookie, days=30)`: 分页读取积分流水，筛选“签到收益”。
- `save_cookie(...)`: 根据环境分派到 GitHub Secret / 青龙 / 文件。
- `run() -> int`: 可导入的主流程，返回进程退出码。

## 主流程摘要

1. 收集账号与 Cookie（Docker 下从文件读取）。
2. 补齐数组，确保按索引对应，保留空 Cookie 槽位；
   末尾多余分隔符被丢弃，不产生幽灵账号。
   账号数与 Cookie 数不一致时打印错位告警。
3. 每账号先尝试 Cookie 签到。
4. 仅当状态为 `invalid` 且有账号密码时执行登录并重签。
5. 成功后查询统计并通知。
6. 重新登录并重新签到成功后立即保存；结束时再次统一保存。
7. 输出 `RESULT` JSON 汇总（`succeeded`/`already`/`failed` 互斥，
   `success` 为布尔值）；有失败账号则返回 1。

## 状态语义

`sign()` 可能返回：

- `success`: 成功获得奖励
- `already`: 当日已签到
- `invalid`: Cookie 无效（404 / 未登录 / 请先登录）
- `forbidden`: 被 403 拦截（含 Cloudflare challenge）
- `fail`: 业务失败
- `error`: 请求异常、429 或 5xx

判定顺序（`sign()` 内部）：先看消息里的明确信号
（`鸡腿` → `success`、`已完成签到` → `already`、404/未登录 → `invalid`），
最后才回退到通用的 `success` 标志。顺序很关键：接口在"今日已签到"时
也可能返回 `success: true`，若先判断标志位，`already` 将永远不会被计数。

## 健壮性设计

- `impersonate` 候选链路有限且可配置，遇到挑战才切换。
- 传输异常不会重复提交非幂等的签到 POST。
- 统计查询有页数上限与总时限；数据被页数上限截断时，
  `period` 会标注"数据不完整"，避免把部分数据当作完整窗口。
- 调试日志受 `DEBUG` 控制；通知与登录错误只输出摘要。
- 通知模块导入失败不影响签到。
- GitHub 回写默认关闭，开启后使用 PyNaCl 加密 Secrets API；
  未启用时报告"已跳过保存"而非"保存失败"。
