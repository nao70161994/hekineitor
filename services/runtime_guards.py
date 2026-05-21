def should_enforce(config, name):
    if name == 'csrf':
        return (not config.get('TESTING')) or config.get('ENFORCE_CSRF')
    if name == 'rate_limit':
        return (not config.get('TESTING')) or config.get('ENFORCE_RATE_LIMIT')
    return not config.get('TESTING')
