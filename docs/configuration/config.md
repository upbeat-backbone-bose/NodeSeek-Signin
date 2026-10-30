# 环境变量手册

> 📌 **提示**
> - `docs/configuration/solutions.md` 说明了验证码供应商的差异；本文档侧重列举所有变量的含义与默认值。
> - 仓库根目录的 `.env.example` 提供了一份可直接复制的模板，建议从该文件开始修改。

## 1. 核心账号 / Cookie 变量

| 变量 | 是否必填 | 默认值 | 作用 | 备注 |
| --- | --- | --- | --- | --- |
| `NS_COOKIE` | 建议 | - | 直接使用已有 Cookie 执行签到，支持 `&` 或换行分隔多个账户；支持 `cookie1&&cookie3` 形式的空槽位，空槽位不会导致账号索引错位 | Docker 环境下若设置 `IN_DOCKER=true`，脚本**忽略本环境变量**，只从 `cookie/NS_COOKIE.txt` 读取；仅在重新登录刷新出新 Cookie 后才会原子写回该文件。末尾多余的分隔符会被忽略，不会多出账号 |
| `USER` / `PASS` | 可选 | - | **第 1 个账号**的用户名/密码 | 仅在 Cookie 缺失或明确失效（404 / 未登录 / 请先登录）时尝试登录；网络错误、403、5xx 不触发登录 |
| `USER1` / `PASS1` 以及 `USER2` / `PASS2` … | 可选 | - | 按序号声明后续账号密码 | `USER1` 对应第 2 个账号，`USER2` 对应第 3 个，以此类推；必须连续设置（遇到第一个缺失的序号即停止） |

> ✅ **最小可用集**：至少提供 `NS_COOKIE`，或为每个账号准备对应的 `USERn`/`PASSn` 与验证码服务配置。

> ⚠️ **槽位顺序**：账号与 Cookie 按下标一一对应（位置即身份）。`USER`/`PASS` 是第 1 个账号，`USER1`/`PASS1` 是第 2 个，依此类推。若只配置了 `USER1`/`PASS1`（没有 `USER`/`PASS`），那么 `USER1` 就是第 1 个账号。账号数量与 Cookie 数量不一致时脚本会打印告警提示可能存在错位；账号数多于 Cookie 数时，多出来的账号没有可信的槽位身份，会直接计为失败且不会触发验证码登录。

## 2. 验证码解决方案

| 变量 | 是否必填 | 默认值 | 适用场景 |
| --- | --- | --- | --- |
| `SOLVER_TYPE` | 可选 | `turnstile` | `turnstile` 表示自建 CloudFreed / Cloudflyer 等接口；`yescaptcha` 表示托管服务 |
| `API_BASE_URL` | 条件必填 | 空字符串 | 指向自建服务或 YesCaptcha 的 API 地址，如 `http://127.0.0.1:3000` 或 `https://api.yescaptcha.com` |
| `CLIENT_KEY` | 必填 | - | 验证码服务密钥，CloudFreed 与 YesCaptcha 都使用该名称 |

> ℹ️ 更多供应商注意事项见 `docs/configuration/solutions.md`。

## 3. 运行与调度行为

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `NS_RANDOM` | `false` | 原样传递给签到接口的 `random` 查询参数，不做布尔解析 |
| `RUN_AT` | `09:00-21:00` | `scheduler.py` 读取的定时配置。支持固定时间（`HH:MM`）或时间范围（`HH:MM-HH:MM`，将在区间内随机挑选）；格式错误时回退 `08:00-10:59`；启动时若已处于时间范围内会立即执行一次，之后每天只运行一次 |
| `TIMEOUT` | `15` | 单次 HTTP 请求超时（秒） |
| `NS_IMPERSONATE` | `chrome146` | 首选 curl_cffi 指纹 |
| `NS_IMPERSONATE_ATTEMPTS` | `3` | 指纹最多尝试次数（1-5），仅在 Cloudflare 挑战时切换 |
| `MAX_LOGIN_ATTEMPTS` | 账号数与 Cookie 数中的较大者 | 每次运行最多重新登录次数，避免异常时持续购买验证码 |
| `STATS_MAX_PAGES` | `20` | 签到收益统计最多查询页数（1-20）。若调低导致窗口被截断，统计结果会标注为"数据不完整" |
| `TASK_TIMEOUT` | `1800` | 调度器允许签到子进程运行的最长秒数 |
| `IN_DOCKER` | 未设置 | 设为 `true` 时视为容器环境，Cookie 会写入/读取 `cookie/NS_COOKIE.txt`；用于 Docker Compose 场景 |
| `DEBUG` | `false` | 开启后输出详细调试信息，可能包含敏感上下文，默认关闭 |
| `SCHEDULER_SLEEP_CHUNK` | `60` | 调度器休眠分段检查间隔（秒），用于响应系统时间变化与停止信号 |
| `HEARTBEAT_FILE` | `./cookie/heartbeat` | 心跳文件路径，Docker 健康检查依据其更新时间 |
| `SCHEDULER_LOCK_FILE` | `./cookie/scheduler.lock` | 调度器单实例锁文件路径（POSIX flock） |

## 4. GitHub / CI 集成

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `GH_PAT` | 可选 | GitHub Personal Access Token，仅用于加密 Secret 回写，需要目标仓库的 Secrets 写权限 |
| `GH_COOKIE_WRITEBACK` | 可选 | 默认 `false`。设为 `true` 后通过 GitHub Secrets API + PyNaCl 加密更新 `NS_COOKIE` |
| `GITHUB_ACTIONS` | 由平台注入 | GitHub Actions 运行器自动提供，脚本据此判断当前是否在 Actions 内运行 |
| `GITHUB_REPOSITORY` | 由平台注入 | 与 `GH_PAT` 搭配，指明需要写入 Secret 的仓库 |

> 🔁 默认不会自动回写。启用 `GH_COOKIE_WRITEBACK=true` 后，脚本仅在重新登录并重新签到成功时更新加密 Secret，不再写入明文 Actions Variable。

## 5. 通知推送变量

`notify.py` 支持 20+ 种渠道，下表列出最常用的几类变量。若需启用其他渠道，请查阅 `notify.py` 顶部的 `push_config` 列表。

### 5.1 Telegram

| 变量 | 说明 |
| --- | --- |
| `TG_BOT_TOKEN` | Bot 的 Token，形如 `123456789:ABC...` |
| `TG_USER_ID` | 接收消息的用户或群组 ID |
| `TG_THREAD_ID` | （可选）超级群话题 ID，用于把通知发送到特定话题 |
| `TG_PROXY_HOST` / `TG_PROXY_PORT` / `TG_PROXY_AUTH` / `TG_API_HOST` | （可选）为 Telegram 设置代理或反代 |

### 5.2 Bark / PushPlus / 邮件 等

- **Bark**：`BARK_PUSH`（必须）、`BARK_ARCHIVE`、`BARK_GROUP`、`BARK_SOUND`、`BARK_ICON`、`BARK_LEVEL`, `BARK_URL` 等控制推送外观。
- **PushPlus**：`PUSH_PLUS_TOKEN`（必须）、`PUSH_PLUS_USER`。
- **Server酱 / PushDeer / Go-cqhttp / 飞书 / DingTalk / Gotify / Synology Chat / iGot / 自定义 Webhook**：分别使用 `PUSH_KEY`、`DEER_KEY`、`GOBOT_*`、`FSKEY`、`DD_BOT_SECRET` + `DD_BOT_TOKEN`、`GOTIFY_*`、`CHAT_*`、`IGOT_PUSH_KEY`、`WEBHOOK_*` 等变量。
- **邮件**：`SMTP_SERVER`（可写 `host:port`）、`SMTP_SSL`（默认 `true`）、`SMTP_EMAIL`、`SMTP_PASSWORD`、`SMTP_NAME`。当 `SMTP_SSL=false` 时会强制使用 STARTTLS，不会明文登录。两种方式都会校验服务器证书（自签名证书需自行处理）。
- **其他**：`QYWX_KEY`、`QYWX_AM`、`WE_PLUS_BOT_*`、`QMSG_*`、`AIBOTK_*`、`PUSHME_*`、`CHRONOCAT_*`……均与 `push_config` 字段同名。
- **批量配置**：`NOTIFY_CONFIG_JSON` 可传入一个 JSON 对象，一次性设置多个渠道；`NOTIFY_THREAD_TIMEOUT` 控制单渠道最长等待时间（默认 30 秒）。

### 5.3 通知开关

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CONSOLE` | `false` | 设置为 `true` 时额外将通知输出到控制台（不会禁用其他已配置渠道） |
| `HITOKOTO` | `True` | 是否在通知末尾追加一句「一言」名句 |
| `SKIP_PUSH_TITLE` | 未设置 | 多个标题用回车分隔，匹配到的标题会跳过推送 |

## 6. 部署场景推荐组合

| 场景 | 最少需要配置 | 建议额外配置 |
| --- | --- | --- |
| **GitHub Actions** | `NS_COOKIE` 或 `USERn/PASSn` + 验证码变量 | `GH_COOKIE_WRITEBACK=true` + `GH_PAT`（加密回写）、`NOTIFY_CONFIG_JSON`（通知） |
| **Docker Compose / 本地定时** | `USER`/`PASS`（或 `USERn`/`PASSn`）+ 验证码变量，或预先写入 `cookie/NS_COOKIE.txt` | `IN_DOCKER=true`（启用文件存储 Cookie）、`./cookie` 目录归属 UID 1000、任意通知变量 |
| **青龙面板** | 直接在面板变量中写入 `NS_COOKIE` 或 `USERn/PASSn`、验证码变量 | 配置任意通知变量，支持与青龙自带通知并存 |

## 7. 调试与排障建议

1. 利用 `.env.example` 复制生成 `.env`，逐项填值，便于与仓库更新保持同步。
2. 本地调试可运行 `python test_run.py` 验证配置是否生效；该命令会执行真实签到，可能消耗验证码额度。Docker/青龙请先确认 `RUN_AT` 是否在可接受的时段内。
3. 如果启用了账号密码但依然无法自动登录，请确认 `SOLVER_TYPE`、`API_BASE_URL`、`CLIENT_KEY` 是否匹配对应的验证码服务。
4. 若通知未触发，可在同一个 shell 中临时导出变量后执行 `python notify.py` 做自检。

通过本文档即可对照自己的部署场景，快速核验环境变量是否齐全，减少因配置遗漏导致的签到失败。
