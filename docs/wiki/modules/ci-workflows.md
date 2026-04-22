# 模块说明: GitHub Actions Workflows

## 目录

- `.github/workflows/blank.yml`
- `.github/workflows/docker-publish.yml`
- `.github/workflows/update-actions.yml`

## 1. 签到工作流（blank.yml）

- 触发方式
  - `schedule`: 每日定时（UTC cron）
  - `workflow_dispatch`: 手动触发
- 核心步骤
  1. `actions/checkout@v6`
  2. `actions/setup-python@v6`（3.11.8）
  3. `pip install curl_cffi requests --upgrade`
  4. `python nodeseek_sign.py`
- 输入来源
  - 大量变量来自 `secrets` / `vars`，包括账号、`NS_COOKIE`、验证码与通知字段

## 2. Docker 发布工作流（docker-publish.yml）

- 触发方式
  - Release 发布
  - 手动触发（可传 tags 与 push 开关）
  - `docker-test/**` 分支对关键文件变更
- 核心步骤
  1. Checkout
  2. Buildx 初始化
  3. 可选登录镜像仓库
  4. 生成镜像元数据
  5. 构建并按条件推送镜像

## 3. Actions 升级检查（update-actions.yml）

- 触发方式
  - 每周一固定时间
  - 手动触发
- 功能
  - 扫描 workflow 中 `actions/*` 版本
  - 查询 actions 仓库最新 release
  - 在 Step Summary 输出升级建议与批量替换示例命令

## 4. 开发注意

- 修改签到脚本环境变量读取逻辑后，应同步核对 `blank.yml` 的变量映射。
- `docker-publish.yml` 使用 `vars.DOCKERHUB_USERNAME` 与 `secrets.DOCKERHUB_TOKEN`；缺失将导致仅本地构建或推送失败。
