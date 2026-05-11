import os
import re
import hmac
import urllib.parse
import hashlib
import functools
import html as _html
import ipaddress
import unicodedata
import uuid
import secrets
import json as _json
import time as _time
import random as _random
from flask import Flask, render_template, request, jsonify, session, Response
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict
from engine import (Engine, PLAYER_FETISH_BASE_ID, _get_conn, _put_conn, _use_db,
                    FOCUS_THRESHOLD, get_compound_works,
                    list_compound_works, set_compound_works, delete_compound_works,
                    parse_works_list)
from audit import recent_audit, write_audit
from storage import atomic_write_json, data_path, load_json_file
from work_utils import safe_work_url, work_title

# ── サーバーサイドセッション ──────────────────────────────
_SESSION_TTL    = 86400  # 24時間
_LOCAL_SESSIONS = {}     # ローカル用インメモリストア {sid: (data, updated_at)}

def _session_load(sid):
    if _use_db():
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT data, updated_at FROM sessions WHERE session_id = %s', (sid,))
            row = cur.fetchone()
            if row and _time.time() - row[1] < _SESSION_TTL:
                return _json.loads(row[0])
        finally:
            _put_conn(conn)
    else:
        entry = _LOCAL_SESSIONS.get(sid)
        if entry and _time.time() - entry[1] < _SESSION_TTL:
            return dict(entry[0])
    return None

def _session_save(sid, data):
    now = _time.time()
    if _use_db():
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute('''
                    INSERT INTO sessions (session_id, data, updated_at) VALUES (%s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE
                    SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at
                ''', (sid, _json.dumps(data, ensure_ascii=False), now))
                # 1%の確率で期限切れセッションを掃除
                if _random.random() < 0.01:
                    cur.execute('DELETE FROM sessions WHERE updated_at < %s',
                                (now - _SESSION_TTL,))
        finally:
            _put_conn(conn)
    else:
        _LOCAL_SESSIONS[sid] = (data, now)
        if len(_LOCAL_SESSIONS) > 2000:
            cutoff = now - _SESSION_TTL
            for k in [k for k, v in _LOCAL_SESSIONS.items() if v[1] < cutoff]:
                del _LOCAL_SESSIONS[k]

def cleanup_sessions():
    """期限切れセッションを全削除（管理APIから呼び出し可）。"""
    cutoff = _time.time() - _SESSION_TTL
    if _use_db():
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute('DELETE FROM sessions WHERE updated_at < %s', (cutoff,))
                return cur.rowcount
        finally:
            _put_conn(conn)
    else:
        old = [k for k, v in _LOCAL_SESSIONS.items() if v[1] < cutoff]
        for k in old:
            del _LOCAL_SESSIONS[k]
        return len(old)


def _local_session_count():
    if _use_db():
        return None
    return len(_LOCAL_SESSIONS)

class _ServerSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None, is_new=False):
        def on_update(self):
            self.modified = True
        super().__init__(initial or {}, on_update)
        self.sid      = sid
        self.is_new   = is_new
        self.modified = False

class _ServerSessionInterface(SessionInterface):
    _cookie = 'heki_sid'

    def open_session(self, app, request):
        sid = request.cookies.get(self._cookie)
        if sid:
            data = _session_load(sid)
            if data is not None:
                return _ServerSession(data, sid=sid)
        return _ServerSession(sid=str(uuid.uuid4()), is_new=True)

    def save_session(self, app, session, response):
        if not session.modified and not session.is_new:
            return
        _session_save(session.sid, dict(session))
        secure = bool(os.environ.get('DATABASE_URL'))
        response.set_cookie(
            self._cookie, session.sid,
            httponly=True, secure=secure, samesite='Lax',
            max_age=_SESSION_TTL,
        )

# ─────────────────────────────────────────────────────────
app = Flask(__name__)
_secret = os.environ.get('SECRET_KEY')
if not _secret:
    if os.environ.get('DATABASE_URL'):
        raise RuntimeError('本番環境では SECRET_KEY 環境変数の設定が必須です')
    import sys, warnings
    print('WARNING: SECRET_KEY が未設定です。本番環境では環境変数に設定してください。', file=sys.stderr)
    warnings.warn('SECRET_KEY が未設定です。本番環境では環境変数に設定してください。', stacklevel=1)
    _secret = 'hekineitor_dev_secret_2024'
elif len(_secret) < 16:
    import sys
    print('WARNING: SECRET_KEY が短すぎます（16文字以上推奨）。', file=sys.stderr)
app.secret_key = _secret
app.session_interface = _ServerSessionInterface()


@app.after_request
def _record_status_counts(response):
    if 400 <= response.status_code < 500:
        _ERROR_COUNTS['4xx'] += 1
    elif response.status_code >= 500:
        _ERROR_COUNTS['5xx'] += 1
    is_admin_mutation = (
        request.path.startswith('/api/admin/')
        or (request.path.startswith('/api/fetish/') and request.method == 'DELETE')
    )
    if (
        is_admin_mutation
        and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}
        and 'import_matrix' not in request.path
    ):
        try:
            write_audit('admin_api', 'ok' if response.status_code < 400 else 'error', {
                'status_code': response.status_code,
            }, request)
        except Exception:
            pass
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    response.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; img-src 'self' data: https:; "
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    return response


def _client_ip():
    remote_addr = request.remote_addr or 'unknown'
    trusted = app.config.get('TRUSTED_PROXY_IPS')
    if trusted is None:
        trusted = os.environ.get('TRUSTED_PROXY_IPS', '')
    if isinstance(trusted, str):
        trusted = [item.strip() for item in trusted.split(',') if item.strip()]
    if trusted:
        try:
            remote_ip = ipaddress.ip_address(remote_addr)
            proxy_trusted = any(
                remote_ip in ipaddress.ip_network(entry, strict=False)
                for entry in trusted
            )
        except ValueError:
            proxy_trusted = remote_addr in trusted
        if proxy_trusted:
            forwarded = request.headers.get('X-Forwarded-For', '')
            return (forwarded.split(',')[0].strip() or remote_addr)
    return remote_addr


def _rate_limit(scope, limit, window_seconds=60):
    if not _should_enforce_runtime_guard('rate_limit'):
        return None
    overrides = app.config.get('RATE_LIMIT_OVERRIDES') or {}
    if scope in overrides:
        limit, window_seconds = overrides[scope]
    else:
        env_prefix = 'RATE_LIMIT_' + scope.upper()
        try:
            limit = int(os.environ.get(env_prefix + '_LIMIT', limit))
            window_seconds = int(os.environ.get(env_prefix + '_WINDOW', window_seconds))
        except ValueError:
            pass
    now = _time.time()
    key = (scope, _client_ip())
    bucket = [ts for ts in _RATE_LIMIT_BUCKETS.get(key, []) if now - ts < window_seconds]
    if len(bucket) >= limit:
        _RATE_LIMIT_BUCKETS[key] = bucket
        retry_after = max(1, int(window_seconds - (now - bucket[0])))
        return jsonify({
            'status': 'error',
            'message': f'リクエストが多すぎます。{retry_after}秒後に再試行してください。',
            'retry_after': retry_after,
        }), 429, {'Retry-After': str(retry_after)}
    bucket.append(now)
    _RATE_LIMIT_BUCKETS[key] = bucket
    return None


def _confirmation_text():
    data = request.get_json(silent=True) or {}
    return (data.get('confirm_text') or request.headers.get('X-Confirm-Text') or '').strip()


def _require_confirm(expected):
    if _confirmation_text() != expected:
        return jsonify({
            'status': 'error',
            'message': f'確認のため「{expected}」と入力してください',
            'required_confirm_text': expected,
        }), 400
    return None


def _csrf_token():
    token = session.get('admin_csrf_token')
    issued_at = session.get('admin_csrf_issued_at', 0)
    ttl = int(os.environ.get('ADMIN_CSRF_TTL_SECONDS', '7200'))
    if not token or _time.time() - issued_at > ttl:
        token = secrets.token_urlsafe(32)
        session['admin_csrf_token'] = token
        session['admin_csrf_issued_at'] = _time.time()
    return token


def _check_admin_csrf():
    if not _should_enforce_runtime_guard('csrf'):
        return True
    expected = session.get('admin_csrf_token')
    issued_at = session.get('admin_csrf_issued_at', 0)
    ttl = int(os.environ.get('ADMIN_CSRF_TTL_SECONDS', '7200'))
    if not issued_at or _time.time() - issued_at > ttl:
        return False
    supplied = request.headers.get('X-CSRF-Token', '')
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))

def _app_version():
    h = hashlib.md5()
    for path in ['app.py', 'engine.py', 'templates/index.html']:
        try:
            with open(os.path.join(os.path.dirname(__file__), path), 'rb') as f:
                h.update(f.read())
        except OSError:
            pass
    return h.hexdigest()[:8]

APP_VERSION       = _app_version()
DISPLAY_VERSION   = 'v1.9.2'
AMAZON_ASSOCIATE_ID = os.environ.get('AMAZON_ASSOCIATE_ID', '')
engine = Engine()
APP_STARTED_AT = int(_time.time())
_ERROR_COUNTS = {'4xx': 0, '5xx': 0}
_RATE_LIMIT_BUCKETS = {}


def _should_enforce_runtime_guard(name):
    if name == 'csrf':
        return (not app.config.get('TESTING')) or app.config.get('ENFORCE_CSRF')
    if name == 'rate_limit':
        return (not app.config.get('TESTING')) or app.config.get('ENFORCE_RATE_LIMIT')
    return not app.config.get('TESTING')

GUESS_THRESHOLD = 0.75
SOFT_MAX_QUESTIONS = 20
HARD_MAX_QUESTIONS = 30
MAX_QUESTIONS   = SOFT_MAX_QUESTIONS


def _normalize_name(s):
    s = unicodedata.normalize('NFKC', s)
    s = s.lower()
    s = re.sub(r'[\s\u3000・･（）()「」『』【】〔〕\-_～~、。×]', '', s)
    return s

def _levenshtein(a, b):
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j] + (ca != cb), curr[-1] + 1, prev[j + 1] + 1))
        prev = curr
    return prev[-1]

def _find_similar(name, fetishes):
    norm_new = _normalize_name(name)
    results = []
    for f in fetishes:
        norm_f = _normalize_name(f['name'])
        if norm_new == norm_f:
            continue
        if norm_new in norm_f or norm_f in norm_new:
            results.append(f)
            continue
        if len(norm_new) <= 12 and len(norm_f) <= 12 and _levenshtein(norm_new, norm_f) <= 2:
            results.append(f)
    return results[:5]


def _question_total_for_count(count):
    return HARD_MAX_QUESTIONS if count >= SOFT_MAX_QUESTIONS else SOFT_MAX_QUESTIONS


def _should_extend_low_confidence(count, top_p, second_p, guess_thr):
    if count < SOFT_MAX_QUESTIONS or count >= HARD_MAX_QUESTIONS:
        return False
    gap_points = top_p - second_p
    return top_p < guess_thr or gap_points < 0.20


def _record_quality_stat(key, count=1):
    for _ in range(max(0, int(count or 0))):
        engine._record_daily_stat(key)


def _record_guess_quality_feedback(correct):
    quality = session.pop('last_guess_quality', None) or {}
    if not quality:
        return
    suffix = 'correct' if correct else 'wrong'
    if quality.get('low_confidence_extended'):
        _record_quality_stat(f'q_low_conf_{suffix}')
    if quality.get('additional_questions', 0) > 0:
        _record_quality_stat(f'q_additional_{suffix}')


def _select_next_question(answers, asked, idk_streak=0, disambiguate=False):
    if disambiguate:
        return engine.best_disambiguating_question(answers, set(asked), idk_streak=idk_streak)
    return engine.best_question(answers, set(asked), idk_streak=idk_streak)


def _snapshot_current_matrix(reason):
    rows = []
    fetishes = [{'id': f['id'], 'name': f['name']} for f in engine.fetishes]
    for fi, f in enumerate(engine.fetishes):
        for qi, q in enumerate(engine.questions):
            rows.append({
                'fetish_id': f['id'],
                'fetish_name': f['name'],
                'question_id': qi,
                'question_text': q['text'],
                'yes': round(engine.matrix['yes'][fi][qi], 4),
                'total': round(engine.matrix['total'][fi][qi], 4),
            })
    snapshot = {
        'created_at': int(_time.time()),
        'reason': reason,
        'fetishes': fetishes,
        'matrix_rows': rows,
    }
    backup_dir = data_path('matrix_import_backups')
    os.makedirs(backup_dir, exist_ok=True)
    path = os.path.join(backup_dir, f'matrix_before_{_time.time_ns()}.json')
    atomic_write_json(path, snapshot, ensure_ascii=False, indent=2)
    _prune_matrix_import_backups()
    return path


def _matrix_import_expected_rows():
    return len(engine.fetishes) * len(engine.questions)


def _matrix_import_completeness_error(report):
    expected_rows = _matrix_import_expected_rows()
    if report.get('skipped_rows') != 0 or report.get('valid_rows') != expected_rows:
        return jsonify({
            'status': 'error',
            'message': 'matrix_rows は現在の全 fetish/question 組み合わせを含む必要があります',
            **report,
            'expected_rows': expected_rows,
        }), 400
    return None


def _list_matrix_import_backups(limit=50):
    backup_dir = data_path('matrix_import_backups')
    if not os.path.isdir(backup_dir):
        return []
    rows = []
    for name in sorted(os.listdir(backup_dir), reverse=True):
        if not name.endswith('.json'):
            continue
        path = os.path.join(backup_dir, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        rows.append({'name': name, 'mtime': int(stat.st_mtime), 'size': stat.st_size})
    return rows if limit is None else rows[:limit]


def _prune_matrix_import_backups():
    try:
        keep = int(os.environ.get('MATRIX_IMPORT_BACKUP_KEEP', '20'))
    except ValueError:
        keep = 20
    keep = max(1, min(keep, 200))
    backups = _list_matrix_import_backups(limit=None)
    for row in backups[keep:]:
        try:
            os.remove(os.path.join(data_path('matrix_import_backups'), row['name']))
        except OSError:
            pass


def _bounded_int(value, default, min_value=1, max_value=100):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(min_value, min(max_value, n))


def _build_fetish_log_rows():
    fetish_log = engine.get_fetish_log()
    rows = []
    for f in engine.fetishes:
        lg = fetish_log.get(f['id'], {'guessed': 0, 'correct': 0, 'wrong': 0})
        guessed = lg['guessed']
        correct = lg['correct']
        wrong = lg['wrong']
        acc = round(correct / guessed * 100) if guessed else None
        rows.append({
            'id': f['id'], 'name': f['name'],
            'guessed': guessed, 'correct': correct, 'wrong': wrong, 'acc': acc,
        })
    rows.sort(key=lambda r: -r['guessed'])
    return rows


def _paged_fetish_log_rows(rows, args):
    q = (args.get('q') or '').strip().lower()
    min_guessed = _bounded_int(args.get('min_guessed'), 0, 0, 1000000)
    acc_filter = args.get('acc_filter') or 'all'
    sort_key = args.get('sort') or 'guessed'
    order = args.get('order') or 'desc'
    page = _bounded_int(args.get('page'), 1, 1, 1000000)
    per_page = _bounded_int(args.get('per_page'), 50, 10, 200)

    def include(row):
        acc = row['acc']
        return (
            q in row['name'].lower()
            and row['guessed'] >= min_guessed
            and (
                acc_filter == 'all'
                or (acc_filter == 'low' and acc is not None and acc < 50)
                or (acc_filter == 'high' and acc is not None and acc >= 70)
                or (acc_filter == 'none' and acc is None)
            )
        )

    filtered = [row for row in rows if include(row)]
    key_map = {
        'name': lambda r: r['name'],
        'guessed': lambda r: r['guessed'],
        'correct': lambda r: r['correct'],
        'wrong': lambda r: r['wrong'],
        'acc': lambda r: -1 if r['acc'] is None else r['acc'],
    }
    filtered.sort(key=key_map.get(sort_key, key_map['guessed']), reverse=(order != 'asc'))
    total = len(filtered)
    start = (page - 1) * per_page
    return {
        'rows': filtered[start:start + per_page],
        'page': page,
        'per_page': per_page,
        'total': total,
        'pages': max(1, (total + per_page - 1) // per_page),
    }


@app.route('/')
def index():
    return render_template('index.html',
                           display_version=DISPLAY_VERSION,
                           amazon_associate_id=AMAZON_ASSOCIATE_ID)


@app.route('/r')
def result_share():
    name = request.args.get('f', '')[:60]
    prob = request.args.get('p', '')[:5]
    desc = request.args.get('d', '')[:120]
    base_url = request.host_url.rstrip('/')
    og_image = f"{base_url}/ogp?f={urllib.parse.quote(name)}&p={prob}"
    return render_template('result_share.html',
                           fetish_name=name, probability=prob, desc=desc,
                           display_version=DISPLAY_VERSION,
                           og_image=og_image)


@app.route('/ogp')
def ogp_image():
    """診断結果のOGP画像をSVGで動的生成する（1200×630 Twitter推奨サイズ）。"""
    name = request.args.get('f', '???')[:30]
    prob = request.args.get('p', '')[:5]
    try:
        bar_w = max(8, min(int(float(prob) * 5.6), 560)) if prob else 0
        prob_val = float(prob) if prob else 0
    except ValueError:
        bar_w = 0
        prob_val = 0
    # 名前の折り返し（12文字で改行）
    if len(name) > 12:
        line1, line2 = name[:12], name[12:24]
        if len(name) > 24:
            line2 = name[12:23] + '…'
    else:
        line1, line2 = name, ''
    line1 = _html.escape(line1, quote=False)
    line2 = _html.escape(line2, quote=False)
    prob_text = _html.escape(prob, quote=False)
    fs_name = 72 if len(line1) <= 8 else 60
    y1 = 260 if line2 else 290
    y2 = y1 + fs_name + 12
    bar_color = '#f5a623' if prob_val >= 75 else ('#e94560' if prob_val >= 50 else '#5b8dd9')
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0.6" y2="1">
      <stop offset="0%" stop-color="#0d1b2a"/>
      <stop offset="100%" stop-color="#16213e"/>
    </linearGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#e94560"/>
      <stop offset="100%" stop-color="#f5a623"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#e94560" stop-opacity="0.15"/>
      <stop offset="100%" stop-color="#f5a623" stop-opacity="0.05"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="0" y="0" width="1200" height="8" fill="url(#bar)"/>
  <rect x="60" y="60" width="580" height="510" rx="20" fill="url(#accent)"/>
  <rect x="60" y="60" width="580" height="510" rx="20" fill="none" stroke="#e94560" stroke-width="1" stroke-opacity="0.3"/>
  <text x="350" y="130" text-anchor="middle" font-family="sans-serif" font-size="28" fill="#888">🔮 へきネイター診断結果</text>
  <text x="350" y="{y1}" text-anchor="middle" font-family="sans-serif" font-size="{fs_name}" font-weight="bold" fill="#e94560">{line1}</text>
  {'<text x="350" y="' + str(y2) + '" text-anchor="middle" font-family="sans-serif" font-size="' + str(fs_name) + '" font-weight="bold" fill="#e94560">' + line2 + '</text>' if line2 else ''}
  {'<text x="350" y="' + str((y2 if line2 else y1)+70) + '" text-anchor="middle" font-family="sans-serif" font-size="36" fill="' + bar_color + '">一致度 ' + prob_text + '%</text>' if prob else ''}
  <rect x="130" y="490" width="440" height="12" rx="6" fill="#1a1a3e"/>
  <rect x="130" y="490" width="{bar_w}" height="12" rx="6" fill="url(#bar)"/>
  <rect x="680" y="60" width="460" height="510" rx="20" fill="#0a0f1e" fill-opacity="0.6"/>
  <text x="910" y="160" text-anchor="middle" font-family="sans-serif" font-size="24" fill="#555">あなたの性癖は？</text>
  <text x="910" y="320" text-anchor="middle" font-family="sans-serif" font-size="80" fill="#e94560" opacity="0.15">?</text>
  <text x="910" y="440" text-anchor="middle" font-family="sans-serif" font-size="20" fill="#444">hekineitor.onrender.com</text>
  <text x="910" y="480" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#333">質問に答えるだけで診断</text>
</svg>'''
    return Response(svg, mimetype='image/svg+xml',
                    headers={'Cache-Control': 'public, max-age=3600'})


@app.route('/manifest.json')
def manifest():
    path = os.path.join(app.static_folder, 'manifest.json')
    with open(path, encoding='utf-8') as f:
        body = f.read()
    return Response(body, mimetype='application/manifest+json',
                    headers={'Cache-Control': 'no-cache'})


@app.route('/sw.js')
def sw():
    return render_template('sw.js', version=APP_VERSION), 200, {
        'Content-Type': 'application/javascript',
        'Cache-Control': 'no-cache',
    }


@app.route('/offline')
def offline():
    return render_template('offline.html')


@app.route('/fetish/<int:fetish_id>')
def fetish_detail(fetish_id):
    idx = engine.index_of(fetish_id)
    if idx is None:
        return _ERROR_PAGE.format(
            title='見つかりません', emoji='🔍', code='404',
            message='その性癖は存在しないか、削除されました。'
        ), 404
    f = engine.fetishes[idx]
    # 関連性癖
    from engine import FETISH_RELATIONS, work_title
    related = []
    for rid in FETISH_RELATIONS.get(fetish_id, []):
        ri = engine.index_of(rid)
        if ri is not None:
            related.append({'id': rid, 'name': engine.fetishes[ri]['name']})
    # 作品リスト（アフィリエイトリンク付き）
    works = []
    for w in f.get('works', []):
        title = work_title(w)
        url = w.get('url', '') if isinstance(w, dict) else ''
        url = safe_work_url(url)
        if url and AMAZON_ASSOCIATE_ID and 'tag=' not in url:
            sep = '&' if '?' in url else '?'
            url = url + f'{sep}tag={urllib.parse.quote(AMAZON_ASSOCIATE_ID)}'
        works.append({'title': title, 'url': url})
    # 特徴的な質問 TOP5（P(yes)が高い質問）
    nq = len(engine.questions)
    char_qs = []
    if idx < len(engine.matrix['yes']):
        row_yes = engine.matrix['yes'][idx]
        row_tot = engine.matrix['total'][idx]
        scores = []
        for qi in range(nq):
            p = row_yes[qi] / row_tot[qi] if row_tot[qi] > 0 else 0.5
            if abs(p - 0.5) > 0.08:
                scores.append((p, qi))
        scores.sort(reverse=True)
        for p, qi in scores[:5]:
            char_qs.append({'text': engine.questions[qi]['text'], 'p': round(p * 100)})
    # 診断実績
    fetish_log = engine.get_fetish_log()
    lg = fetish_log.get(fetish_id, {'guessed': 0, 'correct': 0, 'wrong': 0})
    acc = round(lg['correct'] / lg['guessed'] * 100) if lg['guessed'] else None
    base_url = request.host_url.rstrip('/')
    og_image = f"{base_url}/ogp?f={urllib.parse.quote(f['name'])}&p=90"
    return render_template('fetish.html',
        fetish=f,
        works=works,
        related=related,
        char_qs=char_qs,
        log=lg,
        acc=acc,
        display_version=DISPLAY_VERSION,
        og_image=og_image,
        base_url=base_url,
    )


@app.route('/stats')
def stats_page():
    fetish_log = engine.get_fetish_log()
    s = engine.get_stats()
    rows = []
    for f in engine.fetishes:
        if f['id'] >= PLAYER_FETISH_BASE_ID:
            continue
        lg = fetish_log.get(f['id'], {'guessed': 0, 'correct': 0, 'wrong': 0})
        g, c, w = lg['guessed'], lg['correct'], lg['wrong']
        acc = round(c / g * 100) if g else None
        rows.append({'id': f['id'], 'name': f['name'], 'guessed': g, 'correct': c, 'wrong': w, 'acc': acc})
    rows.sort(key=lambda r: -r['guessed'])
    top10 = [r for r in rows if r['guessed'] > 0][:10]
    total_guessed = sum(r['guessed'] for r in rows)
    total_correct = sum(r['correct'] for r in rows)
    overall_acc = round(total_correct / total_guessed * 100) if total_guessed else None
    ranked = [r for r in rows if r['guessed'] >= 3 and r['acc'] is not None]
    top_acc = sorted(ranked, key=lambda r: -r['acc'])[:5]
    base_url = request.host_url.rstrip('/')
    return render_template('stats.html',
        top10=top10,
        play_count=s['play_count'],
        learn_count=s['learn_count'],
        total_guessed=total_guessed,
        overall_acc=overall_acc,
        top_acc=top_acc,
        total_fetishes=len([f for f in engine.fetishes if f['id'] < PLAYER_FETISH_BASE_ID]),
        display_version=DISPLAY_VERSION,
        base_url=base_url,
    )


@app.route('/robots.txt')
def robots_txt():
    host = request.host_url.rstrip('/')
    txt = f"""User-agent: *
Disallow: /admin
Disallow: /api/
Allow: /
Sitemap: {host}/sitemap.xml
"""
    return Response(txt, mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap_xml():
    host = request.host_url.rstrip('/')
    urls = [host + '/', host + '/r']
    for f in engine.fetishes:
        if f['id'] < 10000:
            urls.append(f"{host}/fetish/{f['id']}")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        lines.append(f'  <url><loc>{u}</loc></url>')
    lines.append('</urlset>')
    return Response('\n'.join(lines), mimetype='application/xml')


@app.route('/api/start', methods=['POST'])
def start():
    limited = _rate_limit('api_start', 120)
    if limited:
        return limited
    data = request.get_json(silent=True) or {}
    exclude_ids = []
    for eid in data.get('exclude_ids', []):
        try:
            exclude_ids.append(int(eid))
        except (ValueError, TypeError):
            pass
    session.clear()
    session['answers']     = {}
    session['asked']       = []
    session['started']     = True
    session['exclude_ids'] = exclude_ids
    q = engine.best_question({}, set())
    session['asked'].append(q)
    q_data = engine.questions[q]
    q_variants = q_data.get('variants', [])
    q_text = _random.choice([q_data['text']] + q_variants) if q_variants else q_data['text']
    return jsonify({
        'question_id': q,
        'question':    q_text,
        'count':       0,
        'total':       SOFT_MAX_QUESTIONS,
        'axis':        engine._question_axis(q),
        'q_hint':      q_data.get('hint', ''),
    })


@app.route('/api/resume', methods=['POST'])
def resume():
    """localStorageに保存した回答ペアからセッションを復元して次の質問を返す。"""
    data  = request.get_json(silent=True) or {}
    pairs = data.get('pairs', [])
    exclude_ids = []
    for eid in data.get('exclude_ids', []):
        try:
            exclude_ids.append(int(eid))
        except (ValueError, TypeError):
            pass
    session.clear()
    session['started']     = True
    session['answers']     = {}
    session['asked']       = []
    session['idk_streak']  = 0
    session['exclude_ids'] = exclude_ids
    for item in pairs:
        try:
            q_idx = int(item['q_id'])
            ans   = float(item['answer'])
        except (KeyError, ValueError, TypeError):
            continue
        if ans not in (1, 0.5, 0, -0.5, -1):
            continue
        if q_idx < 0 or q_idx >= len(engine.questions):
            continue
        session['answers'][str(q_idx)] = ans
        if q_idx not in session['asked']:
            session['asked'].append(q_idx)
        session['idk_streak'] = session['idk_streak'] + 1 if ans == 0 else 0
    answers = session['answers']
    asked   = session['asked']
    if not answers:
        q = engine.best_question({}, set())
        session['asked'].append(q)
        q_data = engine.questions[q]
        q_variants = q_data.get('variants', [])
        q_text = _random.choice([q_data['text']] + q_variants) if q_variants else q_data['text']
        return jsonify({'action': 'question', 'question_id': q,
                        'question': q_text,
                        'count': 0, 'total': SOFT_MAX_QUESTIONS,
                        'axis': engine._question_axis(q),
                        'q_hint': q_data.get('hint', '')})
    next_q = engine.best_question(answers, set(asked), idk_streak=session['idk_streak'])
    if next_q is None:
        return _make_guess(answers)
    asked.append(next_q)
    session['asked'] = asked
    nq_data = engine.questions[next_q]
    nq_variants = nq_data.get('variants', [])
    nq_text = _random.choice([nq_data['text']] + nq_variants) if nq_variants else nq_data['text']
    return jsonify({'action': 'question', 'question_id': next_q,
                    'question': nq_text,
                    'count': len(asked) - 1, 'total': _question_total_for_count(len(asked) - 1),
                    'axis': engine._question_axis(next_q),
                    'q_hint': nq_data.get('hint', '')})


@app.route('/api/continue', methods=['POST'])
def continue_game():
    """診断確定後に「もう少し続ける」ボタンで追加質問を開始する。"""
    if not session.get('started'):
        return jsonify({'status': 'session_expired'}), 440
    answers = session.get('answers', {})
    asked   = session.get('asked', [])
    top2    = engine.top_guess(answers, n=2)
    top_p   = top2[0][1] if top2 else 0.0
    session['continue_thr'] = min(top_p + 0.20, 0.95)
    session['continued']    = True
    next_q = engine.best_question(answers, set(asked), idk_streak=0)
    if next_q is None:
        return jsonify({'status': 'no_question'})
    asked.append(next_q)
    session['asked'] = asked
    cq_data = engine.questions[next_q]
    cq_variants = cq_data.get('variants', [])
    cq_text = _random.choice([cq_data['text']] + cq_variants) if cq_variants else cq_data['text']
    return jsonify({'action': 'question', 'question_id': next_q,
                    'question': cq_text,
                    'count': len(asked) - 1, 'total': HARD_MAX_QUESTIONS,
                    'axis': engine._question_axis(next_q),
                    'q_hint': cq_data.get('hint', '')})


@app.route('/api/answer', methods=['POST'])
def answer():
    limited = _rate_limit('api_answer', 240)
    if limited:
        return limited
    if not session.get('started'):
        return jsonify({'status': 'session_expired'}), 440
    data = request.get_json(silent=True) or {}
    if 'question_id' not in data or 'answer' not in data:
        return jsonify({'status': 'error', 'message': 'question_id と answer が必要です'}), 400
    try:
        q_idx = int(data['question_id'])
        ans   = float(data['answer'])
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': '不正な値です'}), 400
    if ans not in (1, 0.5, 0, -0.5, -1):
        return jsonify({'status': 'error', 'message': '不正な回答値です'}), 400
    if q_idx < 0 or q_idx >= len(engine.questions):
        return jsonify({'status': 'error', 'message': '不正な質問IDです'}), 400

    answers = session.get('answers', {})
    asked   = session.get('asked', [])

    answers[str(q_idx)] = ans
    session['answers']  = answers

    # back() 後の再回答でも q_idx を asked に含める（重複質問防止）
    if q_idx not in asked:
        asked.append(q_idx)

    # 「わからない」連続カウント
    idk_streak = session.get('idk_streak', 0)
    idk_streak = idk_streak + 1 if ans == 0 else 0
    session['idk_streak'] = idk_streak

    try:
        top2 = engine.top_guess(answers, n=2)
        top_p    = top2[0][1]
        second_p = top2[1][1] if len(top2) > 1 else 0.0
        count = len(asked)

        # 終了条件: idk連続4回 / hard上限 / 通常閾値 / 早期打ち切り（比率ベース）
        guess_thr = engine.config.get('guess_threshold', GUESS_THRESHOLD)
        if session.get('continued'):
            guess_thr = session.get('continue_thr', min(guess_thr + 0.20, 0.95))
        gap_ratio  = top_p / max(second_p, 0.001)
        early_stop = (count >= 4 and top_p >= 0.70 and gap_ratio >= 3.0) or \
                     (count >= 8 and top_p >= 0.55 and gap_ratio >= 2.5)
        # 接戦（1位と2位が近い）かつ問数が少ない場合は閾値を引き上げて続行
        effective_thr = guess_thr if (gap_ratio >= 1.8 or count >= 10) \
                        else min(guess_thr + 0.10, 0.90)
        extend_low_confidence = _should_extend_low_confidence(count, top_p, second_p, guess_thr)
        should_guess = (
            idk_streak >= 4
            or top_p >= effective_thr
            or count >= HARD_MAX_QUESTIONS
            or early_stop
            or (count >= SOFT_MAX_QUESTIONS and not extend_low_confidence)
        )
        if should_guess:
            return _make_guess(answers)

        next_q = _select_next_question(
            answers,
            asked,
            idk_streak=idk_streak,
            disambiguate=extend_low_confidence or count >= SOFT_MAX_QUESTIONS,
        )
        if next_q is None:
            return _make_guess(answers)

        asked.append(next_q)
        session['asked'] = asked

        focus_thr = engine.config.get('focus_threshold', FOCUS_THRESHOLD)
        hint = '答えが見えてきました…もう少しです' if top_p >= focus_thr else None
        if extend_low_confidence:
            hint = '候補が接戦です。もう少し絞り込みます'
            session['low_confidence_extended'] = True

        aq_data = engine.questions[next_q]
        aq_variants = aq_data.get('variants', [])
        aq_text = _random.choice([aq_data['text']] + aq_variants) if aq_variants else aq_data['text']

        resp = {
            'action':      'question',
            'question_id': next_q,
            'question':    aq_text,
            'count':       count,
            'total':       _question_total_for_count(count),
            'axis':        engine._question_axis(next_q),
            'q_hint':      aq_data.get('hint', ''),
        }
        if hint:
            resp['hint'] = hint
        contradictions = engine.detect_contradictions(answers)
        if contradictions:
            resp['contradictions'] = contradictions
        return jsonify(resp)
    except Exception:
        app.logger.exception('answer() 推論エラー')
        return jsonify({'status': 'session_expired', 'restart': True}), 440


@app.route('/api/back', methods=['POST'])
def back():
    if not session.get('started'):
        return jsonify({'status': 'session_expired'}), 440
    asked   = session.get('asked', [])
    answers = session.get('answers', {})

    if len(asked) < 2:
        return jsonify({'status': 'no_history'})

    # asked[-1] = 現在表示中（未回答）、asked[-2] = 直前に回答済み
    asked.pop()                          # 現在の質問を除去
    prev_q = asked[-1]
    answers.pop(str(prev_q), None)       # 直前の回答を取り消し
    asked.pop()                          # 直前の質問も除去（再回答時に再追加）

    session['asked']      = asked
    session['answers']    = answers
    session['idk_streak'] = 0

    return jsonify({
        'question_id': prev_q,
        'question':    engine.questions[prev_q]['text'],
        'count':       len(asked),
        'total':       _question_total_for_count(len(asked)),
    })


import math as _math

PROFILE_MIN_RATIO = 0.25   # best_p に対する比率の下限
PROFILE_MIN_PROB  = 0.08   # 絶対確率の下限
COMPOUND_RATIO    = 0.55   # 2位がこの比率以上なら複合
TRIPLE_RATIO      = 0.45   # 3位がこの比率以上なら三重複合

def _learn_factor(answers, total_n=1):
    """確信度スケーリング × √n 分散: 不確実なほど強く、多く選ぶほど弱く。"""
    probs  = engine.posteriors(answers)
    thr    = engine.config.get('guess_threshold', GUESS_THRESHOLD)
    top_p  = max(probs) if probs else thr
    if top_p >= thr:
        # 診断閾値以上: top_p=thr→1.0、top_p=1.0→0.5 に線形マッピング
        conf = max(0.5, 1.0 - 0.5 * (top_p - thr) / max(1.0 - thr, 1e-9))
    else:
        # 閾値未満（max_questions 到達など）: 不確実なほど強く（最大2.0）
        conf = min(2.0, thr / max(top_p, 0.1))
    n_scale = 1.0 / _math.sqrt(max(total_n, 1))
    return max(0.3, min(2.0, conf * n_scale))


def _parse_id_list(value):
    if not isinstance(value, list):
        return set()
    parsed = set()
    for item in value:
        try:
            parsed.add(int(item))
        except (ValueError, TypeError):
            continue
    return parsed


def _compute_guess(answers):
    """診断結果を返す（play_count はインクリメントしない、純粋計算）。
    レスポンスの fetish_id 系は全てDB id（永続的・プレイヤー追加性癖でも安全）。"""
    probs   = engine.posteriors(answers)
    exclude_ids = set(session.get('exclude_ids', []))
    ranked  = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
    # exclude_ids に該当するものを末尾に退ける（除外優先、0件なら通常通り）
    if exclude_ids:
        ranked = [i for i in ranked if engine.fetishes[i]['id'] not in exclude_ids] + \
                 [i for i in ranked if engine.fetishes[i]['id'] in exclude_ids]
    best_i  = ranked[0]
    best_p  = probs[best_i]
    best_f  = engine.fetishes[best_i]
    best_db = best_f['id']

    compound_ratio = engine.config.get('compound_ratio', COMPOUND_RATIO)
    triple_ratio   = engine.config.get('triple_ratio',   TRIPLE_RATIO)
    compound = []
    compound_db_ids = set()
    if len(ranked) > 1 and probs[ranked[1]] >= best_p * compound_ratio:
        c = engine.fetishes[ranked[1]]
        compound.append({'fetish_id': c['id'],
                         'fetish_name': c['name'],
                         'probability': round(probs[ranked[1]] * 100, 1)})
        compound_db_ids.add(c['id'])
        if len(ranked) > 2 and probs[ranked[2]] >= best_p * triple_ratio:
            c = engine.fetishes[ranked[2]]
            compound.append({'fetish_id': c['id'],
                             'fetish_name': c['name'],
                             'probability': round(probs[ranked[2]] * 100, 1)})
            compound_db_ids.add(c['id'])

    threshold = max(best_p * PROFILE_MIN_RATIO, PROFILE_MIN_PROB)
    profile = []
    for fi in ranked[1:]:
        f_dict = engine.fetishes[fi]
        if f_dict['id'] == best_db or f_dict['id'] in compound_db_ids:
            continue
        if probs[fi] >= threshold:
            profile.append({'fetish_id': f_dict['id'],
                            'fetish_name': f_dict['name'],
                            'probability': round(probs[fi] * 100, 1)})

    profile_db_ids = {p['fetish_id'] for p in profile}
    related_seen   = profile_db_ids | compound_db_ids | {best_db}
    related        = []
    for src_db in [best_db] + list(compound_db_ids):
        for r in engine.get_related(src_db):
            if r['fetish_id'] not in related_seen:
                related.append(r)
                related_seen.add(r['fetish_id'])

    # 上位5件の確率バー用
    top_chart = []
    for fi in ranked[:5]:
        f_dict = engine.fetishes[fi]
        top_chart.append({'fetish_name': f_dict['name'], 'probability': round(probs[fi] * 100, 1)})

    reasons = engine.get_answer_contributions(answers, best_i)

    # 作品レコメンド: 複合特化作品を優先し、その後各性癖の個別作品をマージ
    # works は文字列 or dict の混在があるため、タイトル文字列でdedup管理
    from engine import work_title
    seen_titles: set = set()
    cross_works: list = []   # 複合に特化した作品（複数性癖の要素を兼ね備えた作品）
    merged_works: list = []  # 個別作品のマージ

    def _add_work(w, target):
        t = work_title(w)
        if t and t not in seen_titles:
            seen_titles.add(t)
            target.append(w)

    if compound:
        for c in compound:
            for w in get_compound_works(best_db, c['fetish_id']):
                _add_work(w, cross_works)
        # 三重複合の場合、compound同士のペアも確認
        c_ids = [c['fetish_id'] for c in compound]
        for i in range(len(c_ids)):
            for j in range(i + 1, len(c_ids)):
                for w in get_compound_works(c_ids[i], c_ids[j]):
                    _add_work(w, cross_works)

    for w in best_f.get('works', []):
        _add_work(w, merged_works)
    for c in compound:
        ci = engine.index_of(c['fetish_id'])
        if ci is not None:
            for w in engine.fetishes[ci].get('works', []):
                _add_work(w, merged_works)

    return {
        'action':       'guess',
        'fetish_id':    best_db,
        'fetish_name':  best_f['name'],
        'fetish_desc':  best_f['desc'],
        'probability':  round(best_p * 100, 1),
        'compound':     compound,
        'profile':      profile,
        'related':      related,
        'top_chart':    top_chart,
        'reasons':      reasons,
        'works':        merged_works,
        'cross_works':  cross_works,
    }


def _make_guess(answers):
    engine.increment_play_count()
    result = _compute_guess(answers)
    additional_questions = max(0, len(answers or {}) - SOFT_MAX_QUESTIONS)
    low_confidence_extended = bool(session.get('low_confidence_extended'))
    session['last_guess_quality'] = {
        'low_confidence_extended': low_confidence_extended,
        'additional_questions': additional_questions,
    }
    if low_confidence_extended:
        _record_quality_stat('q_low_conf_guess')
    if additional_questions > 0:
        _record_quality_stat('q_additional_guess')
        _record_quality_stat('q_additional_question', additional_questions)
    engine.log_guessed(result['fetish_id'])
    return jsonify(result)


@app.route('/api/confirm', methods=['POST'])
def confirm():
    data = request.get_json(silent=True) or {}
    if 'correct' not in data or 'fetish_id' not in data:
        return jsonify({'status': 'error', 'message': 'correct と fetish_id が必要です'}), 400
    try:
        f_db_id = int(data['fetish_id'])
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': '不正な fetish_id です'}), 400
    f_idx = engine.index_of(f_db_id)
    if f_idx is None:
        return jsonify({'status': 'error', 'message': '存在しない fetish_id です'}), 400
    correct = data['correct']
    answers = session.get('answers', {})

    if correct:
        learn_idxs = [f_idx]
        for cid in data.get('compound_ids', []):
            try:
                c_idx = engine.index_of(int(cid))
                if c_idx is not None and c_idx != f_idx:
                    learn_idxs.append(c_idx)
            except (ValueError, TypeError):
                pass
        factor = _learn_factor(answers, total_n=len(learn_idxs))
        for idx in learn_idxs:
            engine.learn(answers, idx, strength_factor=factor)
            engine.log_correct(engine.fetishes[idx]['id'])
        # 複合正解: 共起パターンを相互強化
        for i in range(len(learn_idxs)):
            for j in range(i + 1, len(learn_idxs)):
                engine.learn_cooccurrence(answers, learn_idxs[i], learn_idxs[j], factor * 0.3)
        _record_guess_quality_feedback(True)
        return jsonify({'status': 'learned'})
    else:
        compound_db_ids = set()
        for cid in data.get('compound_ids', []):
            try:
                compound_db_ids.add(int(cid))
            except (ValueError, TypeError):
                pass
        presented_db_ids = {f_db_id} | compound_db_ids
        maybe_db_ids = _parse_id_list(data.get('maybe_ids')) & presented_db_ids
        explicit_wrong_ids = _parse_id_list(data.get('wrong_ids')) & presented_db_ids
        if 'wrong_ids' in data or 'maybe_ids' in data:
            wrong_db_ids = explicit_wrong_ids
        else:
            wrong_db_ids = set(presented_db_ids)

        factor = _learn_factor(answers, total_n=max(1, len(maybe_db_ids)))
        for mid in maybe_db_ids:
            m_idx = engine.index_of(mid)
            if m_idx is not None:
                engine.learn_near_miss(answers, m_idx, strength_factor=factor)

        if not data.get('add_only', False):
            for wid in wrong_db_ids:
                engine.log_wrong(wid)
            _record_guess_quality_feedback(False)
        probs = engine.posteriors(answers)
        excluded_db_ids = set(presented_db_ids)
        candidates = []
        for i, f in enumerate(engine.fetishes):
            if f['id'] in excluded_db_ids:
                continue
            candidates.append((probs[i], f))
        candidates.sort(key=lambda t: t[0], reverse=True)
        sorted_fetishes = [dict(f, prob=round(p * 100, 1)) for p, f in candidates[:20]]
        # add_only=True は正解追加目的のリスト取得なので wrong_db_ids を設定しない
        if not data.get('add_only', False):
            session['wrong_db_ids'] = sorted(wrong_db_ids)
            session['near_miss_db_ids'] = sorted(maybe_db_ids)
            session['candidate_db_ids'] = [f['id'] for f in sorted_fetishes]
            session['candidate_negative_factor'] = 0.15 if maybe_db_ids else 0.3
        else:
            session['wrong_db_ids'] = []
            session['near_miss_db_ids'] = []
            session['candidate_db_ids'] = []
            session['candidate_negative_factor'] = 0.3
        return jsonify({'status': 'wrong', 'fetishes': sorted_fetishes})


@app.route('/api/teach', methods=['POST'])
def teach():
    data = request.get_json(silent=True) or {}
    if 'fetish_id' not in data:
        return jsonify({'status': 'error', 'message': 'fetish_id が必要です'}), 400
    try:
        f_db_id = int(data['fetish_id'])
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': '不正な fetish_id です'}), 400
    f_idx = engine.index_of(f_db_id)
    if f_idx is None:
        return jsonify({'status': 'error', 'message': '存在しない fetish_id です'}), 400
    answers  = session.get('answers', {})
    try:
        total_n = max(1, int(data.get('total_n', 1)))
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': '不正な total_n です'}), 400
    engine.learn(answers, f_idx, strength_factor=_learn_factor(answers, total_n))
    engine.log_correct(engine.fetishes[f_idx]['id'])
    return jsonify({'status': 'learned', 'fetish_name': engine.fetishes[f_idx]['name']})


@app.route('/api/add_fetish', methods=['POST'])
def add_fetish():
    data        = request.get_json(silent=True) or {}
    name      = data.get('name', '').strip()
    desc      = data.get('desc', '').strip()
    confirmed = data.get('confirmed', False)
    answers   = session.get('answers', {})
    if not name:
        return jsonify({'status': 'error', 'message': '名前を入力してください'}), 400
    if len(name) > 100:
        return jsonify({'status': 'error', 'message': '名前は100文字以内で入力してください'}), 400
    if len(desc) > 500:
        return jsonify({'status': 'error', 'message': '説明は500文字以内で入力してください'}), 400
    existing = next((f for f in engine.fetishes if f['name'] == name), None)
    if existing:
        # 学習は /api/finalize_added にまとめる（完了ボタン押下時）
        return jsonify({'status': 'learned', 'fetish_name': existing['name'],
                        'fetish_id': existing['id'], 'is_new': False})
    if confirmed:
        if not desc:
            desc = name
        _, db_id = engine.add_fetish(name, desc, answers)
        owned = set(session.get('owned_added_fetish_ids', []))
        owned.add(db_id)
        session['owned_added_fetish_ids'] = sorted(owned)
        return jsonify({'status': 'learned', 'fetish_name': name,
                        'fetish_id': db_id, 'is_new': True})
    similar = _find_similar(name, engine.fetishes)
    if similar:
        return jsonify({'status': 'similar', 'candidates': similar})
    return jsonify({'status': 'needs_desc'})


@app.route('/api/finalize_added', methods=['POST'])
def finalize_added():
    data  = request.get_json(silent=True) or {}
    items = data.get('items', [])
    if not isinstance(items, list):
        return jsonify({'status': 'error', 'message': 'items はリストで指定してください'}), 400
    answers  = session.get('answers', {})
    total_n  = max(1, len([i for i in items if isinstance(i, dict)]))
    factor   = _learn_factor(answers, total_n)
    correct_db_ids = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            db_id  = int(item.get('id'))
            is_new = bool(item.get('is_new'))
        except (ValueError, TypeError):
            continue
        idx = engine.index_of(db_id)
        if idx is None:
            continue
        correct_db_ids.add(db_id)
        if is_new:
            engine.boost_learn_new(idx, answers)
        else:
            engine.learn(answers, idx, strength_factor=factor)
    # 複合正解の共起強化
    correct_idxs = [engine.index_of(db_id) for db_id in correct_db_ids
                    if engine.index_of(db_id) is not None]
    for i in range(len(correct_idxs)):
        for j in range(i + 1, len(correct_idxs)):
            engine.learn_cooccurrence(answers, correct_idxs[i], correct_idxs[j], factor * 0.3)
    # 外れた診断に対するネガティブ学習（正解として選ばれなかったもののみ）
    wrong_db_ids = session.pop('wrong_db_ids', [])
    for wid in wrong_db_ids:
        if wid not in correct_db_ids:
            w_idx = engine.index_of(wid)
            if w_idx is not None:
                engine.learn_negative(answers, w_idx)
    # 候補リストに表示されたが選ばれなかった性癖に弱い負学習（wrong_db_ids より弱め）
    candidate_db_ids = session.pop('candidate_db_ids', [])
    near_miss_db_ids = set(session.pop('near_miss_db_ids', []))
    already_learned = set(wrong_db_ids) | correct_db_ids | near_miss_db_ids
    unselected = [cid for cid in candidate_db_ids if cid not in already_learned]
    n_unsel = max(1, len(unselected))
    candidate_negative_factor = session.pop('candidate_negative_factor', 0.3)
    for cid in unselected:
        c_idx = engine.index_of(cid)
        if c_idx is not None:
            engine.learn_negative(
                answers,
                c_idx,
                strength_factor=factor * candidate_negative_factor / (n_unsel ** 0.5),
            )
    return jsonify({'status': 'done'})


def _admin_guard_response():
    limited = _rate_limit('admin_api', 120)
    if limited:
        return limited
    admin_user = os.environ.get('ADMIN_USER', 'admin')
    admin_pass = os.environ.get('ADMIN_PASS', '')
    if not admin_pass:
        return Response('ADMIN_PASS が未設定です', 503)
    auth = request.authorization
    if not auth or not hmac.compare_digest(auth.username, admin_user) \
            or not hmac.compare_digest(auth.password, admin_pass):
        return Response('認証が必要です', 401,
                        {'WWW-Authenticate': 'Basic realm="Admin"'})
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and not _check_admin_csrf():
        return jsonify({'status': 'error', 'message': 'CSRF token が不正です'}), 403
    return None


@app.route('/api/fetish/<int:fetish_id>', methods=['DELETE'])
def delete_fetish(fetish_id):
    owned = set(session.get('owned_added_fetish_ids', []))
    if fetish_id not in owned:
        guard = _admin_guard_response()
        if guard:
            return guard
        confirm_error = _require_confirm('DELETE')
        if confirm_error:
            return confirm_error
    if fetish_id < PLAYER_FETISH_BASE_ID:
        return jsonify({'status': 'error', 'message': 'シード性癖は削除できません'}), 403
    ok = engine.delete_fetish(fetish_id)
    if not ok:
        return jsonify({'status': 'error', 'message': '見つかりません'}), 404
    if fetish_id in owned:
        owned.remove(fetish_id)
        session['owned_added_fetish_ids'] = sorted(owned)
    return jsonify({'status': 'deleted'})


def _require_admin(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        guard = _admin_guard_response()
        if guard:
            return guard
        return f(*args, **kwargs)
    return decorated


def _most_similar_fetishes(fetish_ids, limit=1):
    """Return nearest matrix neighbors for a small set of fetish ids."""
    import math
    nq = len(engine.questions)
    vectors = []
    for idx, fetish in enumerate(engine.fetishes):
        vec = [engine._prob(idx, q) - 0.5 for q in range(nq)]
        norm = math.sqrt(sum(x * x for x in vec))
        vectors.append((fetish['id'], fetish['name'], vec, norm))

    result = {}
    for fid in fetish_ids:
        idx = engine.index_of(fid)
        if idx is None or idx >= len(vectors):
            result[fid] = []
            continue
        _, _, base_vec, base_norm = vectors[idx]
        matches = []
        for other_id, other_name, other_vec, other_norm in vectors:
            if other_id == fid:
                continue
            if base_norm < 1e-9 or other_norm < 1e-9:
                cos = 0.0
            else:
                cos = sum(a * b for a, b in zip(base_vec, other_vec)) / (base_norm * other_norm)
            matches.append({
                'fetish_id': other_id,
                'fetish_name': other_name,
                'cosine': round(cos, 3),
            })
        matches.sort(key=lambda row: -abs(row['cosine']))
        result[fid] = matches[:limit]
    return result


def _build_work_maintenance_summary(sample_limit=8):
    missing_work_fetishes = []
    missing_url_works = []
    unsafe_url_works = []
    total_works = 0
    for fetish in engine.fetishes:
        works = fetish.get('works') or []
        if not works:
            missing_work_fetishes.append({
                'fetish_id': fetish['id'],
                'fetish_name': fetish['name'],
            })
            continue
        for work in works:
            total_works += 1
            title = work_title(work)
            url = work.get('url', '') if isinstance(work, dict) else ''
            row = {
                'fetish_id': fetish['id'],
                'fetish_name': fetish['name'],
                'title': title,
            }
            if not url:
                missing_url_works.append(row)
            elif not safe_work_url(url):
                unsafe_url_works.append({**row, 'url': str(url)})
    return {
        'total_works': total_works,
        'missing_work_fetish_count': len(missing_work_fetishes),
        'missing_url_work_count': len(missing_url_works),
        'unsafe_url_work_count': len(unsafe_url_works),
        'missing_work_fetishes': missing_work_fetishes[:sample_limit],
        'missing_url_works': missing_url_works[:sample_limit],
        'unsafe_url_works': unsafe_url_works[:sample_limit],
        'works_review_url': '/api/admin/works_review',
    }


def _build_admin_maintenance_checklist():
    report = engine.get_quality_report()
    q_by_id = {q['id']: q for q in engine.get_question_stats()}
    weak_ids = [int(row['fetish_id']) for row in report.get('weak_fetishes', [])]
    nearest = _most_similar_fetishes(weak_ids, limit=1) if weak_ids else {}

    weak_fetishes = []
    for row in report.get('weak_fetishes', []):
        fid = int(row['fetish_id'])
        weak_fetishes.append({
            **row,
            'nearest_similar': (nearest.get(fid) or [None])[0],
            'edit_anchor': '#seed-edit-section',
            'similarity_anchor': '#similarity-section',
            'hint': '説明・作品・特徴質問を見直し、近い性癖との判別差を確認',
        })

    duplicate_questions = []
    for pair in report.get('high_correlation_questions', []):
        q1 = q_by_id.get(pair['q1_id'], {})
        q2 = q_by_id.get(pair['q2_id'], {})
        weaker = q1 if q1.get('disc', 0) <= q2.get('disc', 0) else q2
        duplicate_questions.append({
            **pair,
            'suggested_action': f"Q{weaker.get('id')} の無効化または文言差し替えを検討",
            'weaker_question_id': weaker.get('id'),
        })

    low_questions = [{
        **q,
        'suggested_action': '文言を具体化するか、類似質問と統合/無効化を検討',
    } for q in report.get('low_questions', [])]

    works = _build_work_maintenance_summary()
    checklist = [
        {
            'id': 'weak_fetishes',
            'label': '改善候補の性癖',
            'count': len(weak_fetishes),
            'severity': 'warn' if weak_fetishes else 'ok',
            'next_action': '編集欄で説明・作品を補強し、類似度チェックで近い性癖との差分を見る',
        },
        {
            'id': 'duplicate_questions',
            'label': '重複度が高い質問',
            'count': len(duplicate_questions),
            'severity': 'warn' if duplicate_questions else 'ok',
            'next_action': '弱い方の質問を無効化、または別軸の文言に差し替える',
        },
        {
            'id': 'low_questions',
            'label': '低識別力の質問',
            'count': len(low_questions),
            'severity': 'warn' if low_questions else 'ok',
            'next_action': '質問一覧で識別力と使用量を確認して編集する',
        },
        {
            'id': 'works',
            'label': '作品データの不足',
            'count': works['missing_work_fetish_count'] + works['missing_url_work_count'] + works['unsafe_url_work_count'],
            'severity': 'warn' if (
                works['missing_work_fetish_count'] or works['missing_url_work_count'] or works['unsafe_url_work_count']
            ) else 'ok',
            'next_action': '作品リンク確認からURLなし・不正URL・作品なしの性癖を補修する',
        },
    ]
    return {
        'checklist': checklist,
        'weak_fetishes': weak_fetishes,
        'duplicate_questions': duplicate_questions,
        'low_questions': low_questions,
        'works': works,
    }


@app.route('/admin')
@_require_admin
def admin():
    stats = engine.get_learning_stats()
    s = engine.get_stats()
    player_fetishes = [f for f in engine.fetishes if f['id'] >= PLAYER_FETISH_BASE_ID]
    question_stats   = engine.get_question_stats()
    corr_stats       = engine.get_correlation_stats(top_n=30)
    fetish_log_rows  = _build_fetish_log_rows()
    fetish_log_page  = _paged_fetish_log_rows(fetish_log_rows, request.args)
    domain_suggestions = engine.get_top_questions_per_fetish(top_n=5)
    stats_history  = engine.get_stats_history(days=30)
    matrix_heatmap = engine.get_matrix_heatmap(n_fetishes=20, n_questions=20)
    axis_stats     = engine.get_axis_stats()
    quality_report = engine.get_quality_report()
    maintenance_checklist = _build_admin_maintenance_checklist()
    return render_template('admin.html', stats=stats, play_count=s['play_count'],
                           learn_count=s['learn_count'], player_fetishes=player_fetishes,
                           question_stats=question_stats, corr_stats=corr_stats,
                           fetish_log_rows=fetish_log_rows,
                           fetish_log_page=fetish_log_page,
                           domain_suggestions=domain_suggestions,
                           engine_config=engine.config,
                           config_defaults=engine._CONFIG_DEFAULTS,
                           stats_history=stats_history,
                           matrix_heatmap=matrix_heatmap,
                           axis_stats=axis_stats,
                           quality_report=quality_report,
                           maintenance_checklist=maintenance_checklist,
                           csrf_token=_csrf_token(),
                           csrf_expires_at=int(session.get('admin_csrf_issued_at', 0) + int(os.environ.get('ADMIN_CSRF_TTL_SECONDS', '7200'))),
                           audit_rows=recent_audit(20),
                           matrix_backups=_list_matrix_import_backups())


@app.route('/api/admin/toggle_question/<int:q_id>', methods=['POST'])
@_require_admin
def toggle_question(q_id):
    if q_id < 0 or q_id >= len(engine.questions):
        return jsonify({'status': 'error', 'message': '不正な質問IDです'}), 400
    disabled = engine.toggle_question_disabled(q_id)
    return jsonify({'status': 'ok', 'disabled': disabled})


@app.route('/api/admin/params', methods=['POST'])
@_require_admin
def update_params():
    data = request.get_json(silent=True) or {}
    updated = {}
    errors  = []
    for key, val in data.items():
        try:
            engine.set_config(key, val)
            updated[key] = engine.config[key]
        except (ValueError, KeyError) as e:
            errors.append(str(e))
    return jsonify({'status': 'ok', 'updated': updated, 'errors': errors})


@app.route('/api/admin/cleanup_sessions', methods=['POST'])
@_require_admin
def admin_cleanup_sessions():
    deleted = cleanup_sessions()
    return jsonify({'status': 'ok', 'deleted': deleted})


@app.route('/api/admin/add_fetish', methods=['POST'])
@_require_admin
def admin_add_fetish():
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    desc = data.get('desc', '').strip()
    if not name:
        return jsonify({'status': 'error', 'message': '名前を入力してください'}), 400
    if len(name) > 100:
        return jsonify({'status': 'error', 'message': '名前は100文字以内'}), 400
    if len(desc) > 500:
        return jsonify({'status': 'error', 'message': '説明は500文字以内'}), 400
    existing = next((f for f in engine.fetishes if f['name'] == name), None)
    if existing:
        return jsonify({'status': 'exists', 'fetish_id': existing['id'], 'fetish_name': existing['name']})
    if not desc:
        desc = name
    _, db_id = engine.add_fetish(name, desc, {})
    return jsonify({'status': 'created', 'fetish_id': db_id, 'fetish_name': name})


@app.route('/api/admin/capture_priors', methods=['POST'])
@_require_admin
def admin_capture_priors():
    engine.capture_learned_priors()
    return jsonify({'status': 'ok'})


@app.route('/api/admin/promote_fetish/<int:fetish_id>', methods=['POST'])
@_require_admin
def admin_promote_fetish(fetish_id):
    if fetish_id < PLAYER_FETISH_BASE_ID:
        return jsonify({'status': 'error', 'message': 'シード性癖は格上げ不要です'}), 400
    new_id = engine.promote_fetish(fetish_id)
    if new_id is None:
        return jsonify({'status': 'error', 'message': '見つかりません'}), 404
    return jsonify({'status': 'promoted', 'old_id': fetish_id, 'new_id': new_id})


@app.route('/api/admin/edit_question/<int:q_idx>', methods=['POST'])
@_require_admin
def admin_edit_question(q_idx):
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'status': 'error', 'message': 'text が必要です'}), 400
    if len(text) > 120:
        return jsonify({'status': 'error', 'message': '質問は120文字以内'}), 400
    ok = engine.edit_question(q_idx, text)
    if not ok:
        return jsonify({'status': 'error', 'message': '不正なインデックスです'}), 404
    return jsonify({'status': 'ok', 'q_idx': q_idx, 'text': text})


@app.route('/api/admin/edit_fetish/<int:fetish_id>', methods=['POST'])
@_require_admin
def admin_edit_fetish(fetish_id):
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip() or None
    desc = data.get('desc', '').strip() if 'desc' in data else None
    works = None
    if 'works' in data:
        raw = data['works']
        if isinstance(raw, str):
            raw = [w.strip() for w in raw.split(',') if w.strip()]
        elif not isinstance(raw, list):
            return jsonify({'status': 'error', 'message': 'works はリストまたは文字列で指定してください'}), 400
        works = parse_works_list(raw)
    if name is not None and len(name) > 50:
        return jsonify({'status': 'error', 'message': '名前は50文字以内'}), 400
    if works is not None and len(works) > 10:
        return jsonify({'status': 'error', 'message': '作品は10件以内'}), 400
    ok = engine.edit_fetish(fetish_id, name=name, desc=desc, works=works)
    if not ok:
        return jsonify({'status': 'error', 'message': '見つかりません'}), 404
    idx = engine.index_of(fetish_id)
    f = engine.fetishes[idx]
    return jsonify({'status': 'ok', 'name': f['name'], 'desc': f['desc'], 'works': f.get('works', [])})


@app.route('/api/admin/compound_works', methods=['GET'])
@_require_admin
def admin_list_compound_works():
    items = list_compound_works()
    # 各ペアに性癖名を付与
    result = []
    for item in items:
        ia = engine.index_of(item['id_a'])
        ib = engine.index_of(item['id_b'])
        name_a = engine.fetishes[ia]['name'] if ia is not None else f"id={item['id_a']}"
        name_b = engine.fetishes[ib]['name'] if ib is not None else f"id={item['id_b']}"
        result.append({**item, 'name_a': name_a, 'name_b': name_b})
    return jsonify(result)


@app.route('/api/admin/compound_works', methods=['POST'])
@_require_admin
def admin_set_compound_works():
    data = request.get_json(silent=True) or {}
    try:
        id_a = int(data['id_a'])
        id_b = int(data['id_b'])
    except (KeyError, ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'id_a と id_b が必要です'}), 400
    if id_a == id_b:
        return jsonify({'status': 'error', 'message': '同じIDは指定できません'}), 400
    raw = data.get('works', [])
    if isinstance(raw, str):
        raw = [w.strip() for w in raw.split(',') if w.strip()]
    works = parse_works_list(raw)
    if not works:
        return jsonify({'status': 'error', 'message': '作品を1件以上入力してください'}), 400
    if len(works) > 10:
        return jsonify({'status': 'error', 'message': '作品は10件以内'}), 400
    key = set_compound_works(id_a, id_b, works)
    return jsonify({'status': 'ok', 'key': key, 'works': works})


@app.route('/api/admin/compound_works/<path:key>', methods=['DELETE'])
@_require_admin
def admin_delete_compound_works(key):
    parts = key.split(',')
    if len(parts) != 2:
        return jsonify({'status': 'error', 'message': '不正なキーです'}), 400
    try:
        id_a, id_b = int(parts[0]), int(parts[1])
    except ValueError:
        return jsonify({'status': 'error', 'message': '不正なキーです'}), 400
    ok = delete_compound_works(id_a, id_b)
    if not ok:
        return jsonify({'status': 'error', 'message': '見つかりません'}), 404
    return jsonify({'status': 'deleted', 'key': key})


@app.route('/health')
def health():
    db_ok = False
    matrix_rows = len(engine.matrix.get('yes', []))
    matrix_cols = len(engine.matrix.get('yes', [[]])[0]) if matrix_rows else 0
    matrix_ok = (
        matrix_rows == len(engine.fetishes) and
        matrix_cols == len(engine.questions) and
        len(engine.matrix.get('total', [])) == len(engine.fetishes) and
        all(len(row) == len(engine.questions) for row in engine.matrix.get('yes', [])) and
        all(len(row) == len(engine.questions) for row in engine.matrix.get('total', []))
    )
    backup_path = os.path.join(os.path.dirname(__file__), 'data', 'matrix_backup.json')
    backup_mtime = None
    if os.path.exists(backup_path):
        backup_mtime = int(os.path.getmtime(backup_path))
    matrix_path = data_path('matrix.json')
    matrix_mtime = int(os.path.getmtime(matrix_path)) if os.path.exists(matrix_path) else None
    if _use_db():
        conn = None
        try:
            conn = _get_conn()
            conn.cursor().execute('SELECT 1')
            db_ok = True
        except Exception:
            pass
        finally:
            if conn is not None:
                _put_conn(conn)
    error_total = _ERROR_COUNTS['4xx'] + _ERROR_COUNTS['5xx']
    degraded_reasons = []
    if not matrix_ok:
        degraded_reasons.append('matrix_shape')
    if _ERROR_COUNTS['5xx'] >= int(os.environ.get('HEALTH_5XX_DEGRADED_THRESHOLD', '5')):
        degraded_reasons.append('5xx_threshold')
    if error_total >= int(os.environ.get('HEALTH_ERROR_DEGRADED_THRESHOLD', '50')):
        degraded_reasons.append('error_threshold')
    if _use_db() and not db_ok:
        degraded_reasons.append('db_unavailable')
    return jsonify({
        'status': 'ok' if not degraded_reasons else 'degraded',
        'degraded_reasons': degraded_reasons,
        'db': db_ok,
        'storage': 'postgres' if _use_db() else 'local_json',
        'fetishes': len(engine.fetishes),
        'questions': len(engine.questions),
        'matrix': {'rows': matrix_rows, 'cols': matrix_cols, 'ok': matrix_ok},
        'backup': {'matrix_backup_mtime': backup_mtime},
        'runtime': {
            'started_at': APP_STARTED_AT,
            'uptime_seconds': int(_time.time()) - APP_STARTED_AT,
            'local_sessions': _local_session_count(),
            'error_counts': dict(_ERROR_COUNTS),
        },
        'persistence': {
            'matrix_saved_mtime': matrix_mtime,
            'audit_entries': len(recent_audit(500)),
        },
    })


@app.route('/api/admin/merge_fetishes', methods=['POST'])
@_require_admin
def admin_merge_fetishes():
    data     = request.get_json(silent=True) or {}
    id_keep  = data.get('id_keep')
    id_rm    = data.get('id_remove')
    new_name = (data.get('new_name') or '').strip() or None
    new_desc = (data.get('new_desc') or '').strip() or None
    if id_keep is None or id_rm is None:
        return jsonify({'status': 'error', 'message': 'id_keep と id_remove が必要です'}), 400
    try:
        id_keep = int(id_keep)
        id_rm = int(id_rm)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'id_keep と id_remove は整数で指定してください'}), 400
    confirm_error = _require_confirm('MERGE')
    if confirm_error:
        return confirm_error
    ok = engine.merge_fetishes(id_keep, id_rm, new_name=new_name, new_desc=new_desc)
    if not ok:
        return jsonify({'status': 'error', 'message': '性癖が見つかりません'}), 404
    idx  = engine.index_of(id_keep)
    name = engine.fetishes[idx]['name'] if idx is not None else '(unknown)'
    return jsonify({'status': 'merged', 'id_keep': id_keep, 'name': name})


@app.route('/api/admin/works_review', methods=['GET'])
@_require_admin
def admin_works_review():
    import re as _re
    rows = []
    for fe in engine.fetishes:
        for w in fe.get('works', []):
            title = w['title'] if isinstance(w, dict) else w
            url   = w.get('url', '') if isinstance(w, dict) else ''
            asin  = ''
            if url:
                m = _re.search(r'/dp/([A-Z0-9]{10})', url)
                asin = m.group(1) if m else ''
            rows.append((fe['name'], title, asin, url))
    html = '''<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<title>作品リンク確認</title>
<style>
body{font-family:sans-serif;font-size:13px;background:#111;color:#ddd;padding:16px;}
table{border-collapse:collapse;width:100%;}
th{background:#222;padding:6px 10px;text-align:left;position:sticky;top:0;z-index:1;}
td{padding:5px 10px;border-bottom:1px solid #222;vertical-align:top;}
tr:hover td{background:#1a1a1a;}
a{color:#7af0a0;}
.no-url{color:#e94560;}
input{background:#222;color:#ddd;border:1px solid #444;padding:4px 8px;border-radius:4px;margin-bottom:10px;width:300px;}
</style></head><body>
<h2>作品リンク確認（''' + str(len(rows)) + '''件）</h2>
<input type="text" id="q" placeholder="性癖名や作品名で絞り込み...">
<table id="tbl">
<tr><th>性癖</th><th>作品タイトル</th><th>ASIN</th><th>リンク</th></tr>'''
    for fetish_name, title, asin, url in rows:
        fetish_name_e = _html.escape(str(fetish_name))
        title_e = _html.escape(str(title))
        asin_e = _html.escape(str(asin))
        if url:
            url_e = _html.escape(str(url), quote=True)
            link = f'<a href="{url_e}" target="_blank" rel="noopener">Kindle</a>'
        else:
            link = '<span class="no-url">URLなし</span>'
        html += f'<tr><td>{fetish_name_e}</td><td>{title_e}</td><td>{asin_e}</td><td>{link}</td></tr>'
    html += '''</table>
<script>
document.getElementById("q").addEventListener("input", () => {
  const q = document.getElementById("q").value.toLowerCase();
  document.querySelectorAll("#tbl tr:not(:first-child)").forEach(tr => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none";
  });
});
</script>
</body></html>'''
    return Response(html, mimetype='text/html')


@app.route('/api/admin/export_matrix', methods=['GET'])
@_require_admin
def admin_export_matrix():
    fetishes  = engine.fetishes
    questions = engine.questions
    rows = []
    for fi, f in enumerate(fetishes):
        for qi, q in enumerate(questions):
            y = engine.matrix['yes'][fi][qi]
            t = engine.matrix['total'][fi][qi]
            rows.append({'fetish_id': f['id'], 'fetish_name': f['name'],
                         'question_id': qi, 'question_text': q['text'],
                         'yes': round(y, 4), 'total': round(t, 4)})
    exported_at = _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime())
    payload = _json.dumps({
        'exported_at': exported_at,
        'metadata': {
            'exported_at': exported_at,
            'fetish_count': len(fetishes),
            'question_count': len(questions),
            'matrix_row_count': len(rows),
        },
        'fetishes': fetishes,
        'matrix_rows': rows,
    }, ensure_ascii=False, indent=2)
    return Response(payload, mimetype='application/json',
                    headers={'Content-Disposition': 'attachment; filename="matrix_export.json"'})


@app.route('/api/admin/import_matrix', methods=['POST'])
@_require_admin
def admin_import_matrix():
    data = request.get_json(silent=True) or {}
    rows = data.get('matrix_rows', [])
    if not rows:
        return jsonify({'status': 'error', 'message': 'matrix_rows が空です'}), 400
    try:
        report = engine.validate_matrix_rows(rows)
        complete_error = _matrix_import_completeness_error(report)
        if complete_error:
            return complete_error
        confirm_error = _require_confirm('IMPORT')
        if confirm_error:
            return confirm_error
        backup_path = _snapshot_current_matrix('before_import_matrix')
        count = engine.import_matrix(rows)
    except ValueError as e:
        write_audit('import_matrix', 'error', {'message': str(e)}, request)
        return jsonify({'status': 'error', 'message': str(e)}), 400
    write_audit('import_matrix', 'ok', {
        'imported_rows': count,
        'input_rows': report['input_rows'],
        'skipped_rows': report['skipped_rows'],
        'backup_path': os.path.relpath(backup_path, os.path.dirname(__file__)),
    }, request)
    return jsonify({
        'status': 'ok',
        'imported_rows': count,
        'backup_path': os.path.relpath(backup_path, os.path.dirname(__file__)),
    })


@app.route('/api/admin/import_matrix/dry_run', methods=['POST'])
@_require_admin
def admin_import_matrix_dry_run():
    data = request.get_json(silent=True) or {}
    rows = data.get('matrix_rows', [])
    if not rows:
        return jsonify({'status': 'error', 'message': 'matrix_rows が空です'}), 400
    try:
        report = engine.validate_matrix_rows(rows)
    except ValueError as e:
        write_audit('import_matrix_dry_run', 'error', {'message': str(e)}, request)
        return jsonify({'status': 'error', 'message': str(e)}), 400
    write_audit('import_matrix_dry_run', 'ok', report, request)
    expected_rows = _matrix_import_expected_rows()
    return jsonify({
        'status': 'ok',
        **report,
        'expected_rows': expected_rows,
        'complete': report['skipped_rows'] == 0 and report['valid_rows'] == expected_rows,
    })


@app.route('/api/admin/matrix_backups', methods=['GET'])
@_require_admin
def admin_matrix_backups():
    return jsonify({'status': 'ok', 'backups': _list_matrix_import_backups()})


@app.route('/api/admin/matrix_backups/<path:name>/restore', methods=['POST'])
@_require_admin
def admin_restore_matrix_backup(name):
    safe_name = os.path.basename(name)
    if safe_name != name or not safe_name.endswith('.json'):
        return jsonify({'status': 'error', 'message': '不正なバックアップ名です'}), 400
    path = os.path.join(data_path('matrix_import_backups'), safe_name)
    if not os.path.exists(path):
        return jsonify({'status': 'error', 'message': 'バックアップが見つかりません'}), 404
    payload = load_json_file(os.path.join('matrix_import_backups', safe_name), default={})
    rows = payload.get('matrix_rows', []) if isinstance(payload, dict) else []
    if not rows:
        return jsonify({'status': 'error', 'message': 'matrix_rows が見つかりません'}), 400
    try:
        report = engine.validate_matrix_rows(rows)
        complete_error = _matrix_import_completeness_error(report)
        if complete_error:
            return complete_error
        confirm_error = _require_confirm('RESTORE')
        if confirm_error:
            return confirm_error
        snapshot = _snapshot_current_matrix('before_restore_matrix_backup')
        count = engine.import_matrix(rows)
    except ValueError as e:
        write_audit('restore_matrix_backup', 'error', {'name': safe_name, 'message': str(e)}, request)
        return jsonify({'status': 'error', 'message': str(e)}), 400
    write_audit('restore_matrix_backup', 'ok', {
        'name': safe_name,
        'restored_rows': count,
        'input_rows': report['input_rows'],
        'skipped_rows': report['skipped_rows'],
        'pre_restore_backup': os.path.relpath(snapshot, os.path.dirname(__file__)),
    }, request)
    return jsonify({
        'status': 'ok',
        'restored_rows': count,
        'pre_restore_backup': os.path.relpath(snapshot, os.path.dirname(__file__)),
    })


@app.route('/api/admin/export_log', methods=['GET'])
@_require_admin
def admin_export_log():
    log = engine.get_fetish_log()
    fetish_map = {f['id']: f['name'] for f in engine.fetishes}
    lines = ['id,name,guessed,correct,wrong,accuracy']
    for fid, entry in sorted(log.items(), key=lambda kv: -kv[1].get('guessed', 0)):
        name    = fetish_map.get(fid, str(fid))
        guessed = entry.get('guessed', 0)
        correct = entry.get('correct', 0)
        wrong   = entry.get('wrong', 0)
        acc     = f"{round(correct/guessed*100,1)}" if guessed else ''
        name_esc = '"' + name.replace('"', '""') + '"'
        lines.append(f'{fid},{name_esc},{guessed},{correct},{wrong},{acc}')
    csv_body = '\n'.join(lines)
    return Response(csv_body, mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="fetish_log.csv"'})


@app.route('/api/admin/audit_log', methods=['GET'])
@_require_admin
def admin_export_audit_log():
    rows = recent_audit(_bounded_int(request.args.get('limit'), 500, 1, 500))
    if request.args.get('format') == 'csv':
        lines = ['ts,action,status,method,path,remote_addr,detail']
        for row in rows:
            detail = _json.dumps(row.get('detail', {}), ensure_ascii=False)
            vals = [
                str(row.get('ts', '')),
                row.get('action', ''),
                row.get('status', ''),
                row.get('method', ''),
                row.get('path', ''),
                row.get('remote_addr', ''),
                detail,
            ]
            escaped = ['"' + str(v).replace('"', '""') + '"' for v in vals]
            lines.append(','.join(escaped))
        return Response('\n'.join(lines), mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="admin_audit_log.csv"'})
    return jsonify({'status': 'ok', 'audit_log': rows})


@app.route('/api/admin/preflight', methods=['GET'])
@_require_admin
def admin_preflight():
    checks = []

    def add_check(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': detail})

    add_check('secret_key_configured', bool(os.environ.get('SECRET_KEY')),
              'SECRET_KEY is set' if os.environ.get('SECRET_KEY') else 'SECRET_KEY is using local development fallback')
    add_check('admin_pass_configured', bool(os.environ.get('ADMIN_PASS')),
              'ADMIN_PASS is set' if os.environ.get('ADMIN_PASS') else 'ADMIN_PASS is missing')
    add_check('storage_available', True, 'postgres' if _use_db() else 'local_json')
    add_check('matrix_shape', len(engine.matrix.get('yes', [])) == len(engine.fetishes),
              f"{len(engine.matrix.get('yes', []))} matrix rows / {len(engine.fetishes)} fetishes")
    add_check('matrix_backups_retained', len(_list_matrix_import_backups()) <= int(os.environ.get('MATRIX_IMPORT_BACKUP_KEEP', '20')),
              f"{len(_list_matrix_import_backups())} import backups present")
    add_check('csrf_enabled', _should_enforce_runtime_guard('csrf'), 'enabled for non-test runtime')
    add_check('rate_limit_enabled', _should_enforce_runtime_guard('rate_limit'), 'enabled for non-test runtime')
    ok = all(c['ok'] for c in checks)
    return jsonify({'status': 'ok' if ok else 'warning', 'checks': checks})


@app.route('/api/admin/fetish_history/<int:fetish_id>', methods=['GET'])
@_require_admin
def admin_fetish_history(fetish_id):
    days = _bounded_int(request.args.get('days'), 30, 1, 90)
    history = engine.get_fetish_history(fetish_id, days=days)
    return jsonify(history)


@app.route('/api/admin/fetish_log_rows', methods=['GET'])
@_require_admin
def admin_fetish_log_rows():
    return jsonify({'status': 'ok', **_paged_fetish_log_rows(_build_fetish_log_rows(), request.args)})


@app.route('/api/admin/performance', methods=['GET'])
@_require_admin
def admin_performance():
    measurements = []

    def measure(name, fn):
        start = _time.perf_counter()
        result = fn()
        elapsed = (_time.perf_counter() - start) * 1000
        measurements.append({'name': name, 'ms': round(elapsed, 3)})
        return result

    measure('get_question_stats', engine.get_question_stats)
    measure('get_learning_stats', engine.get_learning_stats)
    measure('get_fetish_log', engine.get_fetish_log)
    measure('best_question_empty', lambda: engine.best_question({}, set()))
    return jsonify({'status': 'ok', 'measurements': measurements})


@app.route('/api/admin/recent_fetish_ranking', methods=['GET'])
@_require_admin
def admin_recent_fetish_ranking():
    days = _bounded_int(request.args.get('days'), 7, 1, 90)
    top_n = _bounded_int(request.args.get('top_n'), 10, 1, 50)
    ranking = engine.get_recent_fetish_ranking(days=days, top_n=top_n)
    return jsonify({'ranking': ranking, 'days': days})


@app.route('/api/admin/export_stats_history', methods=['GET'])
@_require_admin
def admin_export_stats_history():
    history = engine.get_stats_history(days=90)
    lines = ['date,play,learn,correct,wrong']
    for row in history:
        lines.append(f"{row['date']},{row.get('play',0)},{row.get('learn',0)},"
                     f"{row.get('correct',0)},{row.get('wrong',0)}")
    return Response('\n'.join(lines), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="stats_history.csv"'})


@app.route('/api/admin/fetish_similarity', methods=['POST'])
@_require_admin
def admin_fetish_similarity():
    data = request.get_json(silent=True) or {}
    id_a = data.get('id_a')
    id_b = data.get('id_b')
    if id_a is None or id_b is None:
        return jsonify({'status': 'error', 'message': 'id_a と id_b が必要です'}), 400
    try:
        id_a = int(id_a)
        id_b = int(id_b)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'id_a と id_b は整数で指定してください'}), 400
    result = engine.fetish_similarity(id_a, id_b)
    if result is None:
        return jsonify({'status': 'error', 'message': '性癖が見つかりません'}), 404
    return jsonify({'status': 'ok', **result})


@app.route('/api/admin/quality_report', methods=['GET'])
@_require_admin
def admin_quality_report():
    return jsonify(engine.get_quality_report())


@app.route('/api/admin/maintenance_checklist', methods=['GET'])
@_require_admin
def admin_maintenance_checklist():
    return jsonify(_build_admin_maintenance_checklist())


_ERROR_PAGE = '''<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>へきネイター - {title}</title>
<style>
body{{margin:0;background:#0a0a1a;color:#eee;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;}}
h1{{font-size:3rem;color:#e94560;margin-bottom:8px;}}
p{{color:#888;margin-bottom:24px;}}
a{{color:#7af0a0;text-decoration:none;border:1px solid #7af0a0;padding:8px 20px;border-radius:8px;}}
a:hover{{background:#7af0a0;color:#0a0a1a;}}
</style></head><body>
<div>
<div style="font-size:3rem;">{emoji}</div>
<h1>{code}</h1>
<p>{message}</p>
<a href="/">トップに戻る</a>
</div></body></html>'''

@app.errorhandler(404)
def not_found(e):
    return _ERROR_PAGE.format(
        title='ページが見つかりません',
        emoji='🔮', code='404',
        message='ページが見つかりません。'
    ), 404

@app.errorhandler(500)
def server_error(e):
    return _ERROR_PAGE.format(
        title='エラーが発生しました',
        emoji='💀', code='500',
        message='サーバーエラーが発生しました。しばらくしてからお試しください。'
    ), 500

@app.errorhandler(503)
def service_unavailable(e):
    return _ERROR_PAGE.format(
        title='サービス停止中',
        emoji='🛠️', code='503',
        message='ただいまメンテナンス中です。しばらくしてからお試しください。'
    ), 503


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
