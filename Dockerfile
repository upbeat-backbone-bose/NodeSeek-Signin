# 使用轻量级的 Python 基础镜像（固定到明确的 patch 版本）
FROM python:3.14.10-alpine3.24

# 设置时区为 GMT+8
RUN apk add --no-cache tzdata ca-certificates
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    IN_DOCKER=true

# 升级 pip 到最新版本以修复安全漏洞
RUN pip install --no-cache-dir --upgrade pip

# 设置工作目录
WORKDIR /app

# 复制 requirements.txt 并安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制所有 .py 文件到工作目录
COPY *.py ./

# 使用非 root 用户运行；宿主机 ./cookie 目录需归属 UID/GID 1000
RUN addgroup -g 1000 app \
    && adduser -D -u 1000 -G app app \
    && mkdir -p /app/cookie \
    && chown -R app:app /app

USER app

# heartbeat 由 scheduler.py 持续更新；超过 10 分钟未更新视为不健康
HEALTHCHECK --interval=5m --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import os,sys,time; p=os.getenv('HEARTBEAT_FILE','./cookie/heartbeat'); sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p) < 600 else 1)"

# 设置默认启动命令
CMD ["python", "scheduler.py"]
