# AGENTS.md

NodeSeek auto sign-in: a small Python app plus a standalone Cloudflare Worker. User docs are mostly Chinese; code and config are the source of truth when docs disagree.

## Commands

- Install: `python -m pip install -r requirements.txt -r requirements-dev.txt`. The dev file adds pytest, python-dotenv and MkDocs.
- Configure: copy `.env.example` to `.env` (`Copy-Item .env.example .env` on PowerShell), then fill in real values.
- Unit tests: `python -m pytest -q`. Tests must not access the network, solve captchas, or use real credentials.
- `python test_run.py` loads `.env`, then launches `nodeseek_sign.py` as a subprocess. It has no assertions and performs live NodeSeek requests that can consume captcha credits; do not treat it as a unit test.
- `python nodeseek_sign.py` runs one check-in cycle and exits non-zero if any account fails. It does **not** load `.env`.
- `python scheduler.py` runs forever. If it starts inside a `RUN_AT` random window it runs immediately once; after each run it waits for the next day's window.
- Docker: `docker compose up -d`; the container runs as UID/GID 1000 with `IN_DOCKER=true`.
- Docs: `mkdocs serve`; CI runs `mkdocs build --strict`.
- No linter, formatter, or typechecker is configured. Do not invent commands for them.

## Runtime layout

- `config.py` centralizes `get_env_str`, `get_env_int`, `get_env_bool`, `DEBUG_MODE`, and `REQUEST_TIMEOUT`. Reuse it instead of adding local helpers.
- `cookie_store.py` parses and persists cookie lists. Positions are account identity; empty slots must be preserved (`cookie1&&cookie3`). Writes are atomic, `fsync`ed, and `0600`.
- `nodeseek_sign.py` is the core. `run()` is importable and returns an exit code; execution is under `if __name__ == "__main__"`. Useful seams are `sign`, `session_login`, `get_signin_stats`, `_request_with_impersonate_fallback`, and `run`.
- `scheduler.py` runs the child via an absolute script path and the repo directory as cwd. It enforces `TASK_TIMEOUT`, forwards stop signals, writes `cookie/heartbeat` (including while the child runs), and uses a POSIX `flock` lock when available.
- `notify.py` is optional (`from notify import send` may fail without breaking check-in). Its `push_config` snapshots environment variables once at import; `NOTIFY_CONFIG_JSON` can override fields. A new channel needs entries in `push_config` and `add_notify_function`. Channel threads are daemonized and joined with `NOTIFY_THREAD_TIMEOUT`.
- `nodeseek-cloudflare-worker.js` is a separate implementation with different variable names (`user`, `pass`, `CAPTCHA_API_KEY`, `TRIGGER_TOKEN`, `CHECKIN_KV`, `BotToken`, `ChatID`) and a 2captcha backend. Changes to the Python flow do not propagate there.
- `CLOUDFLARE_WORKER_README.md` is only a pointer; maintain `docs/deployment/cloudflare-worker.md`.

## Verified config gotchas

- Runtime uses `CLIENT_KEY`; `.env.example` keeps `CLIENT_KEY` commented out so a fresh copy never ships a live placeholder key.
- `NS_COOKIE` supports both `&` and newlines in Python and the Worker. Empty slots are preserved; do not filter them when saving.
- `NS_RANDOM` defaults to `"false"` and is passed through as a raw query-string value, not parsed as a boolean.
- `scheduler.py` defaults to `RUN_AT=09:00-21:00` when unset, but falls back to `08:00-10:59` when the value is malformed. `.env.example` keeps `RUN_AT` commented out and points at the code default `09:00-21:00`.
- `IN_DOCKER=true` makes the script read cookies from `cookie/NS_COOKIE.txt` and ignore the `NS_COOKIE` environment variable. The file is gitignored.
- `TIMEOUT`, `DEBUG`, `NS_IMPERSONATE_ATTEMPTS`, and `MAX_LOGIN_ATTEMPTS` are read through `config.py` (apart from Worker env vars). `NS_IMPERSONATE_ATTEMPTS` is capped at 5 and unsupported fingerprints are filtered against the installed curl_cffi; transport errors never retry a non-idempotent check-in POST.
- `STATS_MAX_PAGES` defaults to 20 (max 20) and caps the credit-page pagination; the stats query also has an overall deadline. Lowering it truncates the window, and the result is then labelled "数据不完整".
- Only a missing cookie or a clearly invalid cookie (`404` / 未登录 / 请先登录) triggers a paid captcha login. Network errors, 403 and 5xx do not. When the account count exceeds the cookie count, the extra accounts have no trustworthy slot identity: they are counted as failures and never enter the login path.
- Qinglong writeback resolves `QLAPI` from globals at call time; it works only when Qinglong's task preloader injects it, and skips cleanly otherwise.
- GitHub cookie writeback is encrypted and **off by default**. Set `GH_COOKIE_WRITEBACK=true`; it requires `GH_PAT` (Secrets write), `GITHUB_REPOSITORY`, and PyNaCl.
- Worker `/checkin` requires `TRIGGER_TOKEN`; without it HTTP trigger returns 503. KV is optional but recommended for cookie persistence and locking.

## CI and container notes

- `.github/workflows/blank.yml` maps a fixed subset of secrets; add any new variable there explicitly. It installs `requirements.txt` and pins actions to full commit SHAs.
- `blank.yml` cron is `10 16 * * *` (00:10 Asia/Shanghai). The offset avoids the 00:00 daily check-in counter reset.
- Tests run on Python 3.11 and 3.14 via `.github/workflows/tests.yml`; keep code compatible with 3.11.
- The Cloudflare Worker has its own suite: `node --test "tests/*.test.mjs"` (`tests/worker.test.mjs`), using a stubbed global `fetch` and an in-memory KV binding. Run it after touching `nodeseek-cloudflare-worker.js`.
- The Dockerfile uses `python:3.14.10-alpine3.24`, installs `requirements.txt`, copies `*.py`, runs as UID/GID 1000, and exposes a heartbeat-based healthcheck. A new non-Python runtime asset will not be present unless the Dockerfile changes.
- The host `./cookie` bind mount must be writable by UID 1000.
- `.github/dependabot.yml` covers pip, GitHub Actions, and Docker; action versions are updated as SHA-pinned commits.
