"""Matrix import/export and backup route registration."""


def register_routes(
    bp,
    *,
    ctx_factory,
    require_admin,
    require_admin_or_read,
    export_matrix,
    import_matrix,
    import_matrix_dry_run,
    matrix_backups,
    restore_matrix_backup,
):
    """Register matrix administration routes on ``bp``.

    Handlers are injected by :mod:`routes.admin` so their existing public import
    and patch locations remain stable while route registration is split by
    feature.
    """

    @bp.route('/api/admin/export_matrix', methods=['GET'])
    @require_admin
    def export_matrix_route():
        return export_matrix(ctx_factory())

    @bp.route('/api/admin/import_matrix', methods=['POST'])
    @require_admin
    def import_matrix_route():
        return import_matrix(ctx_factory())

    @bp.route('/api/admin/import_matrix/dry_run', methods=['POST'])
    @require_admin
    def import_matrix_dry_run_route():
        return import_matrix_dry_run(ctx_factory())

    @bp.route('/api/admin/matrix_backups', methods=['GET'])
    @require_admin_or_read
    def matrix_backups_route():
        return matrix_backups(ctx_factory())

    @bp.route('/api/admin/matrix_backups/<path:name>/restore', methods=['POST'])
    @require_admin
    def restore_matrix_backup_route(name):
        return restore_matrix_backup(ctx_factory(), name)
