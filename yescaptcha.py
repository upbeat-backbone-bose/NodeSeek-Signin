import time
from typing import Optional
from urllib.parse import urlparse

from curl_cffi import requests

from config import REQUEST_TIMEOUT


class YesCaptchaSolverError(Exception):
    """YesCaptcha 解决器错误基类"""


class YesCaptchaSolverTimeout(YesCaptchaSolverError):
    """求解总时限已到。"""


class YesCaptchaSolverNetworkError(YesCaptchaSolverError):
    """验证码服务请求失败（网络/传输层）。"""


def _normalize_api_base_url(api_base_url: str) -> str:
    """Validate and normalize a captcha API base URL."""
    value = (api_base_url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise YesCaptchaSolverError("API_BASE_URL 必须是有效的 http(s) URL")
    return value


class YesCaptchaSolver:
    """
    YesCaptcha 验证码解决工具

    使用 YesCaptcha API 解决 Turnstile 验证码，获取验证令牌
    参考文档: https://yescaptcha.atlassian.net/wiki/spaces/YESCAPTCHA/overview
    """

    def __init__(
        self,
        api_base_url: str = "https://api.yescaptcha.com",
        client_key: str = "",
        max_retries: int = 20,
        retry_interval: int = 3,
        timeout: int = None,
        advanced: bool = False,
    ):
        base_url = _normalize_api_base_url(api_base_url)
        self.api_base_url = base_url
        self.create_task_url = f"{base_url}/createTask"
        self.get_result_url = f"{base_url}/getTaskResult"
        self.client_key = client_key
        self.max_retries = max(1, max_retries)
        self.retry_interval = max(1, retry_interval)
        self.timeout = timeout if timeout is not None else REQUEST_TIMEOUT
        self.advanced = advanced

    def solve(
        self,
        url: str,
        sitekey: str,
        user_agent: Optional[str] = None,
        verbose: bool = False,
    ) -> str:
        """解决 Turnstile 验证并返回令牌"""
        if verbose:
            print("正在创建 YesCaptcha 验证任务...")

        task_id = self._create_task(url, sitekey, user_agent, verbose)
        if not task_id:
            raise YesCaptchaSolverError("创建验证码任务失败")

        token = self._get_task_result(task_id, verbose)
        if not token:
            raise YesCaptchaSolverError("获取验证码结果失败")

        if verbose:
            print(f"验证码解决成功，令牌长度: {len(token)}")
        return token

    def _create_task(
        self,
        url: str,
        sitekey: str,
        user_agent: Optional[str] = None,
        verbose: bool = False,
    ) -> Optional[str]:
        """创建验证码任务并返回任务ID"""
        task_type = (
            "TurnstileTaskProxylessM1"
            if self.advanced
            else "TurnstileTaskProxyless"
        )
        data = {
            "clientKey": self.client_key,
            "task": {
                "type": task_type,
                "websiteURL": url,
                "websiteKey": sitekey,
            },
            "softID": "116190",
        }
        if user_agent:
            data["task"]["userAgent"] = user_agent

        try:
            response = requests.post(
                self.create_task_url,
                json=data,
                timeout=self.timeout,
                impersonate="chrome110",
            )
        except Exception as exc:
            raise YesCaptchaSolverNetworkError(
                f"创建验证码任务失败: {type(exc).__name__}"
            ) from exc

        if response.status_code != 200:
            raise YesCaptchaSolverError(
                f"创建验证码任务失败: HTTP {response.status_code}"
            )

        try:
            result = response.json()
        except Exception as exc:
            raise YesCaptchaSolverError(
                "创建验证码任务失败: 响应不是合法 JSON"
            ) from exc

        if result.get("errorId") != 0:
            description = result.get("errorDescription", "未知错误")
            raise YesCaptchaSolverError(f"创建验证码任务失败: {description}")

        task_id = result.get("taskId")
        if not task_id:
            raise YesCaptchaSolverError("创建验证码任务失败: 未返回 taskId")
        if verbose:
            print("成功创建 YesCaptcha 任务")
        return task_id

    def _get_task_result(self, task_id: str, verbose: bool = False) -> Optional[str]:
        """获取任务结果，遇到终态错误立即退出。"""
        data = {"clientKey": self.client_key, "taskId": task_id}
        deadline = time.monotonic() + self.timeout + self.max_retries * self.retry_interval

        for attempt in range(1, self.max_retries + 1):
            if time.monotonic() > deadline:
                raise YesCaptchaSolverTimeout("获取任务结果达到总时限")

            if verbose:
                print(f"尝试获取任务结果 ({attempt}/{self.max_retries})...")

            try:
                response = requests.post(
                    self.get_result_url,
                    json=data,
                    timeout=self.timeout,
                    impersonate="chrome110",
                )
            except Exception as exc:
                raise YesCaptchaSolverNetworkError(
                    f"获取验证码结果失败: {type(exc).__name__}"
                ) from exc

            try:
                result = response.json()
            except Exception as exc:
                raise YesCaptchaSolverError(
                    "获取验证码结果失败: 响应不是合法 JSON"
                ) from exc

            if result.get("errorId", 0) > 0:
                description = result.get("errorDescription", "未知错误")
                raise YesCaptchaSolverError(f"获取验证码结果失败: {description}")

            status = str(result.get("status", "")).lower()
            if status == "ready":
                token = result.get("solution", {}).get("token")
                if verbose and token:
                    print(f"任务已完成，令牌长度: {len(token)}")
                return token

            if status in ("failed", "error", "invalid"):
                description = result.get("errorDescription", status)
                raise YesCaptchaSolverError(f"验证码任务失败: {description}")

            if attempt < self.max_retries:
                if verbose:
                    print(f"任务处理中，等待 {self.retry_interval} 秒后重试...")
                time.sleep(self.retry_interval)
                continue

        raise YesCaptchaSolverTimeout("获取验证码结果超时")
