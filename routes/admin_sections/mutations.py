"""Question, fetish, configuration, and session mutation routes."""


def register_routes(bp, *, ctx_factory, require_admin, require_admin_or_read, resolve_handler):
    """Register admin mutation endpoints on ``bp``."""

    routes = (
        ('/api/admin/toggle_question/<int:q_id>', 'toggle_question_route', ['POST'], 'admin', 'toggle_question'),
        ('/api/admin/params', 'update_params_route', ['POST'], 'admin', 'update_params'),
        ('/api/admin/cleanup_sessions', 'cleanup_sessions_route', ['POST'], 'admin', 'cleanup_sessions'),
        ('/api/admin/add_fetish', 'add_fetish_route', ['POST'], 'admin', 'add_fetish'),
        ('/api/admin/capture_priors', 'capture_priors_route', ['POST'], 'admin', 'capture_priors'),
        ('/api/admin/fetish_lookup/<int:fetish_id>', 'fetish_lookup_route', ['GET'], 'read', 'lookup_fetish'),
        ('/api/admin/promote_fetish/<int:fetish_id>', 'promote_fetish_route', ['POST'], 'admin', 'promote_fetish'),
        (
            '/api/admin/repair_promoted_stats_history',
            'repair_promoted_stats_history_route',
            ['GET', 'POST'],
            'admin',
            'repair_promoted_stats_history',
        ),
        ('/api/admin/move_stats_history', 'move_stats_history_route', ['POST'], 'admin', 'move_stats_history'),
        ('/api/admin/edit_question/<int:q_idx>', 'edit_question_route', ['POST'], 'admin', 'edit_question'),
        ('/api/admin/edit_fetish/<int:fetish_id>', 'edit_fetish_route', ['POST'], 'admin', 'edit_fetish'),
        ('/api/admin/merge_fetishes', 'merge_fetishes_route', ['POST'], 'admin', 'merge_fetishes'),
    )
    for rule, endpoint, methods, access, handler_name in routes:

        def view(_handler_name=handler_name, **url_args):
            return resolve_handler(_handler_name)(ctx_factory(), **url_args)

        view.__name__ = endpoint
        decorator = require_admin if access == 'admin' else require_admin_or_read
        bp.add_url_rule(rule, endpoint, decorator(view), methods=methods)
