import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import audit
from routes import game as game_routes
from services import (
    admin_context,
    admin_helpers,
    admin_security,
    app_meta,
    bootstrap,
    context,
    csv_safety,
    event_store,
    filesystem_context,
    game_context,
    ids,
    improvement_candidates,
    inference,
    matrix_backups,
    name_matching,
    ogp,
    quality_stats,
    question_events,
    question_selection,
    rate_limit,
    response_hooks,
    result_exposure,
    runtime_guards,
    seo_context,
    share,
    share_events,
    share_links,
    share_notes,
    system_context,
    test_play,
    works_links,
)
from services import (
    runtime as runtime_service,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

__all__ = [
    'DummyAuth',
    'DummyLogEngine',
    'DummyRequest',
    'admin_context',
    'admin_helpers',
    'admin_security',
    'app_meta',
    'audit',
    'bootstrap',
    'context',
    'csv_safety',
    'dummy_jsonify',
    'dummy_runtime',
    'event_store',
    'filesystem_context',
    'game_context',
    'game_routes',
    'ids',
    'improvement_candidates',
    'inference',
    'json',
    'matrix_backups',
    'name_matching',
    'ogp',
    'os',
    'patch',
    'quality_stats',
    'question_events',
    'question_selection',
    'rate_limit',
    'response_hooks',
    'result_exposure',
    'runtime_guards',
    'runtime_service',
    'seo_context',
    'share',
    'share_events',
    'share_links',
    'share_notes',
    'system_context',
    'tempfile',
    'test_play',
    'unittest',
    'works_links',
]


class DummyRequest:
    def __init__(self, json_data=None, headers=None, method='GET', authorization=None):
        self._json_data = json_data
        self.headers = headers or {}
        self.method = method
        self.authorization = authorization

    def get_json(self, silent=True):
        return self._json_data


class DummyAuth:
    def __init__(self, username, password):
        self.username = username
        self.password = password


def dummy_jsonify(payload):
    return payload


def dummy_runtime(**overrides):
    req = overrides.pop('request', DummyRequest())
    req.remote_addr = getattr(req, 'remote_addr', '127.0.0.1')
    return runtime_service.flask_runtime(
        request=req,
        session=overrides.pop('session', {}),
        response_cls=overrides.pop('response_cls', object),
        jsonify=overrides.pop('jsonify', dummy_jsonify),
        app_config=overrides.pop('app_config', {'TESTING': True}),
        environ=overrides.pop('environ', {}),
        buckets=overrides.pop('buckets', {}),
        time_fn=overrides.pop('time_fn', lambda: 100),
    )


class DummyLogEngine:
    fetishes = [
        {'id': 1, 'name': 'OnlyGuessed'},
        {'id': 2, 'name': 'MixedFeedback'},
    ]

    def get_fetish_log(self):
        return {
            1: {'guessed': 10, 'correct': 0, 'wrong': 0},
            2: {'guessed': 10, 'correct': 3, 'wrong': 1},
        }
