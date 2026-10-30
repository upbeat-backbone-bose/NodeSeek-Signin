# -*- coding: utf-8 -*-

import base64
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests as py_requests
from curl_cffi import requests
from yescaptcha import YesCaptchaSolver, YesCaptchaSolverError
from turnstile_solver import TurnstileSolver, TurnstileSolverError

from config import DEBUG_MODE, REQUEST_TIMEOUT, get_env_bool, get_env_int, get_env_str
from cookie_store import (
    COOKIE_FILE_PATH,
    CookieFileError,
    align_cookies,
    join_cookies,
    load_cookie_file,
    save_cookie_file,
    split_cookies,
)


_print = print
_debug_mutex = threading.Lock()


def _debug_print(*args, **kwargs):
    """调试模式下打印详细调试信息。"""
    if DEBUG_MODE:
        with _debug_mutex:
            _print("[DEBUG]", *args, **kwargs)


def _mask_string(s: str, show_start: int = 2, show_end: int = 2) -> str:
    """对字符串进行脱敏处理，仅显示首尾字符。"""
    if not s:
        return ""
    if len(s) <= show_start + show_end:
        return "*" * len(s)
    return s[:show_start] + "*" * (len(s) - show_start - show_end) + s[-show_end:]


# ---------------- impersonate 指纹 ----------------
DEFAULT_IMPERSONATE = "chrome146"
# curl_cffi 0.17.0 支持的常用桌面指纹，仅作为 Cloudflare 挑战时的有限回退。
FALLBACK_IMPERSONATE = [
    DEFAULT_IMPERSONATE,
    "chrome142",
    "chrome136",
    "safari184",
    "firefox133",
]

IMPERSONATE_VERSION = get_env_str("NS_IMPERSONATE", DEFAULT_IMPERSONATE)
IMPERSONATE_ATTEMPTS = max(1, min(get_env_int("NS_IMPERSONATE_ATTEMPTS", 3), 5))


def _load_supported_impersonates() -> set:
    """Return the impersonation targets supported by the installed curl_cffi."""
    try:
        from curl_cffi.requests import BrowserType

        return {item.value for item in BrowserType}
    except Exception:
        return set()


SUPPORTED_IMPERSONATE = _load_supported_impersonates()


def _get_impersonate_candidates() -> list[str]:
    """返回主指纹加上有限数量的备选指纹。

    旧的无限回退会构造 43 个候选，单次签到最坏可产生数小时请求。
    这里默认最多 3 个，且允许通过 NS_IMPERSONATE_ATTEMPTS 调整（上限 5）。
    不被当前 curl_cffi 支持的指纹会被剔除，避免配置错误直接让签到失败。
    """
    candidates: list[str] = []
    for value in [IMPERSONATE_VERSION] + FALLBACK_IMPERSONATE:
        if not value:
            continue
        if SUPPORTED_IMPERSONATE and value not in SUPPORTED_IMPERSONATE:
            if value == IMPERSONATE_VERSION:
                print(f"[WARN] 不支持的 impersonate 指纹: {value}，已回退到默认指纹")
            continue
        if value not in candidates:
            candidates.append(value)
        if len(candidates) >= IMPERSONATE_ATTEMPTS:
            break
    if not candidates:
        candidates = [DEFAULT_IMPERSONATE]
    return candidates


IMPERSONATE_CANDIDATES = _get_impersonate_candidates()

# ---------------- 通知模块动态加载 ----------------
hadsend = False
send = None
try:
    from notify import send
    hadsend = True
except ImportError:
    print("未加载通知模块，跳过通知功能")


# ---------------- 环境检测函数 ----------------
def detect_environment():
    """检测当前运行环境"""
    if get_env_bool("IN_DOCKER", False):
        return "docker"

    ql_path_markers = ["/ql/data/", "/ql/config/", "/ql/", "/.ql/"]
    in_ql_env = any(os.path.exists(path) for path in ql_path_markers)

    in_github_env = get_env_bool("GITHUB_ACTIONS", False) or bool(
        get_env_str("GH_PAT") and get_env_str("GITHUB_REPOSITORY")
    )

    if in_ql_env:
        return "qinglong"
    if in_github_env:
        return "github"
    return "unknown"


# ---------------- GitHub Secret 写入函数 ----------------
def save_cookie_to_github_secret(var_name: str, cookie: str) -> bool:
    """通过 GitHub Secrets API 加密更新 Cookie。

    仅当 GH_COOKIE_WRITEBACK=true 时启用，避免默认把会话凭据写入
    明文 Actions Variable。需要 GH_PAT 具备目标仓库的 Secrets 写权限。

    返回值语义：
      True  - 已写入
      False - 写入失败
      None  - 未启用回写（属于配置选择，不是失败）
    """
    if not get_env_bool("GH_COOKIE_WRITEBACK", False):
        print("GitHub Cookie 回写未启用（如需回写请设置 GH_COOKIE_WRITEBACK=true）")
        return None

    token = get_env_str("GH_PAT")
    repo = get_env_str("GITHUB_REPOSITORY")
    if not token or not repo:
        print("GH_PAT 或 GITHUB_REPOSITORY 未设置，跳过 GitHub Secret 更新")
        return False

    try:
        from nacl import encoding, public
    except ImportError:
        print("缺少 PyNaCl，无法加密更新 GitHub Secret")
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        key_response = py_requests.get(
            f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if key_response.status_code != 200:
            print(f"GitHub: 获取 Secrets 公钥失败 ({key_response.status_code})")
            return False
        key_data = key_response.json()

        public_key = public.PublicKey(
            key_data["key"].encode("utf-8"), encoding.Base64Encoder()
        )
        sealed_box = public.SealedBox(public_key)
        encrypted = base64.b64encode(
            sealed_box.encrypt(cookie.encode("utf-8"))
        ).decode("utf-8")

        put_response = py_requests.put(
            f"https://api.github.com/repos/{repo}/actions/secrets/{var_name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": key_data["key_id"]},
            timeout=REQUEST_TIMEOUT,
        )
        if put_response.status_code in (201, 204):
            print(f"GitHub Secret {var_name} 更新成功")
            return True
        print(f"GitHub Secret 更新失败 ({put_response.status_code})")
        return False
    except Exception as exc:
        _debug_print(f"GitHub Secret 更新异常: {exc}")
        print("GitHub Secret 更新异常")
        return False


# ---------------- 青龙面板变量操作 ----------------
def _get_qlapi():
    """青龙会在任务预加载阶段注入全局 QLAPI；普通 Python 下不存在。"""
    return globals().get("QLAPI")


def delete_ql_env(var_name: str) -> bool:
    """删除青龙面板中的指定环境变量"""
    qlapi = _get_qlapi()
    if qlapi is None:
        print("未检测到青龙 QLAPI，跳过环境变量删除")
        return False

    try:
        print(f"查询要删除的环境变量: {var_name}")
        env_result = qlapi.getEnvs({"searchValue": var_name})

        env_ids = []
        if env_result.get("code") == 200 and env_result.get("data"):
            for env in env_result.get("data"):
                if env.get("name") == var_name:
                    env_ids.append(env.get("id"))

        if not env_ids:
            print(f"未找到环境变量: {var_name}")
            return True

        print(f"找到 {len(env_ids)} 个环境变量需要删除: {env_ids}")
        delete_result = qlapi.deleteEnvs({"ids": env_ids})
        if delete_result.get("code") == 200:
            print(f"成功删除环境变量: {var_name}")
            return True
        print("删除环境变量失败")
        return False
    except Exception as exc:
        _debug_print(f"删除环境变量异常: {exc}")
        print("删除环境变量异常")
        return False


def save_cookie_to_ql(var_name: str, cookie: str) -> bool:
    """保存 Cookie 到青龙面板环境变量"""
    qlapi = _get_qlapi()
    if qlapi is None:
        print("未检测到青龙 QLAPI，跳过环境变量更新")
        return False

    try:
        if not delete_ql_env(var_name):
            print("删除已有变量失败，但仍将尝试创建新变量")

        create_result = qlapi.createEnv(
            {
                "envs": [
                    {
                        "name": var_name,
                        "value": cookie,
                        "remarks": "NodeSeek签到自动创建",
                        "status": 2,
                    }
                ]
            }
        )
        if create_result.get("code") == 200:
            print(f"青龙面板环境变量 {var_name} 创建成功")
            return True
        _debug_print(f"青龙面板环境变量创建失败: {create_result}")
        print("青龙面板环境变量创建失败")
        return False
    except Exception as exc:
        _debug_print(f"青龙面板环境变量操作异常: {exc}")
        print("青龙面板环境变量操作异常")
        return False


# ---------------- Docker Cookie 文件保存 ----------------
def save_cookie_to_file(cookie_str: str) -> bool:
    """将 Cookie 列表原子写入私有文件（保留空账号位置）。"""
    try:
        if save_cookie_file(cookie_str, COOKIE_FILE_PATH):
            print(f"Cookie 已成功保存到文件: {COOKIE_FILE_PATH}")
            return True
        return False
    except Exception as exc:
        _debug_print(f"保存Cookie到文件失败: {exc}")
        print("保存Cookie到文件失败")
        return False


# ---------------- 统一变量保存函数 ----------------
def save_cookie(var_name: str, cookie: str):
    """根据当前环境保存 Cookie 到相应位置。

    返回值语义：
      True  - 已保存
      False - 保存失败
      None  - 未执行保存（未启用回写 / 环境不支持），属于配置选择而非失败
    """
    env_type = detect_environment()

    if env_type == "docker":
        print("检测到 Docker 环境，保存 Cookie 到文件...")
        return save_cookie_to_file(cookie)
    if env_type == "qinglong":
        print("检测到青龙环境，保存变量到青龙面板...")
        return save_cookie_to_ql(var_name, cookie)
    if env_type == "github":
        print("检测到 GitHub 环境，保存加密 Secret...")
        return save_cookie_to_github_secret(var_name, cookie)

    print("未检测到支持的环境，跳过变量保存")
    return None


# ---------------- 登录逻辑 ----------------
def session_login(user, password, solver_type, api_base_url, client_key):
    if not client_key:
        print("未配置 CLIENT_KEY，跳过验证码求解和登录")
        return None

    try:
        if solver_type.lower() == "yescaptcha":
            print("正在使用 YesCaptcha 解决验证码...")
            solver = YesCaptchaSolver(
                api_base_url=api_base_url or "https://api.yescaptcha.com",
                client_key=client_key,
            )
        else:  # 默认使用 turnstile_solver
            print("正在使用 TurnstileSolver 解决验证码...")
            solver = TurnstileSolver(
                api_base_url=api_base_url,
                client_key=client_key,
            )

        token = solver.solve(
            url="https://www.nodeseek.com/signIn.html",
            sitekey="0x4AAAAAAAaNy7leGjewpVyR",
            verbose=DEBUG_MODE,
        )
        if not token:
            print("验证码解析失败")
            return None
    except (TurnstileSolverError, YesCaptchaSolverError) as exc:
        # 求解器已经把真实原因（密钥无效、余额不足、超时、请求失败）写进异常，
        # 这里必须透出，否则用户只能看到一句无信息量的"验证码错误"。
        print(f"验证码错误: {exc}")
        return None
    except Exception as exc:
        _debug_print(f"验证码异常: {exc}")
        print("验证码异常")
        return None

    login_impersonate = (
        IMPERSONATE_CANDIDATES[0] if IMPERSONATE_CANDIDATES else DEFAULT_IMPERSONATE
    )
    print(f"[INFO] 使用 impersonate: {login_impersonate}")

    data = {
        "username": user,
        "password": password,
        "token": token,
        "source": "turnstile",
    }
    headers = {
        "origin": "https://www.nodeseek.com",
        "referer": "https://www.nodeseek.com/signIn.html",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Content-Type": "application/json",
    }

    try:
        with requests.Session(impersonate=login_impersonate) as session:
            session.get(
                "https://www.nodeseek.com/signIn.html", timeout=REQUEST_TIMEOUT
            )
            response = session.post(
                "https://www.nodeseek.com/api/account/signIn",
                json=data,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            resp_json = response.json()
            if resp_json.get("success"):
                cookies = session.cookies.get_dict()
                cookie_string = "; ".join(f"{k}={v}" for k, v in cookies.items())
                if not cookie_string:
                    print("登录成功但未获得 Cookie")
                    return None
                return cookie_string

        _debug_print(f"登录失败: {resp_json.get('message')}")
        print("登录失败: 认证失败")
        return None
    except Exception as exc:
        _debug_print(f"登录异常: {exc}")
        print("登录异常: 请求出错")
        return None


# ---------------- 签到逻辑 ----------------
def _is_cloudflare_challenge(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return (
        "just a moment" in lowered
        or "cf-chl" in lowered
        or ("challenge" in lowered and "cloudflare" in lowered)
    )


def _request_with_impersonate_fallback(
    method: str,
    url: str,
    *,
    headers: dict,
    json_data=None,
    timeout: int = None,
):
    """发送请求，只为明确的 Cloudflare 挑战切换有限的备用指纹。

    传输层异常（超时、DNS、连接重置）不会重试，因为签到 POST 不是
    幂等操作，盲目重试可能造成重复签到或放大请求。
    """
    timeout = timeout or REQUEST_TIMEOUT
    candidates = _get_impersonate_candidates()
    deadline = time.monotonic() + timeout * max(1, len(candidates))
    last_resp = None
    last_err = None
    # 记录最后一次实际发出的请求所用的指纹，供错误消息排障使用。
    used = IMPERSONATE_VERSION

    for version in candidates:
        if time.monotonic() >= deadline:
            last_err = TimeoutError("请求总时限已到")
            break
        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                json=json_data,
                impersonate=version,
                timeout=timeout,
            )
        except Exception as exc:
            last_err = exc
            used = version
            _debug_print(f"[WARN] 请求异常 (impersonate={version}): {exc}")
            print(f"[WARN] 请求异常 (impersonate={version})，不再重试")
            break

        last_resp = resp
        used = version
        if resp.status_code not in (403, 503) or not _is_cloudflare_challenge(resp.text):
            return resp, version, None

        print(f"[WARN] Cloudflare challenge (impersonate={version})，尝试下一个指纹...")

    return last_resp, used, last_err


def sign(ns_cookie, ns_random):
    if not ns_cookie:
        return "invalid", "无有效Cookie"

    headers = {
        "origin": "https://www.nodeseek.com",
        "referer": "https://www.nodeseek.com/board",
        "Content-Type": "application/json",
        "Cookie": ns_cookie,
    }
    try:
        url = f"https://www.nodeseek.com/api/attendance?random={ns_random}"
        response, used_impersonate, req_err = _request_with_impersonate_fallback(
            "POST", url, headers=headers, json_data={}, timeout=REQUEST_TIMEOUT
        )
        if req_err is not None:
            return "error", "请求异常"
        if response is None:
            return "error", "请求失败：无响应"
        if response.status_code == 403:
            if _is_cloudflare_challenge(response.text):
                return "forbidden", f"403 Cloudflare challenge (impersonate={used_impersonate})"
            return "forbidden", f"403 Forbidden (impersonate={used_impersonate})"
        if response.status_code == 429:
            return "error", "请求过于频繁 (429)"
        if response.status_code >= 500:
            return "error", f"服务端错误 ({response.status_code})"

        data = response.json()
        msg = data.get("message", "")
        # 判定顺序很重要：先看消息里的明确信号，最后才回退到通用的 success 标志。
        #   - "鸡腿"：本次确实拿到了奖励，属于新签到。
        #   - "已完成签到"：今日已签，需要单独计数。若接口同时返回 success=true，
        #     先前的顺序会让 "already" 永远不会被统计。
        #   - 404 / "请先登录" / "未登录"：会话已失效，必须触发重新登录，
        #     且要优先于 success 标志，否则失效的 Cookie 永远不会被刷新。
        if "鸡腿" in msg:
            return "success", msg
        if "已完成签到" in msg:
            return "already", msg
        if data.get("status") == 404 or "请先登录" in msg or "未登录" in msg:
            return "invalid", msg
        if data.get("success"):
            return "success", msg
        return "fail", msg
    except Exception as exc:
        _debug_print(f"签到请求异常: {exc}")
        return "error", "签到请求异常"


# ---------------- 查询签到收益统计函数 ----------------
# 默认 20 页，与历史行为一致，确保 30 天窗口不被静默截断。
# 若要减少请求数可显式调低，但结果会标记为"数据不完整"。
STATS_MAX_PAGES = max(1, min(get_env_int("STATS_MAX_PAGES", 20), 20))


def get_signin_stats(ns_cookie, days=30):
    """查询前 days 天内的签到收益统计"""
    if not ns_cookie:
        return None, "无有效Cookie"

    if days <= 0:
        days = 1

    headers = {
        "origin": "https://www.nodeseek.com",
        "referer": "https://www.nodeseek.com/board",
        "Cookie": ns_cookie,
    }

    try:
        shanghai_tz = ZoneInfo("Asia/Shanghai")
        now_shanghai = datetime.now(shanghai_tz)
        today_start = datetime(
            now_shanghai.year,
            now_shanghai.month,
            now_shanghai.day,
            tzinfo=shanghai_tz,
        )
        query_start_time = today_start - timedelta(days=days)

        all_records = []
        page = 1
        truncated = False
        deadline = time.monotonic() + max(60, REQUEST_TIMEOUT * 4)

        while page <= STATS_MAX_PAGES:
            if time.monotonic() > deadline:
                _debug_print("统计查询达到总时限，返回已获取的部分数据")
                truncated = True
                break

            url = f"https://www.nodeseek.com/api/account/credit/page-{page}"
            response, _used, req_err = _request_with_impersonate_fallback(
                "GET", url, headers=headers, json_data=None, timeout=REQUEST_TIMEOUT
            )
            if req_err is not None:
                return None, "请求异常"
            if response is None:
                return None, "请求失败：无响应"

            data = response.json()
            if not data.get("success") or not data.get("data"):
                break

            records = data.get("data", [])
            if not records:
                break

            last_record_time = datetime.fromisoformat(
                records[-1][3].replace("Z", "+00:00")
            ).astimezone(shanghai_tz)
            if last_record_time < query_start_time:
                for record in records:
                    record_time = datetime.fromisoformat(
                        record[3].replace("Z", "+00:00")
                    ).astimezone(shanghai_tz)
                    if record_time >= query_start_time:
                        all_records.append(record)
                break

            all_records.extend(records)
            page += 1
            time.sleep(0.5)
        else:
            # 页数用尽仍未触及时间窗口下界，说明数据被截断。
            truncated = True

        signin_records = []
        for record in all_records:
            amount, _balance, description, timestamp = record
            record_time = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            ).astimezone(shanghai_tz)

            if (
                record_time >= query_start_time
                and "签到收益" in description
                and "鸡腿" in description
            ):
                signin_records.append(
                    {
                        "amount": amount,
                        "date": record_time.strftime("%Y-%m-%d"),
                        "description": description,
                    }
                )

        period_desc = f"近{days}天"
        if days == 1:
            period_desc = "今天"
        if truncated:
            # 数据不完整时必须显式说明，避免把部分数据当作完整 30 天窗口。
            period_desc = f"{period_desc}(数据不完整)"

        if not signin_records:
            return {
                "total_amount": 0,
                "average": 0,
                "days_count": 0,
                "records": [],
                "period": period_desc,
                "truncated": truncated,
            }, f"查询成功，但没有找到{period_desc}的签到记录"

        total_amount = sum(record["amount"] for record in signin_records)
        days_count = len(signin_records)
        average = round(total_amount / days_count, 2) if days_count > 0 else 0

        stats = {
            "total_amount": total_amount,
            "average": average,
            "days_count": days_count,
            "records": signin_records,
            "period": period_desc,
            "truncated": truncated,
        }
        return stats, "查询成功"

    except Exception as exc:
        _debug_print(f"查询签到统计异常: {exc}")
        return None, "查询签到统计异常"


# ---------------- 显示签到统计信息 ----------------
def print_signin_stats(stats, account_name):
    """打印签到统计信息"""
    if not stats:
        return

    print(f"\n==== {account_name} 签到收益统计 ({stats['period']}) ====")
    print(f"签到天数: {stats['days_count']} 天")
    print(f"总获得鸡腿: {stats['total_amount']} 个")
    print(f"平均每日鸡腿: {stats['average']} 个")


def _load_accounts():
    """按固定顺序加载账号配置。

    账号顺序即 Cookie 槽位顺序（位置即身份）：

    ==========  ==========================================
    账号序号    对应环境变量
    ==========  ==========================================
    第 1 个     ``USER`` / ``PASS``
    第 2 个     ``USER1`` / ``PASS1``
    第 3 个     ``USER2`` / ``PASS2``
    ...         ...
    ==========  ==========================================

    ``USER1`` 起必须连续（遇到第一个缺失的序号即停止），
    这样才能保证 Cookie 槽位与账号一一对应。
    """
    accounts = []

    user = get_env_str("USER")
    password = get_env_str("PASS")
    if user and password:
        accounts.append({"user": user, "password": password})

    index = 1
    while True:
        user = get_env_str(f"USER{index}")
        password = get_env_str(f"PASS{index}")
        if not (user and password):
            break
        accounts.append({"user": user, "password": password})
        index += 1

    return accounts


def _load_cookies(env_type: str) -> str:
    if env_type == "docker":
        print(f"Docker 环境，尝试从 {COOKIE_FILE_PATH} 读取 Cookie...")
        try:
            raw = load_cookie_file(COOKIE_FILE_PATH)
        except CookieFileError as exc:
            # 单个 Cookie 源不可读不应中断整个签到流程：按空 Cookie 处理。
            print(f"读取 Cookie 文件失败: {exc}")
            print("将使用空 Cookie，必要时可通过账号密码重新登录。")
            return ""
        if raw:
            print("成功从文件加载 Cookie。")
        else:
            print("Cookie 文件不存在或为空，将使用空 Cookie。")
        return raw
    return get_env_str("NS_COOKIE", "")


def _stats_message(stats):
    if not stats:
        return ""
    return (
        f"{stats['period']}已签到{stats['days_count']}天，"
        f"共获得{stats['total_amount']}个鸡腿，平均{stats['average']}个/天"
    )


def run() -> int:
    solver_type = get_env_str("SOLVER_TYPE", "turnstile")
    api_base_url = get_env_str("API_BASE_URL", "")
    client_key = get_env_str("CLIENT_KEY", "")
    ns_random = get_env_str("NS_RANDOM", "false")

    env_type = detect_environment()
    print(f"当前运行环境: {env_type}")

    accounts = _load_accounts()
    cookie_list = split_cookies(_load_cookies(env_type))

    print(f"共发现 {len(accounts)} 个账户配置，{len(cookie_list)} 个现有 Cookie")

    # 账号与 Cookie 按下标一一对应。数量不一致意味着可能存在错位
    # （例如模板里多填了一个 USER/PASS，导致后面所有账号整体后移一位），
    # 这里显式告警而不是让用户从"签到到了别人账号"的现象去反推。
    if accounts and cookie_list and len(accounts) != len(cookie_list):
        print(
            "[警告] 账号数量与 Cookie 数量不一致，可能存在槽位错位："
            f"{len(accounts)} 个账号 vs {len(cookie_list)} 个 Cookie。"
            "请确认 USER/PASS 对应第 1 个账号、USER1/PASS1 对应第 2 个，"
            "以此类推。"
        )
    # 账号数多于 Cookie 数时，多出来的账号没有对应的 Cookie 槽位，其身份
    # 不可信（例如模板里多填了一个 USER/PASS，导致后面所有账号整体后移一位）。
    # 这类账号若贸然重新登录，会为错误账号购买验证码，故直接计为失败。
    # Cookie 数多于账号数属于"尾部账号没有配置凭据"，下标映射仍然成立，
    # 保持原有行为。
    slot_misaligned = (
        bool(accounts) and bool(cookie_list) and len(accounts) > len(cookie_list)
    )

    if not accounts and not cookie_list:
        print("未配置任何账号或 Cookie，退出")
        return 1

    max_count = max(len(accounts), len(cookie_list))
    while len(accounts) < max_count:
        accounts.append({"user": "", "password": ""})
    cookie_list = align_cookies(cookie_list, max_count)

    max_logins = max(0, get_env_int("MAX_LOGIN_ATTEMPTS", max_count))
    login_attempts = 0
    cookies_updated = False
    results = []
    summary_lines = []

    for i in range(max_count):
        account_index = i + 1
        account = accounts[i]
        user = account["user"]
        password = account["password"]
        cookie = cookie_list[i]

        display_user = user if user else f"账号{account_index}"
        masked_user = _mask_string(display_user, 2, 1) if user else display_user

        print(f"\n==== 账号 {masked_user} 开始签到 ====")
        started = time.monotonic()

        misaligned_slot = False
        if cookie:
            result, msg = sign(cookie, ns_random)
        elif slot_misaligned:
            # 账号数多于 Cookie 数时，多出来的账号没有对应的 Cookie 槽位，
            # 它的身份不可信：为它购买验证码既可能花错钱，也可能登录到别人账号。
            result, msg = "fail", "槽位错位，跳过重新登录以避免不必要的验证码消耗"
            misaligned_slot = True
        else:
            result, msg = "invalid", "无Cookie"

        stats = None
        if result in ("success", "already"):
            _debug_print(f"签到结果: {msg}")
            print(f"账号 {masked_user} 签到成功")

            print("正在查询签到收益统计...")
            stats, stats_msg = get_signin_stats(cookie, 30)
            if stats:
                print_signin_stats(stats, masked_user)
            else:
                _debug_print(f"统计查询失败: {stats_msg}")
                print("统计查询失败")
        else:
            _debug_print(f"签到失败或 Cookie 无效: {msg}")
            print("签到失败或 Cookie 无效")

            # 只有明确的 Cookie 失效才重新登录并购买验证码。
            # 网络错误、Cloudflare 403、服务端 5xx 不应触发付费求解。
            if misaligned_slot:
                print("槽位错位，跳过重新登录以避免不必要的验证码消耗")
            elif result != "invalid":
                print("非 Cookie 失效问题，跳过重新登录以避免不必要的验证码消耗")
            elif not (user and password):
                print(f"账号 {masked_user} 无法重新登录: 未配置用户名或密码")
            elif login_attempts >= max_logins:
                print("本次运行已达到最大登录尝试次数，跳过重新登录")
            elif not client_key:
                print("未配置 CLIENT_KEY，无法重新登录")
            else:
                print("尝试重新登录获取新 Cookie...")
                login_attempts += 1
                new_cookie = session_login(
                    user, password, solver_type, api_base_url, client_key
                )
                if not new_cookie:
                    print(f"账号 {masked_user} 登录失败，无法获取新 Cookie")
                else:
                    print("登录成功，使用新 Cookie 重新签到...")
                    result, msg = sign(new_cookie, ns_random)
                    if result in ("success", "already"):
                        _debug_print(f"签到结果: {msg}")
                        print(f"账号 {masked_user} 签到成功")
                        cookie_list[i] = new_cookie
                        cookies_updated = True

                        print("正在查询签到收益统计...")
                        stats, stats_msg = get_signin_stats(new_cookie, 30)
                        if stats:
                            print_signin_stats(stats, masked_user)
                        else:
                            _debug_print(f"统计查询失败: {stats_msg}")
                            print("统计查询失败")

                        # 立即持久化，避免进程中途退出丢失新 Cookie。
                        save_cookie("NS_COOKIE", join_cookies(cookie_list))
                    else:
                        _debug_print(f"重新签到失败: {msg}")
                        print(f"账号 {masked_user} 重新签到仍然失败")

        elapsed = round(time.monotonic() - started, 1)
        success = result in ("success", "already")
        results.append(
            {
                "account": masked_user,
                "status": result,
                "elapsed_seconds": elapsed,
            }
        )

        line = f"账号 {masked_user}: {'✅' if success else '❌'} {result}"
        if stats:
            line += f"（{_stats_message(stats)}）"
        summary_lines.append(line)
        print(f"账号 {masked_user} 完成，耗时 {elapsed}s")

    if cookies_updated and cookie_list:
        print("\n==== 处理完毕，保存更新后的 Cookie ====")
        save_result = save_cookie("NS_COOKIE", join_cookies(cookie_list))
        if save_result is True:
            print("所有 Cookie 已成功保存")
        elif save_result is None:
            print("已跳过保存 Cookie（当前环境未启用对应存储）")
        else:
            print("保存 Cookie 失败，请检查运行环境和配置")

    succeeded_count = sum(1 for item in results if item["status"] == "success")
    already_count = sum(1 for item in results if item["status"] == "already")
    failed_count = len(results) - succeeded_count - already_count

    # 与 Cloudflare Worker 的聚合结构保持一致：
    # succeeded / already / failed 互斥，success 为布尔值表示是否全部成功。
    summary = {
        "total": len(results),
        "success": failed_count == 0 and len(results) > 0,
        "succeeded": succeeded_count,
        "already": already_count,
        "failed": failed_count,
        "results": results,
    }
    print("RESULT " + json.dumps(summary, ensure_ascii=False))

    if hadsend and send is not None:
        try:
            notification = "\n".join(summary_lines)
            if failed_count:
                notification += f"\n\n失败账号数: {failed_count}"
            send("NodeSeek 签到", notification)
        except Exception:
            print("发送通知失败")

    return 0 if failed_count == 0 else 1


# ---------------- 主流程 ----------------
if __name__ == "__main__":
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        print("用户中断")
        sys.exit(130)
