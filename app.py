import os
import re
import html as _html
import json as _json
import time as _time
import random as _random
from flask import Flask, render_template, request, jsonify, session, Response
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
from services import context as context_service
from services import server_session as server_session_service
from services import admin_security as admin_security_service
from services import app_meta as app_meta_service
from services import name_matching as name_matching_service
from services import rate_limit as rate_limit_service
from services import response_hooks as response_hooks_service
from services import matrix_backups as matrix_backup_service
from services import quality_stats as quality_stats_service

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
app.session_interface = server_session_service.ServerSessionInterface()


@app.after_request
def _record_status_counts(response):
    return response_hooks_service.after_request(response, request, _ERROR_COUNTS, write_audit)


def _client_ip():
    return rate_limit_service.client_ip(request, app.config, os.environ)


def _rate_limit(scope, limit, window_seconds=60):
    return rate_limit_service.rate_limit(
        scope,
        limit,
        request,
        app.config,
        _RATE_LIMIT_BUCKETS,
        jsonify,
        _should_enforce_runtime_guard,
        window_seconds=window_seconds,
        environ=os.environ,
        time_fn=_time.time,
    )


def _require_confirm(expected):
    return admin_security_service.require_confirm(request, jsonify, expected)


def _csrf_token():
    return admin_security_service.csrf_token(session, os.environ, now_fn=_time.time)

APP_VERSION       = app_meta_service.app_version(os.path.dirname(__file__))
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


def _find_similar(name, fetishes):
    return name_matching_service.find_similar(name, fetishes)


def _question_total_for_count(count):
    return question_selection_service.question_total_for_count(count, SOFT_MAX_QUESTIONS, HARD_MAX_QUESTIONS)


def _should_extend_low_confidence(count, top_p, second_p, guess_thr):
    return question_selection_service.should_extend_low_confidence(
        count, top_p, second_p, guess_thr, SOFT_MAX_QUESTIONS, HARD_MAX_QUESTIONS,
    )


def _record_quality_stat(key, count=1):
    return quality_stats_service.record_quality_stat(engine, key, count)


def _record_guess_quality_feedback(correct):
    return quality_stats_service.record_guess_quality_feedback(engine, session, correct)


def _select_next_question(answers, asked, idk_streak=0, disambiguate=False):
    if disambiguate:
        return question_selection_service.best_disambiguating_question(engine, answers, set(asked), idk_streak=idk_streak)
    return question_selection_service.best_question(engine, answers, set(asked), idk_streak=idk_streak)


def _snapshot_current_matrix(reason):
    return matrix_backup_service.snapshot_current_matrix(
        engine,
        reason,
        data_path=data_path,
        atomic_write_json=atomic_write_json,
        time_module=_time,
        prune_fn=_prune_matrix_import_backups,
        os_module=os,
    )


def _matrix_import_expected_rows():
    return matrix_backup_service.expected_rows(engine)


def _matrix_import_completeness_error(report):
    return matrix_backup_service.completeness_error(
        report, _matrix_import_expected_rows(), jsonify,
    )


def _list_matrix_import_backups(limit=50):
    return matrix_backup_service.list_backups(
        data_path=data_path, os_module=os, limit=limit,
    )


def _prune_matrix_import_backups():
    return matrix_backup_service.prune_backups(
        environ=os.environ,
        data_path=data_path,
        os_module=os,
        list_fn=_list_matrix_import_backups,
    )


def _bounded_int(value, default, min_value=1, max_value=100):
    return admin_helper_service.bounded_int(value, default, min_value, max_value)


def _build_fetish_log_rows():
    return admin_helper_service.build_fetish_log_rows(engine)


def _paged_fetish_log_rows(rows, args):
    return admin_helper_service.paged_fetish_log_rows(rows, args)


def _seo_context():
    return context_service.build_seo_context(
        engine=engine,
        request=request,
        Response=Response,
        render_template=render_template,
        public_base_url=public_base_url,
        work_title=work_title,
        player_fetish_base_id=PLAYER_FETISH_BASE_ID,
        display_version=DISPLAY_VERSION,
        clean_probability=share_service.clean_probability,
        result_share_text=share_service.result_share_text,
        result_tagline=share_service.result_tagline,
        generate_ogp_png=ogp_service.generate_png,
        render_ogp_svg=_render_ogp_svg,
        safe_work_url=safe_work_url,
        amazon_associate_id=AMAZON_ASSOCIATE_ID,
        fetish_relations=FETISH_RELATIONS,
        error_page=system_routes.ERROR_PAGE,
    )


def _ogp_font_candidates():
    return ogp_service._ogp_font_candidates()


def _render_ogp_svg():
    name = request.args.get('f', '???')[:30]
    prob = request.args.get('p', '')[:5]
    svg = ogp_service.render_svg(name, prob)
    return Response(svg, mimetype='image/svg+xml',
                    headers=seo_routes.ogp_cache_headers())


app.register_blueprint(seo_routes.create_blueprint(_seo_context))


def _game_context():
    runtime = context_service.game_runtime(
        engine=engine,
        request=request,
        session=session,
        jsonify=jsonify,
        rate_limit=_rate_limit,
        random_choice=_random.choice,
        logger=app.logger,
    )
    question_flow = context_service.game_question_flow(
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
    )
    learning = context_service.game_learning(
        learn_factor=_learn_factor,
        learn_positive=learning_service.learn_positive,
        learn_cooccurrence=learning_service.learn_cooccurrence,
        learn_near_miss=learning_service.learn_near_miss,
        learn_negative=learning_service.learn_negative,
        posteriors=inference_service.posteriors,
        parse_id_list=_parse_id_list,
        record_guess_quality_feedback=_record_guess_quality_feedback,
        find_similar=_find_similar,
    )
    admin_bridge = context_service.game_admin_bridge(
        admin_guard_response=_admin_guard_response,
        require_confirm=_require_confirm,
        player_fetish_base_id=PLAYER_FETISH_BASE_ID,
    )
    return context_service.build_game_context(runtime, question_flow, learning, admin_bridge)


def _progress_message(count, top_p, second_p, focus_thr=FOCUS_THRESHOLD):
    return question_selection_service.progress_message(count, top_p, second_p, focus_thr)


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
    return context_service.build_inference_context(
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
    quality_stats_service.mark_guess_quality(engine, session, answers, SOFT_MAX_QUESTIONS)
    engine.log_guessed(result['fetish_id'])
    return jsonify(result)


app.register_blueprint(game_routes.create_blueprint(_game_context))


def _admin_context():
    runtime = context_service.admin_runtime(
        engine=engine,
        request=request,
        jsonify=jsonify,
        Response=Response,
        render_template=render_template,
        session=session,
        csrf_token=_csrf_token,
        recent_audit=recent_audit,
        json_dumps=_json.dumps,
        environ=os.environ,
        require_confirm=_require_confirm,
    )
    reporting = context_service.admin_reporting(
        bounded_int=_bounded_int,
        build_fetish_log_rows=_build_fetish_log_rows,
        paged_fetish_log_rows=_paged_fetish_log_rows,
        perf_counter=_time.perf_counter,
        best_question=question_selection_service.best_question,
        build_admin_maintenance_checklist=admin_helper_service.make_admin_maintenance_checklist(
            engine, work_title, safe_work_url,
        ),
        use_db=_use_db,
        list_matrix_import_backups=_list_matrix_import_backups,
        should_enforce_runtime_guard=_should_enforce_runtime_guard,
        cleanup_sessions=server_session_service.cleanup_sessions,
        player_fetish_base_id=PLAYER_FETISH_BASE_ID,
        strftime=_time.strftime,
        gmtime=_time.gmtime,
    )
    maintenance = context_service.admin_maintenance(
        parse_works_list=parse_works_list,
        list_compound_works=list_compound_works,
        set_compound_works=set_compound_works,
        delete_compound_works=delete_compound_works,
        write_audit=write_audit,
        load_json_file=load_json_file,
        data_path=data_path,
    )
    matrix_tools = context_service.admin_matrix_tools(
        app_dir=os.path.dirname(__file__),
        relpath=os.path.relpath,
        basename=os.path.basename,
        join_path=os.path.join,
        path_exists=os.path.exists,
        re_search=re.search,
        html_escape=_html.escape,
        snapshot_current_matrix=_snapshot_current_matrix,
        matrix_import_completeness_error=_matrix_import_completeness_error,
        matrix_import_expected_rows=_matrix_import_expected_rows,
    )
    return context_service.build_admin_context(runtime, reporting, maintenance, matrix_tools)


def _admin_guard_response():
    return admin_security_service.admin_guard_response(
        request, os.environ, session, Response, jsonify, _rate_limit, _should_enforce_runtime_guard,
    )


app.register_blueprint(admin_routes.create_blueprint(
    _admin_context,
    admin_security_service.require_admin_decorator(_admin_guard_response),
))


def _system_context():
    runtime = context_service.system_runtime(
        engine=engine,
        jsonify=jsonify,
        Response=Response,
        render_template=render_template,
        static_folder=app.static_folder,
        app_version=APP_VERSION,
        environ=os.environ,
        error_counts=_ERROR_COUNTS,
        app_started_at=APP_STARTED_AT,
        time=_time.time,
        local_session_count=server_session_service.local_session_count,
        recent_audit=recent_audit,
    )
    storage = context_service.system_storage(
        use_db=_use_db,
        get_conn=_get_conn,
        put_conn=_put_conn,
        data_path=data_path,
        app_dir=os.path.dirname(__file__),
        join_path=os.path.join,
        path_exists=os.path.exists,
        path_getmtime=os.path.getmtime,
    )
    return context_service.build_system_context(runtime, storage)


app.register_blueprint(system_routes.create_public_blueprint(_system_context))
app.register_blueprint(system_routes.create_health_blueprint(_system_context))


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
