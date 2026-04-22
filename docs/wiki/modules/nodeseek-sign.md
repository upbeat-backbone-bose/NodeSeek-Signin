# 模块说明: nodeseek_sign.py

## 角色

项目核心执行模块，负责：账号装配、签到、失败重试登录、收益统计、通知、Cookie 持久化。

## 关键函数

- `detect_environment()`: 区分 `docker` / `qinglong` / `github` / `unknown`。
- `session_login(...)`: 先解验证码，再调用登录接口并提取 Cookie。
- `sign(ns_cookie, ns_random)`: 调用签到接口并归一化结果状态。
- `get_signin_stats(ns_cookie, days=30)`: 分页读取积分流水，筛选“签到收益”。
- `save_cookie(...)`: 根据环境分派到 GitHub/青龙/文件。

## 主流程摘要

1. 收集账号与 Cookie。
2. 补齐数组，确保按索引对应。
3. 每账号先尝试 Cookie 签到。
4. 失败后（若有账号密码）执行登录并重签。
5. 成功后查询统计并通知。
6. 若 Cookie 更新，统一保存。

## 状态语义

`sign()` 可能返回：

- `success`: 成功获得奖励
- `already`: 当日已签到
- `invalid`: Cookie 无效
- `forbidden`: 被 403 拦截（含 Cloudflare challenge）
- `fail`: 业务失败
- `error`: 请求异常

## 健壮性设计

- `impersonate` 候选链路重试，遇到 challenge 自动切换指纹。
- 调试日志受 `DEBUG` 控制，敏感信息输出做脱敏。
- 通知模块导入失败不影响签到。
