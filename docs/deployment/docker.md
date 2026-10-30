# Docker 镜像构建与发布

## 概述

本项目支持通过 GitHub Actions 自动构建并发布 Docker 镜像到 Docker Hub。

**镜像地址**：[https://hub.docker.com/r/ryachueng/nodeseek-signin](https://hub.docker.com/r/ryachueng/nodeseek-signin)

## 触发条件

当在 GitHub 上创建或发布新的 Release 时，自动触发 Docker 镜像的构建和发布。

## 配置步骤

### 1. 创建 Docker Hub Access Token

1. 登录 [Docker Hub](https://hub.docker.com/)
2. 点击右上角头像 → "Account Settings"
3. 左侧菜单选择 "Security" → "Access Tokens"
4. 点击 "Generate Access Token"
5. 输入 Token 名称（如 `github-actions`）
6. 复制生成的 Token（请妥善保存，关闭后无法再次查看）

### 2. 添加到 GitHub 仓库配置

进入仓库 `Settings` → `Secrets and variables` → `Actions`，添加以下配置：

| 变量类型 | 名称 | 说明 |
|---------|------|------|
| Variables | `DOCKERHUB_REGISTRY` | 镜像仓库地址，默认 `docker.io` |
| Variables | `DOCKERHUB_USERNAME` | Docker Hub 用户名 |
| Secrets | `DOCKERHUB_TOKEN` | Docker Hub Access Token |

### 3. 发布 Release 触发构建

1. 进入 GitHub 仓库页面
2. 点击 "Releases" → "Draft a new release"
3. 填写版本号（遵循 semver 规范，如 `v1.0.0`）
4. 点击 "Publish release"

## 镜像标签策略

构建会生成以下标签的镜像：

| 标签 | 说明 | 示例 |
|------|------|------|
| `v{version}` | git tag 版本 | `nodeseek-signin:v0.0.1` |
| `latest` | 最新 Release | `nodeseek-signin:latest` |
| `test` | 手动触发默认标签或 `docker-test/**` 分支构建 | `nodeseek-signin:test` |

手动触发（workflow_dispatch）时可通过 `docker_tags` 输入额外指定标签，多个标签用逗号分隔，例如 `v1.0.0,edge` 会同时生成这两个标签。

## 本地构建

如果需要在本地构建 Docker 镜像，可使用以下命令：

```bash
# 构建镜像
docker build -t nodeseek-signin .

# 运行容器（Cookie 目录需归属 UID 1000）
mkdir -p cookie
sudo chown -R 1000:1000 cookie
docker run -d \
  --name nodeseek-signin \
  --user 1000:1000 \
  --env-file .env \
  -e IN_DOCKER=true \
  -v "$PWD/cookie:/app/cookie" \
  nodeseek-signin
```

## Dockerfile 参考

```dockerfile
FROM python:3.14.10-alpine3.24

RUN apk add --no-cache tzdata ca-certificates
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    IN_DOCKER=true

RUN pip install --no-cache-dir --upgrade pip
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./

RUN addgroup -g 1000 app \
    && adduser -D -u 1000 -G app app \
    && mkdir -p /app/cookie \
    && chown -R app:app /app
USER app

HEALTHCHECK --interval=5m --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import os,sys,time; p=os.getenv('HEARTBEAT_FILE','./cookie/heartbeat'); sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p) < 600 else 1)"

CMD ["python", "scheduler.py"]
```

> 镜像中的 Python 补丁版本会随依赖升级调整；请以仓库根目录的实际 `Dockerfile` 为准。
