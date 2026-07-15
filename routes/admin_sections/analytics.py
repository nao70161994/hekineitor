"""Analytics and reporting route registration for the admin blueprint."""


def register_routes(bp, *, ctx_factory, require_admin, require_admin_or_read, resolve_handler):
    """Register reporting routes while resolving handlers at request time."""

    def add(rule, endpoint, methods, access, handler_name, **fixed_args):
        def view(**url_args):
            handler = resolve_handler(handler_name)
            return handler(ctx_factory(), **url_args, **fixed_args)

        view.__name__ = endpoint
        decorator = require_admin if access == 'admin' else require_admin_or_read
        bp.add_url_rule(rule, endpoint, decorator(view), methods=methods)

    read_routes = (
        ('/api/admin/export_log', 'export_log_route', 'export_log'),
        ('/api/admin/audit_log', 'audit_log_route', 'audit_log'),
        ('/api/admin/fetish_history/<int:fetish_id>', 'fetish_history_route', 'fetish_history'),
        ('/api/admin/fetish_log_rows', 'fetish_log_rows_route', 'fetish_log_rows'),
        ('/api/admin/low_exposure_fetishes', 'low_exposure_fetishes_route', 'low_exposure_fetishes'),
        ('/api/admin/performance', 'performance_route', 'performance'),
        ('/api/admin/recent_fetish_ranking', 'recent_fetish_ranking_route', 'recent_fetish_ranking'),
        ('/api/admin/dry_run_guess', 'dry_run_guess_route', 'dry_run_guess'),
        ('/api/admin/result_exposures', 'result_exposures_route', 'result_exposures_report'),
        ('/api/admin/result_exposures/recent', 'result_exposures_recent_route', 'result_exposures_recent'),
        ('/api/admin/result_exposure_trend', 'result_exposure_trend_route', 'result_exposure_trend'),
        ('/api/admin/result_exposure_factors', 'result_exposure_factors_route', 'result_exposure_factors'),
        ('/api/admin/export_stats_history', 'export_stats_history_route', 'export_stats_history'),
        ('/api/admin/quality_report', 'quality_report_route', 'quality_report'),
        ('/api/admin/share_events', 'share_events_report_route', 'share_events_report'),
        ('/api/admin/question_events', 'question_events_report_route', 'question_events_report'),
        ('/api/admin/question_events/<kind>.csv', 'question_events_csv_route', 'question_events_csv'),
        ('/api/admin/share_events/<kind>.csv', 'share_events_csv_route', 'share_events_csv'),
        ('/api/admin/share_notes', 'get_share_notes_route', 'share_notes'),
        ('/api/admin/read_overview', 'admin_read_overview_route', 'admin_read_overview'),
        ('/api/admin/fetishes_snapshot', 'fetishes_snapshot_route', 'fetishes_snapshot'),
        ('/api/admin/learning_stats', 'learning_stats_route', 'learning_stats'),
        ('/api/admin/question_stats', 'question_stats_route', 'question_stats'),
        ('/api/admin/funnel_metrics', 'funnel_metrics_route', 'funnel_metrics'),
        ('/api/admin/player_fetishes', 'player_fetishes_route', 'player_fetishes'),
        ('/api/admin/added_fetishes', 'added_fetishes_route', 'added_fetishes'),
        ('/api/admin/promoted_fetish_history', 'promoted_fetish_history_route', 'promoted_fetish_history'),
    )
    for rule, endpoint, handler_name in read_routes:
        add(rule, endpoint, ['GET'], 'read', handler_name)

    add(
        '/api/admin/result_exposures/backfill',
        'result_exposures_backfill_preview_route',
        ['GET'],
        'read',
        'result_exposures_backfill',
        apply=False,
    )
    add(
        '/api/admin/result_exposures/backfill',
        'result_exposures_backfill_apply_route',
        ['POST'],
        'admin',
        'result_exposures_backfill',
        apply=True,
    )
    add('/api/admin/fetish_similarity', 'fetish_similarity_route', ['POST'], 'admin', 'fetish_similarity')
    add('/api/admin/share_notes', 'update_share_notes_route', ['POST'], 'admin', 'share_notes')
