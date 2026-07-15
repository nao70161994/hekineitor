"""Admin page and test-play route registration."""


def register_routes(bp, *, ctx_factory, require_admin, resolve_handler):
    """Register the admin page and test-play controls on ``bp``."""

    routes = (
        ('/admin', 'admin_page_route', ['GET'], 'admin_page'),
        ('/admin/test_play/start', 'start_test_play_route', ['POST'], 'start_test_play'),
        ('/admin/test_play/stop', 'stop_test_play_route', ['POST'], 'stop_test_play'),
    )
    for rule, endpoint, methods, handler_name in routes:

        def view(_handler_name=handler_name):
            return resolve_handler(_handler_name)(ctx_factory())

        view.__name__ = endpoint
        bp.add_url_rule(rule, endpoint, require_admin(view), methods=methods)
