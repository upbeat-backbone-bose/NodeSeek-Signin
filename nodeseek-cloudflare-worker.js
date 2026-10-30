// NodeSeek 签到 Cloudflare Worker
// 使用 2captcha 解决 Turnstile 验证码
//
// 环境变量配置：
// user: 用户名，多个账户用 & 分割，如：user1&user2
// pass: 密码，多个密码用 & 分割，如：pass1&pass2（与 user 一一对应）
// CAPTCHA_API_KEY: 2captcha API 密钥（仅在账号没有可用 Cookie 或 Cookie 明确失效、需要重新登录时才要求配置）
// CAPTCHA_API_URL: 2captcha API 地址（可选，默认 https://api.2captcha.com）
// NS_COOKIE: 已有 Cookie，多个用 & 分割（可选）
// TRIGGER_TOKEN: 手动触发 /checkin 的 Bearer Token（必填，否则 HTTP 触发返回 503）
// CHECKIN_KV: 可选 KV binding，用于 Cookie 持久化和并发锁
// BotToken: Telegram Bot Token（可选）
// ChatID: Telegram Chat ID（可选，用于接收通知）

const COOKIE_KEY = 'nodeseek:cookies';
const LOCK_KEY = 'nodeseek:checkin-lock';
const COOKIE_TTL = 60 * 60 * 24 * 30;
const LOCK_TTL = 600;
const FETCH_TIMEOUT = 25000;

export default {
  async fetch(request, env) {
    return handleRequest(request, env);
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(handleScheduled(env));
  }
};

async function handleRequest(request, env) {
  const url = new URL(request.url);

  if (url.pathname === '/checkin') {
    if (request.method !== 'POST') {
      return jsonResponse({ success: false, message: 'Method Not Allowed' }, 405);
    }

    const expected = (env.TRIGGER_TOKEN || '').trim();
    if (!expected) {
      return jsonResponse(
        { success: false, message: 'TRIGGER_TOKEN 未配置，HTTP 触发已禁用' },
        503
      );
    }

    const authorization = request.headers.get('Authorization') || '';
    const provided = authorization.startsWith('Bearer ')
      ? authorization.slice('Bearer '.length).trim()
      : '';
    if (!provided || provided !== expected) {
      return jsonResponse({ success: false, message: 'Unauthorized' }, 401);
    }

    const rateLimit = await checkRateLimit(env, request);
    if (!rateLimit.allowed) {
      return jsonResponse({ success: false, message: 'Too Many Requests' }, 429);
    }

    const result = await performCheckin(env);
    const status = result.busy ? 409 : result.success ? 200 : 500;
    return jsonResponse(result, status);
  }

  return new Response('NodeSeek 签到服务运行中', { status: 200 });
}

async function handleScheduled(env) {
  const result = await performCheckin(env);
  console.log(
    `定时签到完成: total=${result.total}, success=${result.succeeded}, failed=${result.failed}`
  );
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' }
  });
}

function timeoutSignal(ms) {
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    return AbortSignal.timeout(ms);
  }
  const controller = new AbortController();
  setTimeout(() => controller.abort(), ms);
  return controller.signal;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = FETCH_TIMEOUT) {
  return fetch(url, { ...options, signal: timeoutSignal(timeoutMs) });
}

// ==================== KV 持久化 / 并发锁 / 限流 ====================

function getKv(env) {
  return env && env.CHECKIN_KV ? env.CHECKIN_KV : null;
}

/**
 * 读取 KV 中持久化的 Cookie 槽位。
 *
 * 存储格式为 JSON 对象：{ "0": "cookie...", "2": "cookie..." }，
 * 键是账号下标，只保存非空槽位。旧的纯字符串格式（"a&&b"）仍可读取。
 */
async function loadPersistedSlots(env) {
  const kv = getKv(env);
  if (!kv) return {};
  try {
    const raw = (await kv.get(COOKIE_KEY)) || '';
    if (!raw) return {};
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        const slots = {};
        for (const [index, value] of Object.entries(parsed)) {
          if (value) slots[index] = String(value);
        }
        return slots;
      }
    } catch (parseError) {
      // 旧格式：整条 Cookie 列表
    }
    const legacy = {};
    splitCookieList(raw).forEach((value, index) => {
      if (value) legacy[index] = value;
    });
    return legacy;
  } catch (error) {
    console.error('读取 KV Cookie 失败:', error.message);
    return {};
  }
}

/**
 * 写回 KV 中持久化的 Cookie 槽位（只保存非空槽位）。
 */
async function persistSlots(env, slots) {
  const kv = getKv(env);
  if (!kv) return;
  try {
    const payload = {};
    for (const [index, value] of Object.entries(slots)) {
      if (value) payload[index] = String(value);
    }
    await kv.put(COOKIE_KEY, JSON.stringify(payload), { expirationTtl: COOKIE_TTL });
  } catch (error) {
    console.error('写入 KV Cookie 失败:', error.message);
  }
}

async function acquireLock(env) {
  const kv = getKv(env);
  if (!kv) return true;
  try {
    if (await kv.get(LOCK_KEY)) return false;
    await kv.put(LOCK_KEY, String(Date.now()), { expirationTtl: LOCK_TTL });
    return true;
  } catch (error) {
    console.error('KV 锁操作失败，继续执行:', error.message);
    return true;
  }
}

async function releaseLock(env) {
  const kv = getKv(env);
  if (!kv) return;
  try {
    await kv.delete(LOCK_KEY);
  } catch (error) {
    console.error('释放 KV 锁失败:', error.message);
  }
}

async function checkRateLimit(env, request) {
  const kv = getKv(env);
  if (!kv) return { allowed: true };

  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  const bucket = Math.floor(Date.now() / 600000);
  const key = `nodeseek:rate:${ip}:${bucket}`;
  try {
    const current = parseInt((await kv.get(key)) || '0', 10);
    if (current >= 10) return { allowed: false };
    await kv.put(key, String(current + 1), { expirationTtl: 900 });
    return { allowed: true };
  } catch (error) {
    console.error('KV 限流失败，继续执行:', error.message);
    return { allowed: true };
  }
}

// ==================== 2captcha 验证码解决器 ====================

class TwoCaptchaSolver {
  constructor(apiKey, apiBaseUrl = 'https://api.2captcha.com') {
    const base = String(apiBaseUrl || '').trim().replace(/\/+$/, '');
    if (!/^https?:\/\/[^/]+/i.test(base)) {
      throw new Error('CAPTCHA_API_URL 必须是有效的 http(s) URL');
    }
    this.apiKey = apiKey;
    this.createTaskUrl = `${base}/createTask`;
    this.getResultUrl = `${base}/getTaskResult`;
    this.maxRetries = 40;
    this.retryInterval = 3000;
  }

  async solve(url, sitekey) {
    const taskId = await this._createTask(url, sitekey);
    if (!taskId) {
      throw new Error('创建任务失败：未返回任务ID');
    }
    return this._getTaskResult(taskId);
  }

  async _createTask(url, sitekey) {
    const data = {
      clientKey: this.apiKey,
      task: {
        type: 'TurnstileTaskProxyless',
        websiteURL: url,
        websiteKey: sitekey
      },
      softId: 0
    };

    const response = await fetchWithTimeout(this.createTaskUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const result = await response.json();
    if (result.errorId === 0) {
      return result.taskId;
    }
    throw new Error(
      `API错误 (${result.errorId}): ${result.errorDescription || result.errorCode || '未知错误'}`
    );
  }

  async _getTaskResult(taskId) {
    const data = { clientKey: this.apiKey, taskId };

    for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
      try {
        const response = await fetchWithTimeout(this.getResultUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const result = await response.json();

        if (result.errorId !== 0) {
          const error = new Error(
            `API错误 (${result.errorId}): ${result.errorDescription || result.errorCode || '未知错误'}`
          );
          // API 业务错误是终态，继续轮询只会浪费时间。
          error.terminal = true;
          throw error;
        }

        if (result.status === 'ready') {
          const token = result.solution?.token;
          if (!token) throw new Error('解决成功但未返回令牌');
          return token;
        }

        if (result.status === 'processing') {
          console.log(`[${attempt}/${this.maxRetries}] 验证码处理中...`);
          await this._sleep(this.retryInterval);
          continue;
        }

        throw new Error(`未知状态: ${result.status}`);
      } catch (error) {
        if (error.terminal || attempt === this.maxRetries) {
          throw new Error(`获取结果失败: ${error.message}`);
        }
        console.log(`获取结果请求失败，重试中... (${attempt}/${this.maxRetries})`);
        await this._sleep(this.retryInterval);
      }
    }

    throw new Error(`验证码解决超时（已重试${this.maxRetries}次）`);
  }

  _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

// ==================== NodeSeek 签到逻辑 ====================

/**
 * 按 `&` 或换行切分 Cookie 列表。
 *
 * 中间的空槽位会被保留（表示"该账号暂无 Cookie"），
 * 但末尾的空槽位会被丢弃：它不携带任何 Cookie 信息，
 * 否则会凭空多出一个永远无法签到的账号。
 */
function splitCookieList(raw) {
  if (!raw) return [];
  const slots = String(raw)
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/\n/g, '&')
    .split('&')
    .map(item => item.trim());
  while (slots.length && !slots[slots.length - 1]) {
    slots.pop();
  }
  return slots;
}

function joinCookieList(slots) {
  return slots.map(item => (item ? String(item).trim() : '')).join('&');
}

/**
 * 执行签到主流程
 */
async function performCheckin(env) {
  const users = env.user || '';
  const passwords = env.pass || '';
  const captchaApiKey = env.CAPTCHA_API_KEY || '';
  const captchaApiUrl = env.CAPTCHA_API_URL || 'https://api.2captcha.com';
  const botToken = env.BotToken || '';
  const chatId = env.ChatID || '';

  if (!users || !passwords) {
    const result = aggregateResult(0, 0, 0, 0, '未配置 user 或 pass');
    await sendTelegramMessage(formatTelegramSummary(result), botToken, chatId);
    return result;
  }

  const userList = users.split('&').map(item => item.trim());
  const passList = passwords.split('&').map(item => item.trim());
  if (userList.length !== passList.length) {
    const result = aggregateResult(0, 0, 0, 0, 'user 和 pass 的数量不匹配');
    await sendTelegramMessage(formatTelegramSummary(result), botToken, chatId);
    return result;
  }

  if (!(await acquireLock(env))) {
    return { ...aggregateResult(0, 0, 0, 0, '已有签到任务在运行'), busy: true };
  }

  let succeeded = 0;
  let already = 0;
  let failed = 0;
  const total = userList.filter((user, index) => user || passList[index]).length;

  try {
    // 逐槽位合并 Cookie：
    //   - KV 中已刷新的 Cookie 优先（Worker 上次运行刷新出来的）
    //   - KV 中没有的槽位回退到面板里的 NS_COOKIE
    // 不能整体二选一：面板里的 NS_COOKIE 是静态的，永远不会更新，
    // 若整体优先使用它，KV 持久化就完全失效，每次都要重新购买验证码。
    const envSlots = splitCookieList(env.NS_COOKIE || '');
    const persistedSlots = await loadPersistedSlots(env);

    const maxCount = Math.max(userList.length, envSlots.length);
    const cookieSlots = [];
    const refreshedSlots = {};
    for (let i = 0; i < maxCount; i++) {
      const persisted = persistedSlots[i];
      const fromEnv = envSlots[i] || '';
      cookieSlots[i] = persisted || fromEnv;
      if (persisted) {
        refreshedSlots[i] = persisted;
      } else if (fromEnv) {
        refreshedSlots[i] = fromEnv;
      }
    }

    let cookiesChanged = false;

    for (let i = 0; i < userList.length; i++) {
      const user = userList[i];
      const password = passList[i];
      if (!user && !password) {
        continue;
      }
      if (!user || !password) {
        failed++;
        console.error(`账户 ${i + 1} 配置不完整，已跳过`);
        continue;
      }

      try {
        let cookie = cookieSlots[i] || '';
        let needLogin = !cookie;

        if (cookie) {
          const signResult = await sign(cookie);
          if (signResult.success) {
            if (signResult.already) already++;
            else succeeded++;
            continue;
          }
          if (signResult.needLogin) {
            needLogin = true;
          } else {
            failed++;
            console.error(`账户 ${i + 1} 签到失败: ${signResult.message}`);
            continue;
          }
        }

        if (!needLogin) {
          failed++;
          continue;
        }

        // 只有确实需要登录时才要求配置验证码密钥：
        // 已有可用 Cookie 的账号在纯 Cookie 场景下根本用不到验证码。
        if (!captchaApiKey) {
          failed++;
          console.error(`账户 ${i + 1} 需要登录但未配置 CAPTCHA_API_KEY`);
          continue;
        }

        const loginResult = await sessionLogin(
          user,
          password,
          captchaApiKey,
          captchaApiUrl
        );
        if (!loginResult.success) {
          failed++;
          console.error(`账户 ${i + 1} 登录失败: ${loginResult.message}`);
          continue;
        }

        cookie = loginResult.cookie;
        const signResult = await sign(cookie);
        if (signResult.success) {
          cookieSlots[i] = cookie;
          refreshedSlots[i] = cookie;
          cookiesChanged = true;
          if (signResult.already) already++;
          else succeeded++;
        } else {
          failed++;
          console.error(`账户 ${i + 1} 重新签到失败: ${signResult.message}`);
        }
      } catch (error) {
        failed++;
        console.error(`账户 ${i + 1} 处理异常: ${error.message}`);
      }
    }

    if (cookiesChanged) {
      await persistSlots(env, refreshedSlots);
    }
  } finally {
    await releaseLock(env);
  }

  const result = aggregateResult(total, succeeded, already, failed, '签到完成');
  await sendTelegramMessage(formatTelegramSummary(result), botToken, chatId);
  return result;
}

function aggregateResult(total, succeeded, already, failed, message) {
  return {
    success: total > 0 && failed === 0,
    total,
    succeeded,
    already,
    failed,
    message
  };
}

function formatTelegramSummary(result) {
  const lines = [
    `🔔 NodeSeek 签到结果`,
    '',
    `总计: ${result.total}`,
    `成功: ${result.succeeded}`,
    `已签到: ${result.already}`,
    `失败: ${result.failed}`
  ];
  if (result.message && result.message !== '签到完成') {
    lines.push('', `说明: ${result.message}`);
  }
  return lines.join('\n');
}

/**
 * 登录并获取 Cookie
 */
async function sessionLogin(user, password, captchaApiKey, captchaApiUrl) {
  try {
    const solver = new TwoCaptchaSolver(captchaApiKey, captchaApiUrl);
    const token = await solver.solve(
      'https://www.nodeseek.com/signIn.html',
      '0x4AAAAAAAaNy7leGjewpVyR'
    );

    const loginData = {
      username: user,
      password: password,
      token: token,
      source: 'turnstile'
    };

    const response = await fetchWithTimeout(
      'https://www.nodeseek.com/api/account/signIn',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
          Accept: 'application/json, text/plain, */*',
          'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
          Origin: 'https://www.nodeseek.com',
          Referer: 'https://www.nodeseek.com/signIn.html'
        },
        body: JSON.stringify(loginData)
      }
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    if (!data.success) {
      throw new Error(data.message || '登录失败');
    }

    const cookie = extractCookies(response);
    if (!cookie) {
      throw new Error('登录成功但未获得 Cookie');
    }

    return { success: true, cookie, message: data.message || '登录成功' };
  } catch (error) {
    console.error(`登录失败: ${error.message}`);
    return { success: false, message: error.message };
  }
}

function extractCookies(response) {
  let headers = [];
  if (typeof response.headers.getSetCookie === 'function') {
    headers = response.headers.getSetCookie();
  } else {
    const raw = response.headers.get('set-cookie');
    if (raw) {
      headers = raw.split(/,(?=[^;]+=[^;]+)/);
    }
  }
  return headers
    .map(item => item.split(';')[0].trim())
    .filter(item => item.includes('='))
    .join('; ');
}

/**
 * 执行签到
 */
async function sign(cookie) {
  if (!cookie) {
    return { success: false, needLogin: true, message: '无有效Cookie' };
  }

  try {
    const random = Math.random().toString(36).substring(2, 15);
    const response = await fetchWithTimeout(
      `https://www.nodeseek.com/api/attendance?random=${random}`,
      {
        method: 'POST',
        headers: {
          Cookie: cookie,
          'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
          Accept: 'application/json, text/plain, */*',
          'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
          Origin: 'https://www.nodeseek.com',
          Referer: 'https://www.nodeseek.com/'
        }
      }
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    const msg = data.message || '';

    // 判定顺序：先看消息里的明确信号，最后才回退到通用的 success 标志。
    //   - "鸡腿"：本次确实拿到了奖励，属于新签到。
    //   - "已完成签到"：今日已签，需单独计数。若接口同时返回 success=true，
    //     先前的顺序会让 "already" 永远不会被统计。
    //   - 404 / "请先登录" / "未登录"：会话失效，需重新登录，
    //     且要优先于 success 标志。
    if (msg.includes('鸡腿')) {
      return { success: true, already: false, needLogin: false, message: msg };
    }

    if (msg.includes('已完成签到')) {
      return { success: true, already: true, needLogin: false, message: msg };
    }

    if (data.status === 404 || msg.includes('请先登录') || msg.includes('未登录')) {
      return { success: false, needLogin: true, message: 'Cookie已失效' };
    }

    if (data.success) {
      return { success: true, already: false, needLogin: false, message: msg };
    }

    return { success: false, needLogin: false, message: msg || '签到失败' };
  } catch (error) {
    console.error(`签到失败: ${error.message}`);
    return { success: false, needLogin: false, message: error.message };
  }
}

// ==================== Telegram 通知 ====================

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

async function sendTelegramMessage(message, botToken, chatId) {
  if (!chatId) {
    return;
  }
  if (!botToken || !botToken.trim()) {
    console.log('未配置 BotToken，跳过 Telegram 通知');
    return;
  }

  const now = new Date();
  const formattedTime = now.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });

  const fullMessage = `执行时间: ${formattedTime}\n\n${message}`;

  try {
    const url = `https://api.telegram.org/bot${botToken}/sendMessage`;
    const response = await fetchWithTimeout(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: chatId,
        text: escapeHtml(fullMessage),
        parse_mode: 'HTML'
      })
    });

    if (!response.ok) {
      console.error('Telegram 消息发送失败:', response.status);
    }
  } catch (error) {
    console.error('发送 Telegram 消息时出错:', error.message);
  }
}
