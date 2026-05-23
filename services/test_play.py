SESSION_KEY = 'heki_test_play_learning_disabled'


def enable(session):
    session[SESSION_KEY] = True


def disable(session):
    session.pop(SESSION_KEY, None)


def is_learning_disabled(session):
    return bool(session.get(SESSION_KEY))


def preserve_flag(session):
    return is_learning_disabled(session)


def restore_flag(session, enabled):
    if enabled:
        enable(session)
