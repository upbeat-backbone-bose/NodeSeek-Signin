# NodeSeek-Signin Wiki

## 文档导航

- `architecture.md`: 系统架构、运行形态与关键数据流。
- `interfaces.md`: 环境变量、外部 API、运行入口与 I/O 接口。
- `developer-guide.md`: 本地开发、调试、验证与常见变更流程。
- `modules/nodeseek-sign.md`: 核心签到脚本实现细节。
- `modules/scheduler.md`: 定时调度器实现与时间计算逻辑。
- `modules/solvers-and-notify.md`: 验证码求解器与通知模块说明。
- `modules/cloudflare-worker.md`: Cloudflare Worker 独立实现说明。
- `modules/ci-workflows.md`: GitHub Actions 工作流与触发条件。
- `concepts/account-cookie-lifecycle.md`: 多账号与 Cookie 生命周期机制。

## 项目概览

该仓库是一个 Python 脚本型项目，用于 NodeSeek 自动签到，支持多账号、Cookie 续期、验证码自动求解、通知推送，以及 GitHub Actions / Docker Compose / 青龙等多环境运行。

核心执行路径如下：

1. `scheduler.py`（可选）决定执行时间并调用 `nodeseek_sign.py`。
2. `nodeseek_sign.py` 按账号与 Cookie 执行签到，失败时尝试登录刷新。
3. 成功后查询近 30 天签到收益，并通过 `notify.py` 发送通知（若可用）。
4. 新 Cookie 根据环境回写到 Docker 文件、青龙变量或 GitHub Actions Variables。

## 代码边界

- 业务核心在根目录 Python 文件，不是 package 化工程。
- `nodeseek-cloudflare-worker.js` 是独立 JS 版本实现，不参与 Python 主链路。
- `.github/workflows/` 仅负责 CI/CD 与定时触发，不包含业务逻辑实现。
- `docs/` 目录是面向用户的部署与配置文档；`docs/wiki/` 是面向开发者的代码导向文档。
