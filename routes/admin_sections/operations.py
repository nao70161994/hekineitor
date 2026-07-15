"""Operational health and maintenance route registration."""


def register_routes(bp, *, ctx_factory, require_admin_or_read, resolve_handler):
    """Register read-only operational endpoints on ``bp``."""

    routes = (
        ('/api/admin/preflight', 'preflight_route', 'preflight'),
        ('/api/admin/operations_snapshot', 'operations_snapshot_route', 'operations_snapshot'),
        ('/api/admin/works_health', 'works_health_route', 'works_health'),
        ('/api/admin/matrix_health', 'matrix_health_route', 'matrix_health'),
        ('/api/admin/maintenance_checklist', 'maintenance_checklist_route', 'maintenance_checklist'),
    )
    for rule, endpoint, handler_name in routes:

        def view(_handler_name=handler_name):
            return resolve_handler(_handler_name)(ctx_factory())

        view.__name__ = endpoint
        bp.add_url_rule(rule, endpoint, require_admin_or_read(view), methods=['GET'])
