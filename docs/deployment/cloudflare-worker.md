# NodeSeek 签到 Cloudflare Worker 版本

这是一个可以直接部署到 Cloudflare Workers 的 NodeSeek 自动签到脚本，使用 2captcha 解决 Turnstile 验证码。

## 功能特性

- ✅ 使用 2captcha 解决 Turnstile 验证码
- ✅ 支持多账户批量签到
- ✅ 支持 Cron 定时任务和带鉴权的手动触发
- ✅ 可选 KV 持久化 Cookie，减少重复登录和验证码消耗
- ✅ KV 并发锁与简单限流，避免重复执行
- ✅ Telegram 官方 API 通知（不再使用第三方中转）
- ✅ 对外只返回聚合结果，不泄露用户名和逐账号错误

## 部署步骤

### 1. 准备工作

1. 注册 [2captcha](https://2captcha.com/)，充值并在 API 设置页面获取 `CAPTCHA_API_KEY`。
2. 生成一个足够长的随机字符串作为 `TRIGGER_TOKEN`，用于保护 `/checkin`。
3. 可选：与 [@BotFather](https://t.me/BotFather) 创建 Bot 获取 `BotToken`，再获取接收通知的 `ChatID`。

### 2. 创建 Worker

#### 方式一：Cloudflare Dashboard

1. 登录 Cloudflare Dashboard，进入 Workers & Pages。
2. 创建 Worker，命名例如 `nodeseek-signin`。
3. 编辑代码，粘贴 `nodeseek-cloudflare-worker.js` 的全部内容并部署。
4. 在 `设置 -> 变量和机密` 中添加下方环境变量；`TRIGGER_TOKEN`、`CAPTCHA_API_KEY` 建议使用“机密”类型（`CAPTCHA_API_KEY` 仅在需要重新登录时才会用到）。

#### 方式二：Wrangler CLI

```bash
npm install -g wrangler
wrangler login
```

创建 `wrangler.toml`：

```toml
name = "nodeseek-signin"
main = "nodeseek-cloudflare-worker.js"
compatibility_date = "2026-01-01"

[triggers]
crons = ["0 9 * * *"]

# 可选：绑定 KV 以持久化 Cookie 和启用并发锁
# [[kv_namespaces]]
# binding = "CHECKIN_KV"
# id = "<your-kv-namespace-id>"
```

部署：

```bash
wrangler deploy
```

### 3. 配置环境变量

| 变量名 | 必要性 | 说明 |
| --- | --- | --- |
| `user` | 必填 | NodeSeek 用户名，多个用 `&` 分隔 |
| `pass` | 必填 | 密码，多个用 `&` 分隔，与 `user` 一一对应 |
| `CAPTCHA_API_KEY` | 需要登录时必填 | 2captcha API Key；只有账号没有可用 Cookie 或 Cookie 明确失效时才会用到 |
| `TRIGGER_TOKEN` | HTTP 触发必填 | `/checkin` 的 Bearer Token；未配置时 HTTP 触发返回 503 |
| `CAPTCHA_API_URL` | 可选 | 默认 `https://api.2captcha.com`，必须是 http(s) URL |
| `NS_COOKIE` | 可选 | 已有 Cookie，多个用 `&` 分隔；空槽位用 `&&` 保留 |
| `CHECKIN_KV` | 可选（推荐） | KV binding 名称；绑定后持久化 Cookie、启用并发锁和限流 |
| `BotToken` | 可选 | Telegram Bot Token |
| `ChatID` | 可选 | Telegram Chat ID |

示例：

```text
user: alice&bob
pass: password123&password456
CAPTCHA_API_KEY: 1234567890abcdef1234567890abcdef
TRIGGER_TOKEN: a-long-random-token
NS_COOKIE: session=...&session=...
BotToken: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz
ChatID: 123456789
```

### 4. 配置 KV（推荐）

1. 在 Cloudflare Dashboard 中创建 KV namespace。
2. 在 Worker 的 `设置 -> 绑定` 中添加 KV namespace，变量名填写 `CHECKIN_KV`。
3. 重新部署。

绑定后：

- 登录成功的新 Cookie 会按账号下标写入 `nodeseek:cookies`，有效期 30 天。
- **KV 中已刷新的 Cookie 优先于面板里的 `NS_COOKIE`**：面板里的值是静态的，永远不会更新；每次运行会用 KV 中对应下标的新值覆盖它，仅在 KV 缺少该下标时才回退到面板值。这样重新登录的结果才能真正被复用，避免每次运行都重新购买验证码。
- 每次签到会尝试获取 `nodeseek:checkin-lock`，防止定时任务和手动触发重叠。
- 手动触发会按 IP 做简单限流（每 10 分钟最多 10 次）。

未绑定 KV 时 Worker 仍可运行，但每次 Cookie 失效都需要重新登录并购买验证码，且没有并发锁。

> 如果需要让面板里的 `NS_COOKIE` 重新生效（例如手动换了一个新 Cookie），删除 KV 中的 `nodeseek:cookies` 键即可，Worker 会回退到面板值。

### 5. 设置定时任务

在 Dashboard 的 `触发器 -> Cron 触发器` 中添加，例如：

- `0 9 * * *`：每天 UTC 09:00（北京时间 17:00）
- `0 1 * * *`：每天 UTC 01:00（北京时间 09:00）

Cron 使用 UTC，请按需换算。

### 6. 手动触发

```bash
curl -X POST https://your-worker-name.your-subdomain.workers.dev/checkin \
  -H "Authorization: Bearer <TRIGGER_TOKEN>"
```

返回示例（只包含聚合结果）：

```json
{
  "success": true,
  "total": 2,
  "succeeded": 1,
  "already": 1,
  "failed": 0,
  "message": "签到完成"
}
```

未授权返回 401，未配置 `TRIGGER_TOKEN` 返回 503，已有任务运行或触发过于频繁返回 409/429，配置错误或签到失败返回 500。

## 工作原理

1. 定时任务或带 Bearer Token 的 HTTP 请求触发签到。
2. 逐槽位合并 Cookie：优先取 KV 中该下标已刷新的值，KV 缺失时回退到 `NS_COOKIE` 的对应下标。
3. 使用合并后的 Cookie 调用签到 API。
4. 只有账号没有可用 Cookie、或 Cookie 明确失效（404 / 未登录 / 请先登录）时才调用 2captcha 登录；网络错误和 Cloudflare 403 不会触发付费求解。`CAPTCHA_API_KEY` 仅在确实需要登录时才要求配置。
5. 登录成功后更新内存中的 Cookie 槽位；绑定 KV 时按槽位写回 KV。
6. 通过 Telegram 官方 API 发送聚合通知；配置错误（缺少 `user`/`pass`，或两者数量不匹配）同样会发送通知，不再静默失败。缺少 `CAPTCHA_API_KEY` 且确实需要登录时，该账号计为失败并发送通知。

## 安全说明

- `/checkin` 不再允许匿名调用；请务必设置高强度 `TRIGGER_TOKEN`。
- Worker 不返回用户名、逐账号结果或原始异常，避免信息泄露。
- 已移除第三方 Telegram 中转；未配置 `BotToken` 时直接跳过通知。
- Telegram 消息内容会做 HTML 转义。
- 所有外部请求使用 `AbortSignal.timeout`，避免无限等待。
- KV 锁为 best-effort：Cloudflare KV 不提供原子比较交换，极端并发下仍可能重叠。
- 请不要把真实 Cookie、密码或 API Key 写进代码仓库。

## 成本与限制

- 2captcha 按次计费，Turnstile 价格以官网为准。
- Cloudflare Workers 的 CPU 时间、Cron、KV 配额随套餐变化，请以 Cloudflare 当前文档为准。
- Worker 的单次请求有执行时间上限；账号很多时建议拆分 Worker 或改用 Docker/GitHub Actions。

## 故障排查

### 签到失败

- 检查 `user`/`pass` 数量是否一致。
- 检查 `CAPTCHA_API_KEY` 余额和权限。
- 查看 Worker 实时日志；对外响应只保留聚合信息。

### 验证码超时

- 确认 `CAPTCHA_API_URL` 可访问且为 http(s)。
- 检查 2captcha 服务状态和余额。
- 适当增加代码中的 `maxRetries` 或 `retryInterval`。

### 收不到 Telegram 通知

- 确认同时配置了 `BotToken` 和 `ChatID`。
- 先与 Bot 对话一次激活。
- 未配置 `BotToken` 时不会回退到任何第三方服务。

### 定时任务未执行

- 检查 Cron 表达式和 UTC 时区换算。
- 确认 Worker 已部署且未被禁用。
- 查看 Cloudflare 的 Cron 触发日志。

## 升级

替换 `nodeseek-cloudflare-worker.js` 后重新部署。环境变量和 KV binding 无需重新配置。

## 许可证与免责声明

本项目基于原 NodeSeek-Signin 项目改编，遵循相同的开源许可证。脚本仅供学习交流使用，请遵守 NodeSeek 的服务条款；使用本脚本产生的任何后果由使用者自行承担。
