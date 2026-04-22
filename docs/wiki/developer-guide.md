# 开发者指南

## 1. 本地准备

安装依赖：

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

建议使用 `.env.example` 复制出 `.env` 并按需填入变量。

## 2. 常用执行方式

- 快速验证（自动加载 `.env`）：

```bash
python test_run.py
```

- 直接执行核心脚本（不自动加载 `.env`）：

```bash
python nodeseek_sign.py
```

- 运行定时调度（无限循环）：

```bash
python scheduler.py
```

- Docker 定时运行：

```bash
docker compose up -d
```

- 本地构建文档：

```bash
mkdocs build
```

## 3. 关键调试点

- 登录失败排查：
  - 检查 `SOLVER_TYPE`、`API_BASE_URL`、`CLIENTT_KEY`。
  - 验证账号密码是否与目标账号匹配。
- Cookie 失效行为：
  - 无账号密码时只会报失败，不会自动恢复。
  - 有账号密码时会尝试验证码登录刷新。
- Cloudflare 拦截：
  - 关注日志中 `403 Cloudflare challenge`。
  - 调整 `NS_IMPERSONATE` 作为首选指纹。

## 4. 代码修改建议

- 修改通知相关逻辑时，同步检查 `nodeseek_sign.py` 与 `notify.py` 的超时和开关读取。
- 修改调度行为时，确认 `docker-compose.yml` 和 `.github/workflows/blank.yml` 的运行入口是否仍一致。
- 修改验证码参数命名时，不要更改 `CLIENTT_KEY` 变量名。

## 5. 回归验证清单

1. 单账号 Cookie 正常签到。
2. Cookie 失效后账号密码登录恢复。
3. 多账号索引对齐（账号数与 Cookie 数不一致）。
4. Docker 模式 Cookie 文件读写。
5. `TIMEOUT` 生效（主脚本与通知模块）。

## 6. 已知实现差异

- `scheduler.py` 的代码默认 `RUN_AT=09:00-21:00`。
- `scheduler.py` 在无效格式时回退到 `08:00-10:59`，日志文案也使用该回退值。

文档或注释与运行行为不一致时，以代码实现为准。
