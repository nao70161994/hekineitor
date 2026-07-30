"""Works and compound-works administration route registration."""


def register_routes(
    bp,
    *,
    ctx_factory,
    require_admin,
    require_admin_or_read,
    list_compound_works,
    set_compound_works,
    delete_compound_works,
    works_review,
    work_catalog_admin,
    mutate_work_catalog_admin,
    works_link_queue_payload,
):
    """Register works administration routes on ``bp``."""

    @bp.route('/api/admin/compound_works', methods=['GET'])
    @require_admin_or_read
    def list_compound_works_route():
        return list_compound_works(ctx_factory())

    @bp.route('/api/admin/compound_works', methods=['POST'])
    @require_admin
    def set_compound_works_route():
        return set_compound_works(ctx_factory())

    @bp.route('/api/admin/compound_works/<path:key>', methods=['DELETE'])
    @require_admin
    def delete_compound_works_route(key):
        return delete_compound_works(ctx_factory(), key)

    @bp.route('/api/admin/works_review', methods=['GET'])
    @require_admin_or_read
    def works_review_route():
        return works_review(ctx_factory())

    @bp.route('/api/admin/work_catalog', methods=['GET'])
    @require_admin_or_read
    def work_catalog_admin_route():
        return work_catalog_admin(ctx_factory())

    @bp.route('/api/admin/work_catalog/mutate', methods=['POST'])
    @require_admin
    def mutate_work_catalog_admin_route():
        return mutate_work_catalog_admin(ctx_factory())

    @bp.route('/api/admin/works_link_queue', methods=['GET'])
    @require_admin_or_read
    def works_link_queue_route():
        ctx = ctx_factory()
        try:
            sample_limit = max(1, min(int(ctx.request.args.get('sample_limit', 20)), 100))
        except ValueError:
            sample_limit = 20
        return ctx.jsonify(works_link_queue_payload(ctx, sample_limit=sample_limit))
