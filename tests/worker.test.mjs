/**
 * Cloudflare Worker 的端到端测试。
 *
 * 不访问真实网络：全局 fetch 被替换为可控的桩，
 * KV binding 用内存 Map 模拟。
 *
 * 覆盖审计发现的问题：
 *   - KV 中已刷新的 Cookie 必须被真正使用（此前 env.NS_COOKIE 恒优先，
 *     导致 KV 持久化完全失效，每次都重新购买验证码）。
 *   - KV 缺失的槽位必须回退到 env.NS_COOKIE。
 *   - 配置错误时必须发送 Telegram 通知（此前完全静默）。
 *   - "已完成签到" 必须被识别为 already。
 *   - Cookie 槽位与账号必须按下标一一对应。
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import worker from '../nodeseek-cloudflare-worker.js';

const COOKIE_KEY = 'nodeseek:cookies';
const LOCK_KEY = 'nodeseek:checkin-lock';

/** 内存版 KV binding。 */
class FakeKv {
  constructor(initial = {}) {
    this.store = new Map(Object.entries(initial));
    this.puts = [];
    this.deletes = [];
  }

  async get(key) {
    return this.store.has(key) ? this.store.get(key) : null;
  }

  async put(key, value, options) {
    this.store.set(key, value);
    this.puts.push({ key, value, options });
  }

  async delete(key) {
    this.deletes.push(key);
    this.store.delete(key);
  }
}

/**
 * 安装 fetch 桩。
 *
 * @param {object} options
 * @param {string[]} options.validCookies 视为已登录、可直接签到的 Cookie
 * @param {string} options.attendanceMessage 其他 Cookie 签到时返回的 message
 * @param {boolean} options.attendanceSuccess 其他 Cookie 签到时返回的 success
 * @param {number} options.attendanceStatus 其他 Cookie 签到时返回的 HTTP 状态码
 */
function installFetchStub(options = {}) {
  const calls = [];
  const attendanceMessage = options.attendanceMessage ?? '获得 5 个鸡腿';
  const attendanceSuccess = options.attendanceSuccess ?? true;
  const attendanceStatus = options.attendanceStatus ?? 200;
  // 已通过登录取得的 Cookie，签到时视为成功。
  const loggedInCookies = new Set();
  const validCookies = new Set(options.validCookies ?? []);

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    const href = typeof url === 'string' ? url : url.toString();
    calls.push({ href, init });

    if (href.includes('/api/attendance')) {
      const cookie = init?.headers?.Cookie || '';
      if (loggedInCookies.has(cookie) || validCookies.has(cookie)) {
        return jsonResponse({ success: true, message: '获得 5 个鸡腿' });
      }
      return jsonResponse(
        {
          success: attendanceSuccess,
          message: attendanceMessage,
        },
        attendanceStatus
      );
    }
    if (href.includes('/api/account/signIn')) {
      loggedInCookies.add('session=new-cookie');
      return jsonResponse({ success: true, message: '登录成功' });
    }
    if (href.includes('api.telegram.org')) {
      return jsonResponse({ ok: true });
    }
    if (href.includes('createTask')) {
      return jsonResponse({ errorId: 0, taskId: 'task-1' });
    }
    if (href.includes('getTaskResult')) {
      return jsonResponse({
        errorId: 0,
        status: 'ready',
        solution: { token: 'captcha-token' },
      });
    }
    return jsonResponse({});
  };

  return {
    calls,
    restore: () => {
      globalThis.fetch = originalFetch;
    },
  };
}

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    headers: { getSetCookie: () => ['session=new-cookie; Path=/'] },
  };
}

function makeEnv(overrides = {}) {
  return {
    user: 'alice',
    pass: 'pw',
    CAPTCHA_API_KEY: 'key',
    TRIGGER_TOKEN: 'secret-token',
    ...overrides,
  };
}

function checkinRequest(env, token = 'secret-token') {
  return new Request('https://worker.example/checkin', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
}

function attendanceCookies(calls) {
  return calls
    .filter((c) => c.href.includes('/api/attendance'))
    .map((c) => c.init.headers.Cookie);
}

test('未配置 TRIGGER_TOKEN 时 HTTP 触发返回 503', async () => {
  const stub = installFetchStub();
  try {
    const env = makeEnv({ TRIGGER_TOKEN: '' });
    const response = await worker.fetch(checkinRequest(env), env);
    assert.equal(response.status, 503);
  } finally {
    stub.restore();
  }
});

test('错误的 Bearer Token 返回 401', async () => {
  const stub = installFetchStub();
  try {
    const env = makeEnv();
    const response = await worker.fetch(checkinRequest(env, 'wrong'), env);
    assert.equal(response.status, 401);
  } finally {
    stub.restore();
  }
});

test('KV 中的已刷新 Cookie 会被真正使用，而不是被 env 的旧 Cookie 覆盖', async () => {
  // 面板里的 NS_COOKIE 永远是旧值；KV 里是上次运行刷新出来的新值。
  const kv = new FakeKv({ [COOKIE_KEY]: JSON.stringify({ 0: 'fresh-cookie' }) });
  const stub = installFetchStub({ validCookies: ['fresh-cookie'] });
  try {
    const env = makeEnv({ NS_COOKIE: 'stale-cookie', CHECKIN_KV: kv });
    const response = await worker.fetch(checkinRequest(env), env);

    assert.equal(response.status, 200);
    assert.deepEqual(attendanceCookies(stub.calls), ['fresh-cookie']);

    // 不应触发重新登录（那意味着又付了一次验证码）。
    assert.ok(
      !stub.calls.some((c) => c.href.includes('/api/account/signIn')),
      '有效 Cookie 不应触发登录'
    );
  } finally {
    stub.restore();
  }
});

test('KV 中缺失的槽位回退到 env.NS_COOKIE', async () => {
  const kv = new FakeKv({ [COOKIE_KEY]: JSON.stringify({ 0: 'fresh-cookie' }) });
  const stub = installFetchStub({
    validCookies: ['fresh-cookie', 'env-second'],
  });
  try {
    const env = makeEnv({
      user: 'alice&bob',
      pass: 'pw1&pw2',
      NS_COOKIE: 'stale-cookie&env-second',
      CHECKIN_KV: kv,
    });
    await worker.fetch(checkinRequest(env), env);

    assert.deepEqual(attendanceCookies(stub.calls), ['fresh-cookie', 'env-second']);
  } finally {
    stub.restore();
  }
});

test('KV 使用旧的纯字符串格式时仍可读取', async () => {
  const kv = new FakeKv({ [COOKIE_KEY]: 'legacy-cookie' });
  const stub = installFetchStub({ validCookies: ['legacy-cookie'] });
  try {
    const env = makeEnv({ CHECKIN_KV: kv });
    await worker.fetch(checkinRequest(env), env);

    assert.deepEqual(attendanceCookies(stub.calls), ['legacy-cookie']);
  } finally {
    stub.restore();
  }
});

test('重新登录后新 Cookie 会按槽位写回 KV', async () => {
  const kv = new FakeKv();
  const stub = installFetchStub({
    attendanceMessage: '未登录',
    attendanceSuccess: false,
  });
  try {
    const env = makeEnv({
      user: 'alice&bob',
      pass: 'pw1&pw2',
      NS_COOKIE: 'stale-1&stale-2',
      CHECKIN_KV: kv,
    });
    const response = await worker.fetch(checkinRequest(env), env);
    assert.equal(response.status, 200);

    const put = kv.puts.find((p) => p.key === COOKIE_KEY);
    assert.ok(put, '应写回 KV');
    const payload = JSON.parse(put.value);
    assert.equal(payload['0'], 'session=new-cookie');
    assert.equal(payload['1'], 'session=new-cookie');
  } finally {
    stub.restore();
  }
});

test('配置错误时发送 Telegram 通知，而不是静默失败', async () => {
  const stub = installFetchStub();
  try {
    // 缺少 user / pass
    const env = makeEnv({ user: '', pass: '', BotToken: 'bot', ChatID: '42' });
    const response = await worker.fetch(checkinRequest(env), env);

    assert.equal(response.status, 500);
    const telegram = stub.calls.find((c) => c.href.includes('api.telegram.org'));
    assert.ok(telegram, '配置错误时必须发送 Telegram 通知');
    const body = JSON.parse(telegram.init.body);
    assert.ok(body.text.includes('未配置'), '通知内容应说明失败原因');
  } finally {
    stub.restore();
  }
});

test('缺少 CAPTCHA_API_KEY 但 Cookie 可用时仍能正常签到', async () => {
  const stub = installFetchStub({ validCookies: ['c1'] });
  try {
    const env = makeEnv({
      CAPTCHA_API_KEY: '',
      NS_COOKIE: 'c1',
      BotToken: 'bot',
      ChatID: '42',
    });
    const response = await worker.fetch(checkinRequest(env), env);
    const body = await response.json();

    assert.equal(response.status, 200);
    assert.equal(body.succeeded, 1);
    assert.equal(body.failed, 0);
    assert.ok(
      !stub.calls.some((c) => c.href.includes('/api/account/signIn')),
      '有效 Cookie 不应触发登录'
    );
  } finally {
    stub.restore();
  }
});

test('缺少 CAPTCHA_API_KEY 且账号无 Cookie 时计为失败并发送 Telegram 通知', async () => {
  const stub = installFetchStub();
  try {
    const env = makeEnv({
      CAPTCHA_API_KEY: '',
      BotToken: 'bot',
      ChatID: '42',
    });
    const response = await worker.fetch(checkinRequest(env), env);
    const body = await response.json();

    assert.equal(response.status, 500);
    assert.equal(body.failed, 1);
    assert.ok(
      stub.calls.some((c) => c.href.includes('api.telegram.org')),
      '必须发送 Telegram 通知'
    );
    assert.ok(
      !stub.calls.some((c) => c.href.includes('createTask')),
      '缺少密钥时不应尝试购买验证码'
    );
  } finally {
    stub.restore();
  }
});

test('"已完成签到" 被识别为 already 并单独计数', async () => {
  const stub = installFetchStub({
    attendanceMessage: '今日已完成签到',
    attendanceSuccess: true,
  });
  try {
    const env = makeEnv({ NS_COOKIE: 'c1' });
    const response = await worker.fetch(checkinRequest(env), env);
    const body = await response.json();

    assert.equal(response.status, 200);
    assert.equal(body.already, 1);
    assert.equal(body.succeeded, 0);
    assert.equal(body.failed, 0);
    assert.equal(body.success, true);
  } finally {
    stub.restore();
  }
});

test('接口用 500 表达"今天已完成签到"时仍识别为 already', async () => {
  // 实测（2026-11-01）：同一天重复签到返回 HTTP 500 +
  // {"success": false, "message": "今天已完成签到，请勿重复操作"}。
  const stub = installFetchStub({
    attendanceMessage: '今天已完成签到，请勿重复操作',
    attendanceSuccess: false,
    attendanceStatus: 500,
  });
  try {
    const env = makeEnv({ NS_COOKIE: 'c1' });
    const response = await worker.fetch(checkinRequest(env), env);
    const body = await response.json();

    assert.equal(response.status, 200);
    assert.equal(body.already, 1);
    assert.equal(body.failed, 0);
    assert.equal(body.success, true);
  } finally {
    stub.restore();
  }
});

test('5xx 正文提到未登录时不触发重新登录', async () => {
  // 5xx 不代表 Cookie 失效，needLogin 会购买验证码。
  const stub = installFetchStub({
    attendanceMessage: '请先登录',
    attendanceSuccess: false,
    attendanceStatus: 500,
  });
  try {
    const env = makeEnv({ NS_COOKIE: 'c1' });
    const response = await worker.fetch(checkinRequest(env), env);
    const body = await response.json();

    assert.equal(body.failed, 1);
    assert.equal(
      stub.calls.filter((c) => c.href.includes('/api/account/signIn')).length,
      0,
      '服务端故障不应触发登录'
    );
  } finally {
    stub.restore();
  }
});

test('拿到奖励时记为 succeeded 而非 already', async () => {
  const stub = installFetchStub({
    validCookies: ['c1'],
    attendanceMessage: '签到成功，获得 5 个鸡腿',
  });
  try {
    const env = makeEnv({ NS_COOKIE: 'c1' });
    const response = await worker.fetch(checkinRequest(env), env);
    const body = await response.json();

    assert.equal(body.succeeded, 1);
    assert.equal(body.already, 0);
  } finally {
    stub.restore();
  }
});

test('末尾多余分隔符不产生幽灵账号', async () => {
  const stub = installFetchStub({ validCookies: ['c1', 'c2'] });
  try {
    const env = makeEnv({
      user: 'alice&bob',
      pass: 'pw1&pw2',
      NS_COOKIE: 'c1&c2&',
    });
    const response = await worker.fetch(checkinRequest(env), env);
    const body = await response.json();

    assert.equal(body.total, 2);
    assert.equal(body.failed, 0);
    assert.equal(response.status, 200);
  } finally {
    stub.restore();
  }
});

test('Cookie 槽位与账号按下标一一对应', async () => {
  const stub = installFetchStub({
    validCookies: ['c1', 'c3'],
    attendanceMessage: '未登录',
    attendanceSuccess: false,
  });
  try {
    // 第 2 个账号没有 Cookie，应触发登录；第 1、3 个直接用已有 Cookie。
    const env = makeEnv({
      user: 'alice&bob&carol',
      pass: 'pw1&pw2&pw3',
      NS_COOKIE: 'c1&&c3',
    });
    await worker.fetch(checkinRequest(env), env);

    // 只有第 2 个账号（空 Cookie）会走到登录后的重签。
    const usedCookies = attendanceCookies(stub.calls);
    assert.ok(
      usedCookies.includes('c1') && usedCookies.includes('c3'),
      '有 Cookie 的账号应直接使用自己的 Cookie'
    );

    const logins = stub.calls.filter((c) => c.href.includes('/api/account/signIn'));
    assert.equal(logins.length, 1, '只有缺 Cookie 的账号需要登录');
    const loginBody = JSON.parse(logins[0].init.body);
    assert.equal(loginBody.username, 'bob', '登录的应是第 2 个账号');
  } finally {
    stub.restore();
  }
});

test('对外响应不包含用户名或逐账号细节', async () => {
  const stub = installFetchStub();
  try {
    const env = makeEnv({ user: 'alice', pass: 'secret-pw' });
    const response = await worker.fetch(checkinRequest(env), env);
    const text = await response.text();

    assert.ok(!text.includes('alice'), '响应不得包含用户名');
    assert.ok(!text.includes('secret-pw'), '响应不得包含密码');
    assert.ok(!text.includes('results'), '响应不得包含逐账号结果');
  } finally {
    stub.restore();
  }
});

test('KV 锁在任务结束后被释放', async () => {
  const kv = new FakeKv();
  const stub = installFetchStub();
  try {
    const env = makeEnv({ CHECKIN_KV: kv });
    await worker.fetch(checkinRequest(env), env);

    assert.ok(kv.deletes.includes(LOCK_KEY), '应释放锁');
  } finally {
    stub.restore();
  }
});
