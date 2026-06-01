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
from services import share as share_service
from services import share_events as share_events_service
from services import question_events as question_events_service
from services import share_notes as share_notes_service
from services import test_play as test_play_service
from services import game_context as game_context_service
from services import seo_context as seo_context_service
from services import admin_context as admin_context_service
from services import system_context as system_context_service
from services import server_session as server_session_service
from services import app_meta as app_meta_service
from services import bootstrap as bootstrap_service
from services import response_hooks as response_hooks_service
from services import matrix_backups as matrix_backup_service
from services import runtime as runtime_service
from services import filesystem_context as filesystem_context_service

# ─────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = app_meta_service.secret_key(os.environ)
app.session_interface = server_session_service.ServerSessionInterface()


@app.after_request
def _record_status_counts(response):
    return response_hooks_service.after_request(response, request, _ERROR_COUNTS, write_audit)


def _flask_runtime():
    return runtime_service.flask_runtime(
        request=request,
        session=session,
        response_cls=Response,
        jsonify=jsonify,
        app_config=app.config,
        environ=os.environ,
        buckets=_RATE_LIMIT_BUCKETS,
        time_fn=_time.time,
    )

BOOTSTRAP = bootstrap_service.app_bootstrap(
    base_dir=os.path.dirname(__file__),
    environ=os.environ,
    app_version_fn=app_meta_service.app_version,
)
engine = Engine()


def public_base_url():
    return share_service.public_base_url(os.environ, request)
APP_STARTED_AT = int(_time.time())
_ERROR_COUNTS = {'4xx': 0, '5xx': 0}
_RATE_LIMIT_BUCKETS = {}


def _filesystem_context():
    return filesystem_context_service.filesystem_context(
        app_dir=os.path.dirname(__file__),
        os_module=os,
        re_module=re,
        html_escape=_html.escape,
        data_path=data_path,
        atomic_write_json=atomic_write_json,
        load_json_file=load_json_file,
    )


def _matrix_operations():
    return matrix_backup_service.operations_for_filesystem(
        engine=engine,
        filesystem=_filesystem_context(),
        time_module=_time,
        jsonify=jsonify,
        environ=os.environ,
    )


def _seo_context():
    return seo_context_service.build(
        engine=engine,
        request=request,
        response_cls=Response,
        render_template=render_template,
        public_base_url=public_base_url,
        work_title=work_title,
        player_fetish_base_id=PLAYER_FETISH_BASE_ID,
        display_version=BOOTSTRAP.display_version,
        app_version=BOOTSTRAP.app_version,
        safe_work_url=safe_work_url,
        amazon_associate_id=BOOTSTRAP.amazon_associate_id,
        adsense_client=BOOTSTRAP.adsense_client,
        fetish_relations=FETISH_RELATIONS,
        error_page=system_routes.ERROR_PAGE,
        record_share_event=lambda *args, **kwargs: share_events_service.safe_record_event(*args, environ=os.environ, **kwargs),
        learning_disabled=lambda: test_play_service.is_learning_disabled(session),
        rate_limit=_flask_runtime().rate_limit,
        environ=os.environ,
    )


def _game_context():
    return game_context_service.build(
        engine=engine,
        flask_runtime=_flask_runtime(),
        random_choice=_random.choice,
        logger=app.logger,
        player_fetish_base_id=PLAYER_FETISH_BASE_ID,
        soft_max_questions=BOOTSTRAP.soft_max_questions,
        hard_max_questions=BOOTSTRAP.hard_max_questions,
        guess_threshold=BOOTSTRAP.guess_threshold,
        focus_threshold=FOCUS_THRESHOLD,
        work_title=work_title,
        get_compound_works=get_compound_works,
        record_share_event=lambda *args, **kwargs: share_events_service.safe_record_event(*args, environ=os.environ, **kwargs),
        record_question_event=lambda *args, **kwargs: question_events_service.safe_record_event(*args, environ=os.environ, **kwargs),
        preserve_test_play_flag=lambda: test_play_service.preserve_flag(session),
        restore_test_play_flag=lambda enabled: test_play_service.restore_flag(session, enabled),
        learning_disabled=lambda: test_play_service.is_learning_disabled(session),
        environ=os.environ,
    )


def _share_event_allowed_result_names():
    return {
        str(fetish.get('name') or '').strip()
        for fetish in getattr(engine, 'fetishes', [])
        if str(fetish.get('name') or '').strip()
    }


def _admin_share_event_report(**kwargs):
    return share_events_service.event_report(
        environ=os.environ,
        allowed_result_names=_share_event_allowed_result_names(),
        **kwargs,
    )


def _admin_context():
    return admin_context_service.build(
        engine=engine,
        flask_runtime=_flask_runtime(),
        render_template=render_template,
        recent_audit=recent_audit,
        json_dumps=_json.dumps,
        perf_counter=_time.perf_counter,
        work_title=work_title,
        safe_work_url=safe_work_url,
        amazon_associate_id=BOOTSTRAP.amazon_associate_id,
        use_db=_use_db,
        matrix_ops=_matrix_operations(),
        cleanup_sessions=server_session_service.cleanup_sessions,
        player_fetish_base_id=PLAYER_FETISH_BASE_ID,
        strftime=_time.strftime,
        gmtime=_time.gmtime,
        parse_works_list=parse_works_list,
        list_compound_works=list_compound_works,
        set_compound_works=set_compound_works,
        delete_compound_works=delete_compound_works,
        write_audit=write_audit,
        filesystem=_filesystem_context(),
        share_event_report=_admin_share_event_report,
        question_event_report=lambda **kwargs: question_events_service.event_report(engine, environ=os.environ, **kwargs),
        share_event_count=lambda: share_events_service.event_count(environ=os.environ),
        question_event_count=lambda: question_events_service.event_count(environ=os.environ),
        share_event_storage_status=lambda: share_events_service.storage_status(environ=os.environ),
        question_event_storage_status=lambda: question_events_service.storage_status(environ=os.environ),
        load_share_notes=lambda: share_notes_service.load_notes(environ=os.environ),
        save_share_note=lambda result_name, note: share_notes_service.save_note(result_name, note, environ=os.environ),
        enable_test_play=lambda: test_play_service.enable(session),
        disable_test_play=lambda: test_play_service.disable(session),
        is_test_play=lambda: test_play_service.is_learning_disabled(session),
    )


def _system_context():
    return system_context_service.build(
        engine=engine,
        jsonify=jsonify,
        response_cls=Response,
        render_template=render_template,
        static_folder=app.static_folder,
        app_version=BOOTSTRAP.app_version,
        environ=os.environ,
        error_counts=_ERROR_COUNTS,
        adsense_client=BOOTSTRAP.adsense_client,
        app_started_at=APP_STARTED_AT,
        time_fn=_time.time,
        local_session_count=server_session_service.local_session_count,
        recent_audit=recent_audit,
        use_db=_use_db,
        get_conn=_get_conn,
        put_conn=_put_conn,
        filesystem=_filesystem_context(),
    )


def _register_blueprints(application):
    application.register_blueprint(seo_routes.create_blueprint(_seo_context))
    application.register_blueprint(game_routes.create_blueprint(_game_context))
    application.register_blueprint(admin_routes.create_blueprint(
        _admin_context,
        runtime_service.require_admin_decorator(lambda: _flask_runtime().admin_guard_response()),
        runtime_service.require_admin_or_read_decorator(
            lambda: _flask_runtime().admin_guard_response(),
            lambda: _flask_runtime().admin_read_guard_response(),
        ),
    ))
    application.register_blueprint(system_routes.create_public_blueprint(_system_context))
    application.register_blueprint(system_routes.create_health_blueprint(_system_context))


def _register_error_handlers(application):
    application.register_error_handler(404, lambda e: system_routes.not_found())
    application.register_error_handler(500, lambda e: system_routes.server_error())
    application.register_error_handler(503, lambda e: system_routes.service_unavailable())


_register_blueprints(app)
_register_error_handlers(app)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
