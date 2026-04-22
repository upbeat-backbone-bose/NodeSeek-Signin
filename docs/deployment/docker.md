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

发布 Release 时，会自动生成以下标签的镜像：

| 标签 | 说明 | 示例 |
|------|------|------|
| `v{version}` | git tag 版本 | `nodeseek-signin:v0.0.1` |
| `latest` | 最新版本 | `nodeseek-signin:latest` |

## 本地构建

如果需要在本地构建 Docker 镜像，可使用以下命令：

```bash
# 构建镜像
docker build -t nodeseek-signin .

# 运行容器
docker run -d \
  -e NS_COOKIE="your_cookie_here" \
  -e DEBUG="true" \
  nodeseek-signin
```

## Dockerfile 参考

```dockerfile
FROM python:3.14-alpine

RUN apk add --no-cache tzdata ca-certificates
ENV TZ=Asia/Shanghai

RUN pip install --no-cache-dir --upgrade pip

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

CMD ["python", "scheduler.py"]
```
