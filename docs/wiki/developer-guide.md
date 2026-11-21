# 开发者指南

## 1. 本地准备

安装依赖：

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

建议使用 `.env.example` 复制出 `.env` 并按需填入变量。

## 2. 常用执行方式

- 单元测试（不访问网络、不消耗验证码）：

```bash
python -m pytest -q
```

- 快速验证（自动加载 `.env`，会执行真实签到）：

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
mkdocs build --strict
```

## 3. 关键调试点

- 登录失败排查：
  - 检查 `SOLVER_TYPE`、`API_BASE_URL`、`CLIENT_KEY`。
  - 验证账号密码是否与目标账号匹配。
- Cookie 失效行为：
  - 无账号密码时只会报失败，不会自动恢复。
  - 有账号密码时，仅在 `sign()` 返回 `invalid` 时才尝试验证码登录。
- Cloudflare 拦截：
  - 关注日志中 `403 Cloudflare challenge`。
  - 调整 `NS_IMPERSONATE`，并用 `NS_IMPERSONATE_ATTEMPTS` 限制回退次数。
- 调度器问题：
  - 查看 `cookie/heartbeat` 是否持续更新。
  - 检查 `RUN_AT` 格式与当前 GMT+8 时间。

## 4. 代码修改建议

- 新增环境变量时优先在 `config.py` 中读取，不要在多个模块里重复实现解析。
- 修改 Cookie 解析或持久化逻辑时，必须保留空槽位，并补充 `tests/test_cookie_store.py`。
- 修改通知相关逻辑时，同步检查 `nodeseek_sign.py` 与 `notify.py` 的超时和开关读取。
- 修改调度行为时，确认 `docker-compose.yml` 和 `.github/workflows/blank.yml` 的运行入口是否仍一致。
- 修改验证码参数命名时，不要更改 `CLIENT_KEY` 变量名。
- 修改 Worker 时同步更新 `docs/deployment/cloudflare-worker.md`（部署与变量说明）和 `docs/wiki/modules/cloudflare-worker.md`（实现说明），两份实现互不影响。

## 5. 回归验证清单

1. `python -m pytest -q` 全部通过。
2. 单账号 Cookie 正常签到。
3. Cookie 明确失效后账号密码登录恢复。
4. 多账号索引对齐（账号数与 Cookie 数不一致、含空槽位）。
5. Docker 模式 Cookie 文件读写与权限。
6. `TIMEOUT` 生效（主脚本、求解器与通知模块）。
7. `mkdocs build --strict` 通过。

## 6. 已知实现差异

- `scheduler.py` 的代码默认 `RUN_AT=09:00-21:00`。
- `scheduler.py` 在无效格式时回退到 `08:00-10:59`，日志文案也使用该回退值。
- `.env.example` 把 `RUN_AT` 保持注释状态并标注代码默认值 `09:00-21:00`，复制模板后由用户自行决定。
- Docker 容器以 UID/GID 1000 运行，宿主机 `./cookie` 需可写。

文档或注释与运行行为不一致时，以代码实现为准。
