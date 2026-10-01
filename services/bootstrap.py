class AppBootstrap:
    @staticmethod
    def _adsense_slot(environ, key):
        value = str(environ.get(key, '') or '').strip()
        if not value.isdigit() or value == '0000000000':
            return ''
        return value

    @staticmethod
    def _to_publisher_id(raw_adsense_client):
        adsense_client = (raw_adsense_client or '').strip()
        if adsense_client.startswith('ca-pub-'):
            return 'pub-' + adsense_client[len('ca-pub-') :]
        return adsense_client

    def __init__(
        self,
        *,
        base_dir,
        environ,
        app_version_fn,
        display_version='v1.9.2',
        guess_threshold=0.75,
        soft_max_questions=20,
        hard_max_questions=30,
    ):
        self.base_dir = base_dir
        self.app_version = app_version_fn(base_dir)
        self.display_version = display_version
        self.amazon_associate_id = environ.get('AMAZON_ASSOCIATE_ID', '')
        raw_adsense_client = environ.get('ADSENSE_CLIENT', '').strip()
        self.adsense_client = raw_adsense_client
        self.adsense_publisher_id = self._to_publisher_id(raw_adsense_client)
        self.adsense_slots = {
            'home': self._adsense_slot(environ, 'ADSENSE_SLOT_HOME'),
            'result': self._adsense_slot(environ, 'ADSENSE_SLOT_RESULT'),
            'share': self._adsense_slot(environ, 'ADSENSE_SLOT_SHARE'),
        }
        self.guess_threshold = guess_threshold
        self.soft_max_questions = soft_max_questions
        self.hard_max_questions = hard_max_questions
        self.max_questions = soft_max_questions


def app_bootstrap(**kwargs):
    return AppBootstrap(**kwargs)
