# GitHub Actions 部署

## 1. 基础配置

1. Fork 本仓库到自己的 GitHub 账号下。
2. 进入仓库的 `Settings > Secrets and variables > Actions`。
3. 在 **Secrets** 中添加以下配置（不要使用 Variables 保存凭据）：

| 名称 | 必要性 | 说明 |
| --- | --- | --- |
| `NS_COOKIE` | 建议 | NodeSeek 用户 Cookie。多账号用 `&` 或换行分隔；空槽位用 `&&` 保留，避免账号错位 |
| `USER` / `PASS` | 可选 | 第一个账号的用户名和密码 |
| `USER1` / `PASS1` … | 可选 | 额外账号，序号从 1 递增 |
| `SOLVER_TYPE` | 可选 | `turnstile`（默认）或 `yescaptcha` |
| `API_BASE_URL` | 条件必需 | 自建 CloudFreed 或 YesCaptcha 地址 |
| `CLIENT_KEY` | 登录时必需 | 验证码服务客户端密钥 |
| `NOTIFY_CONFIG_JSON` | 可选 | 一次性传入所有通知渠道配置的 JSON 对象 |
| `TG_BOT_TOKEN` / `TG_USER_ID` / `TG_THREAD_ID` | 可选 | Telegram 通知 |

> `NS_COOKIE` 等同账号会话。Actions Variable 是明文存储且不会自动脱敏，本项目已不再从 `vars.NS_COOKIE` 读取，也不会写入 Variable。

## 2. 可选：自动加密回写 Cookie

默认不会自动回写。若希望 Cookie 轮换后自动更新：

1. 创建 **fine-grained PAT**，只授权目标仓库的 `Secrets: Read and write` 权限（不需要 `repo` 全权限或 `workflow`）。
2. 将 PAT 保存为仓库 Secret：`GH_PAT`。
3. 添加 Secret：`GH_COOKIE_WRITEBACK=true`。
4. 脚本重新登录成功后，会通过 GitHub Secrets API 获取公钥，用 PyNaCl sealed box 加密后更新 `NS_COOKIE`。

如果不开启该功能，请在 Cookie 失效后手动更新 `NS_COOKIE` Secret。

## 3. 调度时间

工作流 cron 为 `10 16 * * *`，即北京时间（UTC+8）每天 00:10。刻意避开 00:00 整点：NodeSeek 每日签到计数在 00:00 重置，整点触发可能落在重置生效前，导致当天仍按前一天的计数判定。GitHub Actions 的定时任务可能因平台负载延迟，属于正常现象。

## 4. 安全说明

- 工作流只声明 `contents: read`，不再需要 `actions: write`。
- 依赖通过 `pip install -r requirements.txt` 安装，版本由仓库统一管理，不在 CI 中临时升级。
- 所有 GitHub Actions 固定到完整 commit SHA，由 Dependabot 负责更新。
- 若使用账号密码登录，请同时配置验证码服务；只有 Cookie 明确失效时才会触发登录，网络错误不会自动消耗验证码额度。
- 签到失败时脚本会返回非零退出码，Actions 会显示为失败，便于发现问题。
