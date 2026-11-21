# NodeSeek-Signin 文档站

欢迎来到 NodeSeek-Signin 文档站。

本页面包含两类内容：

- 使用文档：面向部署和配置。
- 开发者 Wiki：面向代码结构、模块职责和执行流程。

## 快速入口

- 项目说明：[仓库根目录 README](https://github.com/upbeat-backbone-bose/NodeSeek-Signin)
- 环境变量：[环境变量手册](configuration/config.md)
- 验证码方案：[验证码解决方案](configuration/solutions.md)
- GitHub Actions 部署：[GitHub Actions 部署](deployment/github-actions.md)
- Docker Compose 部署：[Docker Compose 部署](deployment/docker-compose.md)
- Docker 镜像构建发布：[Docker 镜像构建发布](deployment/docker.md)
- Cloudflare Worker 部署：[Cloudflare Worker 部署](deployment/cloudflare-worker.md)
- 青龙面板部署：[青龙面板部署](deployment/qinglong-panel.md)
- 开发者 Wiki：[开发者 Wiki](wiki/index.md)

## 常用命令

```bash
pip install -r requirements.txt -r requirements-dev.txt
python test_run.py
python nodeseek_sign.py
docker compose up -d
```
