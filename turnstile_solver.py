import json
import time
from typing import Dict, Optional, Union
from urllib.parse import urlparse

import requests

from config import REQUEST_TIMEOUT


class TurnstileSolverError(Exception):
    """Turnstile 解决器错误基类"""


class TurnstileSolverTimeout(TurnstileSolverError):
    """求解总时限已到。"""


class TurnstileSolverNetworkError(TurnstileSolverError):
    """验证码服务请求失败（网络/传输层）。"""


def _normalize_api_base_url(api_base_url: str) -> str:
    """Validate and normalize a captcha API base URL."""
    value = (api_base_url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise TurnstileSolverError("API_BASE_URL 必须是有效的 http(s) URL")
    return value


class TurnstileSolver:
    """
    Turnstile 验证码解决工具

    使用 CloudFreed API 解决 Turnstile 验证码，获取验证令牌
    """

    def __init__(
        self,
        api_base_url: str,
        client_key: str,
        max_retries: int = 20,
        retry_interval: int = 6,
        timeout: int = None,
    ):
        base_url = _normalize_api_base_url(api_base_url)
        self.create_task_url = f"{base_url}/createTask"
        self.get_result_url = f"{base_url}/getTaskResult"
        self.client_key = client_key
        self.max_retries = max(1, max_retries)
        self.retry_interval = max(1, retry_interval)
        self.timeout = timeout if timeout is not None else REQUEST_TIMEOUT

    def solve(
        self,
        url: str,
        sitekey: str,
        action: Optional[str] = None,
        user_agent: Optional[str] = None,
        proxy: Optional[Dict[str, Union[str, int]]] = None,
        verbose: bool = False,
    ) -> str:
        """
        解决 Turnstile 验证并返回令牌
        """
        if verbose:
            print("正在创建 Turnstile 验证任务...")

        payload_dict = {
            "clientKey": self.client_key,
            "type": "Turnstile",
            "url": url,
            "siteKey": sitekey,
        }
        if action:
            payload_dict["action"] = action
        if user_agent:
            payload_dict["userAgent"] = user_agent
        if proxy:
            payload_dict["proxy"] = proxy

        headers = {"Content-Type": "application/json"}
        deadline = time.monotonic() + self.timeout + self.max_retries * self.retry_interval

        try:
            response = requests.post(
                self.create_task_url,
                data=json.dumps(payload_dict),
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()

            if result.get("errorId") not in (0, None):
                description = result.get("errorDescription", "未知错误")
                raise TurnstileSolverError(f"创建任务失败: {description}")

            task_id = result.get("taskId")
            if not task_id:
                raise TurnstileSolverError("未能获取到taskId")

            result_payload = json.dumps(
                {"clientKey": self.client_key, "taskId": task_id}
            )

            for attempt in range(1, self.max_retries + 1):
                if time.monotonic() > deadline:
                    raise TurnstileSolverTimeout("验证码求解总时限已到")

                if verbose:
                    print(f"正在获取 Turnstile 验证结果，尝试 {attempt}/{self.max_retries}...")

                result_response = requests.post(
                    self.get_result_url,
                    data=result_payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                result_response.raise_for_status()
                result_data = result_response.json()

                if result_data.get("errorId") not in (0, None):
                    description = result_data.get("errorDescription", "未知错误")
                    raise TurnstileSolverError(f"获取结果失败: {description}")

                status = str(result_data.get("status", "")).lower()
                if status in ("completed", "ready"):
                    # CloudFreed 风格返回 status=completed + result.response.token，
                    # 2captcha 风格返回 status=ready + solution.token。
                    solution = result_data.get("solution") or {}
                    result_obj = result_data.get("result") or {}
                    if not isinstance(result_obj, dict):
                        result_obj = {}
                    response_obj = result_obj.get("response", {})
                    if isinstance(response_obj, dict):
                        token = (
                            response_obj.get("token")
                            or solution.get("token")
                            or result_obj.get("token")
                        )
                    else:
                        token = (
                            response_obj
                            or solution.get("token")
                            or result_obj.get("token")
                        )
                    if not token:
                        raise TurnstileSolverError("未找到验证令牌")
                    if verbose:
                        print(f"Turnstile 验证成功，令牌长度: {len(token)}")
                    return token

                if status in ("failed", "error", "invalid"):
                    description = result_data.get("errorDescription", status)
                    raise TurnstileSolverError(f"验证任务失败: {description}")

                if attempt < self.max_retries:
                    if verbose:
                        print(f"等待 {self.retry_interval} 秒后重试...")
                    time.sleep(self.retry_interval)

            raise TurnstileSolverTimeout(
                f"达到最大重试次数 ({self.max_retries})，验证失败"
            )

        except TurnstileSolverError:
            raise
        except requests.exceptions.RequestException as exc:
            raise TurnstileSolverNetworkError("验证码服务请求错误") from exc
