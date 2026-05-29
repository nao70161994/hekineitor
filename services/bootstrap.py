class AppBootstrap:
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
        raw_adsense_client = environ.get('ADSENSE_CLIENT', '')
        # AdSense publish IDs may remain on legacy config; canonicalize to current approved ID.
        if raw_adsense_client == 'ca-pub-8835165458837368':
            raw_adsense_client = 'ca-pub-8683516545883768'
        self.adsense_client = raw_adsense_client
        self.guess_threshold = guess_threshold
        self.soft_max_questions = soft_max_questions
        self.hard_max_questions = hard_max_questions
        self.max_questions = soft_max_questions


def app_bootstrap(**kwargs):
    return AppBootstrap(**kwargs)
