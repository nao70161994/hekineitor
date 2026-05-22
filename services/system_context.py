from services import context


def build(
    *,
    engine,
    jsonify,
    response_cls,
    render_template,
    static_folder,
    app_version,
    environ,
    error_counts,
    app_started_at,
    time_fn,
    local_session_count,
    recent_audit,
    use_db,
    get_conn,
    put_conn,
    filesystem,
):
    runtime = context.system_runtime(
        engine=engine,
        jsonify=jsonify,
        Response=response_cls,
        render_template=render_template,
        static_folder=static_folder,
        app_version=app_version,
        environ=environ,
        error_counts=error_counts,
        app_started_at=app_started_at,
        time=time_fn,
        local_session_count=local_session_count,
        recent_audit=recent_audit,
    )
    storage = context.system_storage(
        use_db=use_db,
        get_conn=get_conn,
        put_conn=put_conn,
        data_path=filesystem.data_path,
        app_dir=filesystem.app_dir,
        join_path=filesystem.join_path,
        path_exists=filesystem.path_exists,
        path_getmtime=filesystem.path_getmtime,
    )
    return context.build_system_context(runtime, storage)
