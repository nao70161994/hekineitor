import ast
import inspect

from flask import Flask

from routes import admin
from routes.admin_sections import matrix_handlers

MATRIX_HANDLER_NAMES = (
    '_export_player_fetishes_to_restore',
    '_missing_export_player_fetishes',
    '_backup_integer',
    '_matrix_backup_format_version',
    '_adapt_matrix_rows_to_current_questions',
    '_import_validation_report',
    '_matrix_import_completeness_error',
    'export_matrix',
    'import_matrix',
    'import_matrix_dry_run',
    'matrix_backups',
    'restore_matrix_backup',
)


def test_admin_matrix_handler_wrappers_preserve_signatures_and_patch_targets():
    for name in MATRIX_HANDLER_NAMES:
        wrapper = getattr(admin, name)
        implementation = getattr(matrix_handlers, name)

        assert inspect.signature(wrapper) == inspect.signature(implementation)

        function_node = ast.parse(inspect.getsource(wrapper)).body[0]
        assert isinstance(function_node, ast.FunctionDef)
        assert len(function_node.body) == 1
        assert isinstance(function_node.body[0], ast.Return)


def test_matrix_registrar_still_uses_routes_admin_wrappers(monkeypatch):
    sentinel = object()
    context = object()
    app = Flask(__name__)
    blueprint = admin.create_blueprint(
        lambda: context,
        lambda handler: handler,
    )
    app.register_blueprint(blueprint)

    monkeypatch.setattr(
        admin,
        'export_matrix',
        lambda ctx: sentinel if ctx is context else None,
    )

    assert app.view_functions['admin_routes.export_matrix_route']() is sentinel
