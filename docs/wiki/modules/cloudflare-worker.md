# 模块说明: nodeseek-cloudflare-worker.js

## 角色

Cloudflare Worker 版本的独立签到实现，提供 HTTP 触发和定时触发两种入口，不复用 Python 主链路代码。

## 入口与触发

- `fetch(request, env)`：处理 HTTP 请求。
- `scheduled(event, env, ctx)`：处理 Worker Cron 触发。
- 手动签到接口：`POST /checkin`。

## 主要流程

1. 从 Worker 环境读取账号、密码、Cookie、验证码配置。
2. 优先使用 `NS_COOKIE` 进行签到。
3. Cookie 失效时通过 2captcha 求解 Turnstile 并登录。
4. 对每个账号汇总结果并可选发送 Telegram 通知。

## 关键类

- `TwoCaptchaSolver`
  - 创建任务：`POST <CAPTCHA_API_URL>/createTask`
  - 查询结果：`POST <CAPTCHA_API_URL>/getTaskResult`
  - 轮询策略：最多 40 次，间隔 3 秒

## 变量接口（Worker 环境）

- 账号：`user`、`pass`（使用 `&` 分隔）
- 验证码：`CAPTCHA_API_KEY`、`CAPTCHA_API_URL`
- Cookie：`NS_COOKIE`
- 通知：`BotToken`、`ChatID`

## 与 Python 实现差异

- 验证码服务默认是 2captcha，而 Python 主实现默认是 turnstile/YesCaptcha。
- 变量命名与 Python 不完全一致（如 `user/pass` vs `USERn/PASSn`）。
- 运行平台为 Cloudflare Worker，不依赖本仓库 Python 依赖与 Docker 编排。
