# 青龙面板


在青龙面板中执行以下命令克隆本仓库：

```bash
ql repo https://github.com/upbeat-backbone-bose/NodeSeek-Signin.git
```

## 变量与 Cookie 回写

- 在青龙面板变量中配置 `NS_COOKIE`，或配置 `USER`/`PASS`、`USER1`/`PASS1` 等账号密码。
- 账号密码登录还需要 `SOLVER_TYPE`、`API_BASE_URL`、`CLIENT_KEY`。
- 新 Cookie 通过青龙任务预加载注入的全局 `QLAPI` 写回环境变量；如果运行环境没有注入 `QLAPI`，脚本会跳过回写并继续完成签到。
- 只有 Cookie 明确失效时才会触发登录和验证码，网络错误不会消耗验证码额度。
