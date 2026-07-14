from services import admin_security, rate_limit as rate_limit_service, runtime_guards


class FlaskRuntime:
    def __init__(
        self,
        *,
        request,
        session,
        response_cls,
        jsonify,
        app_config,
        environ,
        buckets,
        time_fn,
        use_db=lambda: False,
        get_conn=None,
        put_conn=None,
        shared_rate_limit_path=None,
        logger=None,
    ):
        self.request = request
        self.session = session
        self.response_cls = response_cls
        self.jsonify = jsonify
        self.app_config = app_config
        self.environ = environ
        self.buckets = buckets
        self.time_fn = time_fn
        self.use_db = use_db
        self.get_conn = get_conn
        self.put_conn = put_conn
        self.shared_rate_limit_path = shared_rate_limit_path
        self.logger = logger

    def should_enforce_runtime_guard(self, name):
        return runtime_guards.should_enforce(self.app_config, name)

    def rate_limit(self, scope, limit, window_seconds=60):
        return rate_limit_service.rate_limit(
            scope,
            limit,
            self.request,
            self.app_config,
            self.buckets,
            self.jsonify,
            self.should_enforce_runtime_guard,
            window_seconds=window_seconds,
            environ=self.environ,
            time_fn=self.time_fn,
            use_db=self.use_db,
            get_conn=self.get_conn,
            put_conn=self.put_conn,
            shared_path=self.shared_rate_limit_path,
            logger=self.logger,
        )

    def require_confirm(self, expected):
        return admin_security.require_confirm(self.request, self.jsonify, expected)

    def csrf_token(self):
        return admin_security.csrf_token(self.session, self.environ, now_fn=self.time_fn)

    def admin_read_guard_response(self):
        return admin_security.read_token_guard_response(
            self.request,
            self.environ,
            self.response_cls,
            self.rate_limit,
        )

    def admin_guard_response(self):
        return admin_security.admin_guard_response(
            self.request,
            self.environ,
            self.session,
            self.response_cls,
            self.jsonify,
            self.rate_limit,
            self.should_enforce_runtime_guard,
        )


def flask_runtime(**kwargs):
    return FlaskRuntime(**kwargs)


require_admin_decorator = admin_security.require_admin_decorator
require_admin_or_read_decorator = admin_security.require_admin_or_read_decorator
