# 模块说明: GitHub Actions Workflows

## 目录

- `.github/workflows/blank.yml`
- `.github/workflows/docker-publish.yml`
- `.github/workflows/docs-pages.yml`
- `.github/workflows/tests.yml`
- `.github/workflows/update-actions.yml`

所有 `uses:` 均固定到完整 commit SHA，由 Dependabot 更新。

## 1. 签到工作流（blank.yml）

- 触发方式
  - `schedule`: `10 16 * * *`（北京时间 00:10，避开 00:00 计数重置临界点）
  - `workflow_dispatch`: 手动触发
- 核心步骤
  1. `actions/checkout`（SHA 固定）
  2. `actions/setup-python`（Python 3.11）
  3. `pip install -r requirements.txt`
  4. `python nodeseek_sign.py`
- 输入来源
  - 账号、`NS_COOKIE`、验证码与通知字段均来自 `secrets`
  - 不再读取 `vars.NS_COOKIE`
- 权限
  - 仅 `contents: read`
  - 配置 `concurrency` 防止重复运行

## 2. Docker 发布工作流（docker-publish.yml）

- 触发方式
  - Release 发布
  - 手动触发（可传 tags 与 push 开关）
  - `docker-test/**` 分支对关键文件变更（同样会推送 `test` 标签镜像）
- 核心步骤
  1. Checkout
  2. Buildx 初始化
  3. 可选登录镜像仓库
  4. 生成镜像元数据
  5. 构建并按条件推送镜像
- 构建输出包含 SBOM 与 provenance。

## 3. 文档发布工作流（docs-pages.yml）

- 在 `docs/**`、`mkdocs.yml` 等变更时构建并部署 GitHub Pages。
- 构建命令为 `mkdocs build --strict`。

## 4. 测试工作流（tests.yml）

- `pytest` 作业：在 Python 3.11 与 3.14 上运行 `python -m pytest -q`。
- `worker` 作业：使用 Node 22 运行 `node --test "tests/*.test.mjs"`，覆盖 Cloudflare Worker 实现。
- 测试不得访问网络、求解验证码或使用真实凭据；Worker 测试通过替换全局 `fetch` 与内存版 KV binding 实现。

## 5. Actions 固定校验（update-actions.yml）

- 在 workflow 变更时运行。
- 拒绝 `@v7`、`@main` 等浮动引用，要求 `uses:` 以 40 位十六进制 commit SHA 结尾。

## 6. 开发注意

- 修改签到脚本环境变量读取逻辑后，应同步核对 `blank.yml` 的变量映射。
- `docker-publish.yml` 使用 `vars.DOCKERHUB_USERNAME` 与 `secrets.DOCKERHUB_TOKEN`；缺失将导致仅本地构建或推送失败。
