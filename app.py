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
from types import SimpleNamespace
from flask import Flask, render_template, request, jsonify, session, Response
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict
from engine import (Engine, PLAYER_FETISH_BASE_ID, _get_conn, _put_conn, _use_db,
                    FOCUS_THRESHOLD, FETISH_RELATIONS, get_compound_works,
                    list_compound_works, set_compound_works, delete_compound_works,
                    parse_works_list)
from audit import recent_audit, write_audit
from storage import atomic_write_json, data_path, load_json_file
from work_utils import safe_work_url, work_title
from routes import admin as admin_routes
from routes import game as game_routes
from routes import seo as seo_routes
from routes import system as system_routes
from services import inference as inference_service
from services import learning as learning_service
from services import question_selection as question_selection_service
from services import ogp as ogp_service
from services import share as share_service
from services import admin_helpers as admin_helper_service
from services import works_links as works_links_service

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


def public_base_url():
    configured = os.environ.get('SITE_BASE_URL', '').strip().rstrip('/')
    if configured:
        return configured
    return request.host_url.rstrip('/')
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
    return question_selection_service.question_total_for_count(count, SOFT_MAX_QUESTIONS, HARD_MAX_QUESTIONS)


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
        return question_selection_service.best_disambiguating_question(engine, answers, set(asked), idk_streak=idk_streak)
    return question_selection_service.best_question(engine, answers, set(asked), idk_streak=idk_streak)


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
    return admin_helper_service.bounded_int(value, default, min_value, max_value)


def _build_fetish_log_rows():
    return admin_helper_service.build_fetish_log_rows(engine)


def _paged_fetish_log_rows(rows, args):
    return admin_helper_service.paged_fetish_log_rows(rows, args)


def _seo_context():
    return SimpleNamespace(
        engine=engine,
        request=request,
        Response=Response,
        render_template=render_template,
        public_base_url=public_base_url,
        work_title=work_title,
        player_fetish_base_id=PLAYER_FETISH_BASE_ID,
        display_version=DISPLAY_VERSION,
        clean_probability=_clean_probability,
        result_share_text=_result_share_text,
        result_tagline=_result_tagline,
        generate_ogp_png=_generate_ogp_png,
        render_ogp_svg=_render_ogp_svg,
        safe_work_url=safe_work_url,
        amazon_associate_id=AMAZON_ASSOCIATE_ID,
        fetish_relations=FETISH_RELATIONS,
        error_page=system_routes.ERROR_PAGE,
    )


@app.route('/')
def index():
    return seo_routes.index(_seo_context())


@app.route('/fetishes')
def fetish_index():
    return seo_routes.fetish_index(_seo_context())


@app.route('/r')
def result_share():
    return seo_routes.result_share(_seo_context())


def _clean_probability(raw):
    return share_service.clean_probability(raw)


def _result_share_text(name, prob):
    return share_service.result_share_text(name, prob)


def _result_tagline(name, prob):
    return share_service.result_tagline(name, prob)


def _ogp_font_candidates():
    return ogp_service._ogp_font_candidates()


def _generate_ogp_png(name, prob):
    return ogp_service.generate_png(name, prob)


def _render_ogp_svg():
    name = request.args.get('f', '???')[:30]
    prob = request.args.get('p', '')[:5]
    svg = ogp_service.render_svg(name, prob)
    return Response(svg, mimetype='image/svg+xml',
                    headers=seo_routes.ogp_cache_headers())


@app.route('/ogp.png')
def ogp_png_image():
    return seo_routes.ogp_png_image(_seo_context())


@app.route('/ogp')
def ogp_image():
    return seo_routes.ogp_svg_image(_seo_context())



@app.route('/manifest.json')
def manifest():
    return system_routes.manifest(_system_context())


@app.route('/sw.js')
def sw():
    return system_routes.service_worker(_system_context())


@app.route('/offline')
def offline():
    return system_routes.offline(_system_context())


@app.route('/fetish/<int:fetish_id>')
def fetish_detail(fetish_id):
    return seo_routes.fetish_detail(_seo_context(), fetish_id)


@app.route('/stats')
def stats_page():
    return seo_routes.stats_page(_seo_context())


@app.route('/robots.txt')
def robots_txt():
    return seo_routes.robots_txt(_seo_context())


@app.route('/sitemap.xml')
def sitemap_xml():
    return seo_routes.sitemap_xml(_seo_context())


def _game_context():
    return SimpleNamespace(
        engine=engine,
        request=request,
        session=session,
        jsonify=jsonify,
        rate_limit=_rate_limit,
        random_choice=_random.choice,
        best_question=question_selection_service.best_question,
        top_guess=inference_service.top_guess,
        make_guess=_make_guess,
        question_total_for_count=_question_total_for_count,
        soft_max_questions=SOFT_MAX_QUESTIONS,
        hard_max_questions=HARD_MAX_QUESTIONS,
        guess_threshold=GUESS_THRESHOLD,
        focus_threshold=FOCUS_THRESHOLD,
        should_extend_low_confidence=_should_extend_low_confidence,
        select_next_question=_select_next_question,
        progress_message=_progress_message,
        logger=app.logger,
        learn_factor=_learn_factor,
        learn_positive=learning_service.learn_positive,
        learn_cooccurrence=learning_service.learn_cooccurrence,
        learn_near_miss=learning_service.learn_near_miss,
        learn_negative=learning_service.learn_negative,
        posteriors=inference_service.posteriors,
        parse_id_list=_parse_id_list,
        record_guess_quality_feedback=_record_guess_quality_feedback,
        find_similar=_find_similar,
        admin_guard_response=_admin_guard_response,
        require_confirm=_require_confirm,
        player_fetish_base_id=PLAYER_FETISH_BASE_ID,
    )


@app.route('/api/start', methods=['POST'])
def start():
    return game_routes.start(_game_context())


@app.route('/api/resume', methods=['POST'])
def resume():
    return game_routes.resume(_game_context())


@app.route('/api/continue', methods=['POST'])
def continue_game():
    return game_routes.continue_game(_game_context())


def _progress_message(count, top_p, second_p, focus_thr=FOCUS_THRESHOLD):
    return question_selection_service.progress_message(count, top_p, second_p, focus_thr)


@app.route('/api/answer', methods=['POST'])
def answer():
    return game_routes.answer(_game_context())


@app.route('/api/back', methods=['POST'])
def back():
    return game_routes.back(_game_context())


PROFILE_MIN_RATIO = 0.25   # best_p に対する比率の下限
PROFILE_MIN_PROB  = 0.08   # 絶対確率の下限
COMPOUND_RATIO    = 0.55   # 2位がこの比率以上なら複合
TRIPLE_RATIO      = 0.45   # 3位がこの比率以上なら三重複合

def _learn_factor(answers, total_n=1):
    threshold = engine.config.get('guess_threshold', GUESS_THRESHOLD)
    return learning_service.learn_factor(engine, inference_service.posteriors, answers, threshold, total_n)


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


def _inference_context():
    return SimpleNamespace(
        engine=engine,
        session=session,
        work_title=work_title,
        get_compound_works=get_compound_works,
        profile_min_ratio=PROFILE_MIN_RATIO,
        profile_min_prob=PROFILE_MIN_PROB,
        compound_ratio=COMPOUND_RATIO,
        triple_ratio=TRIPLE_RATIO,
    )


def _compute_guess(answers):
    """診断結果を返す（play_count はインクリメントしない、純粋計算）。"""
    return inference_service.compute_guess(_inference_context(), answers)


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
    return game_routes.confirm(_game_context())


@app.route('/api/teach', methods=['POST'])
def teach():
    return game_routes.teach(_game_context())


@app.route('/api/add_fetish', methods=['POST'])
def add_fetish():
    return game_routes.add_fetish(_game_context())


@app.route('/api/finalize_added', methods=['POST'])
def finalize_added():
    return game_routes.finalize_added(_game_context())


def _admin_context():
    return SimpleNamespace(
        engine=engine,
        request=request,
        jsonify=jsonify,
        Response=Response,
        render_template=render_template,
        session=session,
        csrf_token=_csrf_token,
        bounded_int=_bounded_int,
        build_fetish_log_rows=_build_fetish_log_rows,
        paged_fetish_log_rows=_paged_fetish_log_rows,
        perf_counter=_time.perf_counter,
        best_question=question_selection_service.best_question,
        build_admin_maintenance_checklist=_build_admin_maintenance_checklist,
        recent_audit=recent_audit,
        json_dumps=_json.dumps,
        environ=os.environ,
        use_db=_use_db,
        list_matrix_import_backups=_list_matrix_import_backups,
        should_enforce_runtime_guard=_should_enforce_runtime_guard,
        parse_works_list=parse_works_list,
        list_compound_works=list_compound_works,
        set_compound_works=set_compound_works,
        delete_compound_works=delete_compound_works,
        cleanup_sessions=cleanup_sessions,
        player_fetish_base_id=PLAYER_FETISH_BASE_ID,
        strftime=_time.strftime,
        gmtime=_time.gmtime,
        require_confirm=_require_confirm,
        snapshot_current_matrix=_snapshot_current_matrix,
        matrix_import_completeness_error=_matrix_import_completeness_error,
        matrix_import_expected_rows=_matrix_import_expected_rows,
        write_audit=write_audit,
        load_json_file=load_json_file,
        data_path=data_path,
        app_dir=os.path.dirname(__file__),
        relpath=os.path.relpath,
        basename=os.path.basename,
        join_path=os.path.join,
        path_exists=os.path.exists,
        re_search=re.search,
        html_escape=_html.escape,
    )


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
    return game_routes.delete_fetish(_game_context(), fetish_id)


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
    return works_links_service.build_work_maintenance_summary(
        engine.fetishes,
        work_title_fn=work_title,
        safe_work_url_fn=safe_work_url,
        sample_limit=sample_limit,
    )


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
    return admin_routes.admin_page(_admin_context())


@app.route('/api/admin/toggle_question/<int:q_id>', methods=['POST'])
@_require_admin
def toggle_question(q_id):
    return admin_routes.toggle_question(_admin_context(), q_id)


@app.route('/api/admin/params', methods=['POST'])
@_require_admin
def update_params():
    return admin_routes.update_params(_admin_context())


@app.route('/api/admin/cleanup_sessions', methods=['POST'])
@_require_admin
def admin_cleanup_sessions():
    return admin_routes.cleanup_sessions(_admin_context())


@app.route('/api/admin/add_fetish', methods=['POST'])
@_require_admin
def admin_add_fetish():
    return admin_routes.add_fetish(_admin_context())


@app.route('/api/admin/capture_priors', methods=['POST'])
@_require_admin
def admin_capture_priors():
    return admin_routes.capture_priors(_admin_context())


@app.route('/api/admin/promote_fetish/<int:fetish_id>', methods=['POST'])
@_require_admin
def admin_promote_fetish(fetish_id):
    return admin_routes.promote_fetish(_admin_context(), fetish_id)


@app.route('/api/admin/edit_question/<int:q_idx>', methods=['POST'])
@_require_admin
def admin_edit_question(q_idx):
    return admin_routes.edit_question(_admin_context(), q_idx)


@app.route('/api/admin/edit_fetish/<int:fetish_id>', methods=['POST'])
@_require_admin
def admin_edit_fetish(fetish_id):
    return admin_routes.edit_fetish(_admin_context(), fetish_id)


@app.route('/api/admin/compound_works', methods=['GET'])
@_require_admin
def admin_list_compound_works():
    return admin_routes.list_compound_works(_admin_context())


@app.route('/api/admin/compound_works', methods=['POST'])
@_require_admin
def admin_set_compound_works():
    return admin_routes.set_compound_works(_admin_context())


@app.route('/api/admin/compound_works/<path:key>', methods=['DELETE'])
@_require_admin
def admin_delete_compound_works(key):
    return admin_routes.delete_compound_works(_admin_context(), key)


def _system_context():
    return SimpleNamespace(
        engine=engine,
        jsonify=jsonify,
        Response=Response,
        render_template=render_template,
        static_folder=app.static_folder,
        app_version=APP_VERSION,
        environ=os.environ,
        use_db=_use_db,
        get_conn=_get_conn,
        put_conn=_put_conn,
        data_path=data_path,
        app_dir=os.path.dirname(__file__),
        join_path=os.path.join,
        path_exists=os.path.exists,
        path_getmtime=os.path.getmtime,
        error_counts=_ERROR_COUNTS,
        app_started_at=APP_STARTED_AT,
        time=_time.time,
        local_session_count=_local_session_count,
        recent_audit=recent_audit,
    )


@app.route('/health')
def health():
    return system_routes.health(_system_context())


@app.route('/api/admin/merge_fetishes', methods=['POST'])
@_require_admin
def admin_merge_fetishes():
    return admin_routes.merge_fetishes(_admin_context())


@app.route('/api/admin/works_review', methods=['GET'])
@_require_admin
def admin_works_review():
    return admin_routes.works_review(_admin_context())


@app.route('/api/admin/works_link_queue', methods=['GET'])
def admin_works_link_queue():
    guard = _admin_guard_response()
    if guard:
        return guard
    try:
        sample_limit = max(1, min(int(request.args.get('sample_limit', 20)), 100))
    except ValueError:
        sample_limit = 20
    return jsonify(admin_routes.works_link_queue_payload(engine, sample_limit=sample_limit))


@app.route('/api/admin/export_matrix', methods=['GET'])
@_require_admin
def admin_export_matrix():
    return admin_routes.export_matrix(_admin_context())


@app.route('/api/admin/import_matrix', methods=['POST'])
@_require_admin
def admin_import_matrix():
    return admin_routes.import_matrix(_admin_context())


@app.route('/api/admin/import_matrix/dry_run', methods=['POST'])
@_require_admin
def admin_import_matrix_dry_run():
    return admin_routes.import_matrix_dry_run(_admin_context())


@app.route('/api/admin/matrix_backups', methods=['GET'])
@_require_admin
def admin_matrix_backups():
    return admin_routes.matrix_backups(_admin_context())


@app.route('/api/admin/matrix_backups/<path:name>/restore', methods=['POST'])
@_require_admin
def admin_restore_matrix_backup(name):
    return admin_routes.restore_matrix_backup(_admin_context(), name)


@app.route('/api/admin/export_log', methods=['GET'])
@_require_admin
def admin_export_log():
    return admin_routes.export_log(_admin_context())


@app.route('/api/admin/audit_log', methods=['GET'])
@_require_admin
def admin_export_audit_log():
    return admin_routes.audit_log(_admin_context())


@app.route('/api/admin/preflight', methods=['GET'])
@_require_admin
def admin_preflight():
    return admin_routes.preflight(_admin_context())


@app.route('/api/admin/fetish_history/<int:fetish_id>', methods=['GET'])
@_require_admin
def admin_fetish_history(fetish_id):
    return admin_routes.fetish_history(_admin_context(), fetish_id)


@app.route('/api/admin/fetish_log_rows', methods=['GET'])
@_require_admin
def admin_fetish_log_rows():
    return admin_routes.fetish_log_rows(_admin_context())


@app.route('/api/admin/performance', methods=['GET'])
@_require_admin
def admin_performance():
    return admin_routes.performance(_admin_context())


@app.route('/api/admin/recent_fetish_ranking', methods=['GET'])
@_require_admin
def admin_recent_fetish_ranking():
    return admin_routes.recent_fetish_ranking(_admin_context())


@app.route('/api/admin/export_stats_history', methods=['GET'])
@_require_admin
def admin_export_stats_history():
    return admin_routes.export_stats_history(_admin_context())


@app.route('/api/admin/fetish_similarity', methods=['POST'])
@_require_admin
def admin_fetish_similarity():
    return admin_routes.fetish_similarity(_admin_context())


@app.route('/api/admin/quality_report', methods=['GET'])
@_require_admin
def admin_quality_report():
    return admin_routes.quality_report(_admin_context())


@app.route('/api/admin/maintenance_checklist', methods=['GET'])
@_require_admin
def admin_maintenance_checklist():
    return admin_routes.maintenance_checklist(_admin_context())


@app.errorhandler(404)
def not_found(e):
    return system_routes.not_found()


@app.errorhandler(500)
def server_error(e):
    return system_routes.server_error()


@app.errorhandler(503)
def service_unavailable(e):
    return system_routes.service_unavailable()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
