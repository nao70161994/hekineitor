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
from services import runtime_guards as runtime_guards_service
from services import matrix_backups as matrix_backup_service
from services import quality_stats as quality_stats_service
from services import ids as ids_service

# ─────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = app_meta_service.secret_key(os.environ)
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
    return share_service.public_base_url(os.environ, request)
APP_STARTED_AT = int(_time.time())
_ERROR_COUNTS = {'4xx': 0, '5xx': 0}
_RATE_LIMIT_BUCKETS = {}


def _should_enforce_runtime_guard(name):
    return runtime_guards_service.should_enforce(app.config, name)

GUESS_THRESHOLD = 0.75
SOFT_MAX_QUESTIONS = 20
HARD_MAX_QUESTIONS = 30
MAX_QUESTIONS   = SOFT_MAX_QUESTIONS




def _record_guess_quality_feedback(correct):
    return quality_stats_service.record_guess_quality_feedback(engine, session, correct)



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


def _seo_context():
    return context_service.seo_context(
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
        render_ogp_svg=ogp_service.render_svg,
        safe_work_url=safe_work_url,
        amazon_associate_id=AMAZON_ASSOCIATE_ID,
        fetish_relations=FETISH_RELATIONS,
        error_page=system_routes.ERROR_PAGE,
    )




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
        question_total_for_count=question_selection_service.make_question_total_for_count(SOFT_MAX_QUESTIONS, HARD_MAX_QUESTIONS),
        soft_max_questions=SOFT_MAX_QUESTIONS,
        hard_max_questions=HARD_MAX_QUESTIONS,
        guess_threshold=GUESS_THRESHOLD,
        focus_threshold=FOCUS_THRESHOLD,
        should_extend_low_confidence=question_selection_service.make_low_confidence_extender(SOFT_MAX_QUESTIONS, HARD_MAX_QUESTIONS),
        select_next_question=question_selection_service.make_next_question_selector(engine),
        progress_message=question_selection_service.progress_message,
    )
    learning = context_service.game_learning(
        learn_factor=learning_service.make_learn_factor(engine, inference_service.posteriors, GUESS_THRESHOLD),
        learn_positive=learning_service.learn_positive,
        learn_cooccurrence=learning_service.learn_cooccurrence,
        learn_near_miss=learning_service.learn_near_miss,
        learn_negative=learning_service.learn_negative,
        posteriors=inference_service.posteriors,
        parse_id_list=ids_service.parse_id_list,
        record_guess_quality_feedback=_record_guess_quality_feedback,
        find_similar=name_matching_service.find_similar,
    )
    admin_bridge = context_service.game_admin_bridge(
        admin_guard_response=_admin_guard_response,
        require_confirm=_require_confirm,
        player_fetish_base_id=PLAYER_FETISH_BASE_ID,
    )
    return context_service.build_game_context(runtime, question_flow, learning, admin_bridge)


PROFILE_MIN_RATIO = 0.25   # best_p に対する比率の下限
PROFILE_MIN_PROB  = 0.08   # 絶対確率の下限
COMPOUND_RATIO    = 0.55   # 2位がこの比率以上なら複合
TRIPLE_RATIO      = 0.45   # 3位がこの比率以上なら三重複合


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


def _make_guess(answers):
    guess_context = context_service.game_guess(
        engine=engine,
        session=session,
        jsonify=jsonify,
        soft_max_questions=SOFT_MAX_QUESTIONS,
        inference_context=_inference_context,
        mark_guess_quality=quality_stats_service.mark_guess_quality,
    )
    return inference_service.make_guess(guess_context, answers)


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
        bounded_int=admin_helper_service.bounded_int,
        build_fetish_log_rows=lambda: admin_helper_service.build_fetish_log_rows(engine),
        paged_fetish_log_rows=admin_helper_service.paged_fetish_log_rows,
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
