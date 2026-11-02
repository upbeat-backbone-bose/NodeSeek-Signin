# 模块说明: nodeseek-cloudflare-worker.js

## 角色

Cloudflare Worker 版本的独立签到实现，提供 HTTP 触发和定时触发两种入口，不复用 Python 主链路代码。

## 入口与触发

- `fetch(request, env)`：处理 HTTP 请求。
- `scheduled(event, env, ctx)`：处理 Worker Cron 触发。
- 手动签到接口：`POST /checkin`，需要 `Authorization: Bearer <TRIGGER_TOKEN>`。

## 鉴权与状态码

- 未配置 `TRIGGER_TOKEN`：503
- Token 缺失或不匹配：401
- 已有任务运行：409
- 触发过于频繁：429
- 签到存在失败账号：500

## 主要流程

1. 从 Worker 环境读取账号、密码、Cookie、验证码配置。
2. 逐槽位合并 Cookie：优先取 KV 中该下标已刷新的值，KV 缺失时回退到 `NS_COOKIE`。
   面板里的 `NS_COOKIE` 是静态的，若整体优先于 KV，刷新结果将永远无法被复用。
3. 仅在账号没有可用 Cookie、或 Cookie 明确失效（404 / 未登录 / 请先登录）时通过 2captcha 求解 Turnstile 并登录；网络错误和 Cloudflare 403 不会触发付费求解。
4. 对每个账号汇总结果，仅返回聚合字段。
5. 可选发送 Telegram 官方 API 通知；配置错误时同样发送通知，不静默失败。

## 关键类

- `TwoCaptchaSolver`
  - 创建任务：`POST <CAPTCHA_API_URL>/createTask`
  - 查询结果：`POST <CAPTCHA_API_URL>/getTaskResult`
  - 轮询策略：最多 40 次，间隔 3 秒
  - 所有请求使用 `AbortSignal.timeout` 超时

## 变量接口（Worker 环境）

- 账号：`user`、`pass`（使用 `&` 分隔）
- 验证码：`CAPTCHA_API_KEY`、`CAPTCHA_API_URL`
- Cookie：`NS_COOKIE`
- 触发鉴权：`TRIGGER_TOKEN`
- KV：`CHECKIN_KV`（可选，持久化 Cookie、并发锁、限流）
- 通知：`BotToken`、`ChatID`

## 与 Python 实现差异

- 验证码服务默认是 2captcha，而 Python 主实现默认是 turnstile/YesCaptcha。
- 变量命名与 Python 不完全一致（如 `user/pass` vs `USERn/PASSn`）。
- 运行平台为 Cloudflare Worker，不依赖本仓库 Python 依赖与 Docker 编排。
- 响应不包含逐账号信息或原始异常。
- 测试独立于 pytest：`node --test "tests/*.test.mjs"`（`tests/worker.test.mjs`），
  通过替换全局 `fetch` 与内存版 KV binding 覆盖本模块。
