# 验证码解决方案

NodeSeek 论坛使用 Cloudflare Turnstile 验证码。当 Cookie 失效或使用账号密码登录时，需要通过验证码解决服务自动获取验证令牌。

## 方案一：CloudFreed 自建服务

CloudFreed 是基于 curl-impersonate 的自托管方案，支持解决 Cloudflare Turnstile 验证码。

### 部署 CloudFreed

CloudFreed 可以通过 Docker 快速部署：

```bash
# 方式一：直接运行
docker run -p 3000:3000 ghcr.io/cuberetry/cloudfreed:latest

# 方式二：使用 Docker Compose
# 创建 docker-compose.yml
services:
  cloudfreed:
    image: ghcr.io/cuberetry/cloudfreed:latest
    ports:
      - "3000:3000"
    restart: unless-stopped
```

部署后服务地址为 `http://<你的服务器IP>:3000`

### 配置环境变量

| 变量名称 | 说明 |
| :------: | :--- |
| `SOLVER_TYPE` | 设置为 `turnstile` |
| `API_BASE_URL` | CloudFreed 服务地址，如 `http://127.0.0.1:3000` |
| `CLIENT_KEY` | 验证码服务密钥。Python 流程中为必填：未配置时脚本会跳过验证码求解与登录 |
| `USER`/`PASS` 或 `USER1`/`PASS1`... | NodeSeek 论坛用户名/密码 |

### 示例配置

```bash
# .env 文件示例
SOLVER_TYPE=turnstile
API_BASE_URL=http://127.0.0.1:3000
CLIENT_KEY=your_client_key_here
USER=your_username
PASS=your_password
# USER1=your_username1
# PASS1=your_password1
```

> **注意**：自建 CloudFreed 需要能够访问 Cloudflare，建议部署在海外服务器。

---

## 方案二：YesCaptcha 商业服务

YesCaptcha 是托管式验证码解决服务，无需自行部署。

### 注册账号

1. 访问 [YesCaptcha](https://yescaptcha.com/i/d6WKIR) 注册账号
2. 注册后联系客服可免费获得余额（约可使用60次登录）

### 配置环境变量

| 变量名称 | 说明 |
| :------: | :--- |
| `CLIENT_KEY` | YesCaptcha 的 API 密钥。Python 流程中为必填：未配置时脚本会跳过验证码求解与登录 |
| `USER`/`PASS` 或 `USER1`/`PASS1`... | NodeSeek 论坛用户名/密码 |
| `SOLVER_TYPE` | 设置为 `yescaptcha` |

> **提示**：YesCaptcha 提供两个服务节点，可根据网络情况选择：
> - 国际节点：`https://api.yescaptcha.com`（默认）
> - 国内节点：`https://cn.yescaptcha.com`

---

## 方案对比

| | CloudFreed 自建 | YesCaptcha 托管 |
|--|----------------|----------------|
| **部署难度** | 需要自行部署维护 | 即开即用 |
| **成本** | 服务器费用 | 按调用次数付费 |
| **隐私** | 数据完全自主 | 需将请求发送给第三方 |
| **网络要求** | 服务器需访问 Cloudflare | 无特殊要求 |
| **速度** | 取决于服务器性能 | 取决于服务响应 |

---

## 常见问题

### 1. 验证码解决失败

- 检查 `SOLVER_TYPE` 是否与验证码服务匹配
- 确认 `API_BASE_URL` 可访问
- 验证 `CLIENT_KEY` 正确
- 查看服务日志排查具体错误

### 2. 达到最大重试次数

- TurnstileSolver 默认最多轮询 20 次，间隔 6 秒，并受总时限约束
- 遇到 `failed` / `error` / `invalid` 等终态会立即停止，不会继续消耗时间
- 可通过传入 `max_retries` 参数调整

### 3. Cookie 有效期

- 只有 Cookie 缺失或明确失效（404 / 未登录 / 请先登录）时才会重新登录并消耗验证码
- GitHub Actions 默认不会自动回写；需要设置 `GH_COOKIE_WRITEBACK=true` 并提供 `GH_PAT`
- Docker 模式在重新登录刷新出 Cookie 后，会原子写入 `cookie/NS_COOKIE.txt`
- 建议定期检查 Cookie 有效性
