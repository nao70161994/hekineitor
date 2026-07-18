import copy

from tests._service_test_support import (
    app_meta,
    bootstrap,
    ogp,
    os,
    share,
    tempfile,
    unittest,
    works_links,
)


class TestServiceAppConfig(unittest.TestCase):
    def test_ogp_cjk_font_status_shape_and_android_candidate(self):
        candidates = list(ogp._ogp_font_candidates())
        self.assertIn('/system/fonts/NotoSansCJK-Regular.ttc', candidates)
        self.assertIn('data/fonts/NotoSansCJKjp-Regular.otf', candidates)
        status = ogp.cjk_font_status()
        self.assertIn('available', status)
        self.assertIn('detail', status)

    def test_ogp_bold_font_prefers_downloaded_cjk_before_latin_bold(self):
        candidates = ogp._ordered_ogp_font_candidates(bold=True)
        self.assertLess(
            candidates.index('data/fonts/NotoSansCJKjp-Regular.otf'),
            candidates.index('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        )

    def test_app_version_changes_with_file_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'app.py')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('a')
            first = app_meta.app_version(tmp, paths=('app.py',))
            with open(path, 'w', encoding='utf-8') as f:
                f.write('b')
            second = app_meta.app_version(tmp, paths=('app.py',))
        self.assertNotEqual(first, second)

    def test_work_maintenance_summary_reports_quality_counts(self):
        fetishes = [
            {
                'id': 1,
                'name': 'A',
                'works': [
                    {'title': '重複作品', 'url': 'https://www.amazon.co.jp/dp/B000000000'},
                    {'title': '検索作品', 'url': 'https://www.amazon.co.jp/s?k=x'},
                ],
            },
            {
                'id': 2,
                'name': 'B',
                'works': [
                    {'title': '重複作品', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                    {'title': 'ASINなし', 'url': 'https://www.amazon.co.jp/gp/product/noasin'},
                    'URLなし',
                ],
            },
        ]

        summary = works_links.build_work_maintenance_summary(
            fetishes,
            work_title_fn=lambda work: work.get('title', '') if isinstance(work, dict) else str(work),
            safe_work_url_fn=lambda url: str(url).startswith('https://www.amazon.co.jp/'),
            sample_limit=5,
        )

        self.assertEqual(summary['total_works'], 5)
        self.assertEqual(summary['direct_url_work_count'], 2)
        self.assertEqual(summary['search_url_work_count'], 1)
        self.assertEqual(summary['missing_asin_work_count'], 1)
        self.assertEqual(summary['missing_url_work_count'], 1)
        self.assertEqual(summary['duplicate_work_title_count'], 1)
        self.assertEqual(summary['duplicate_works'][0]['title'], '重複作品')
        self.assertEqual(summary['duplicate_works'][0]['count'], 2)

    def test_work_catalog_report_separates_duplicates_aliases_and_conflicts(self):
        fetishes = [
            {
                'id': 1,
                'name': 'A',
                'works': [
                    {'title': '同一作品', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                    {'title': '同一作品', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                    {'title': '作品（漫画）', 'url': 'https://www.amazon.co.jp/dp/B000000002'},
                ],
            },
            {
                'id': 2,
                'name': 'B',
                'works': [
                    {'title': '同一作品 別表記', 'url': 'https://www.amazon.co.jp/dp/B000000001'},
                    {'title': '作品', 'url': 'https://www.amazon.co.jp/dp/B000000003'},
                ],
            },
        ]
        compound = [
            {
                'key': '1,2',
                'id_a': 1,
                'id_b': 2,
                'works': [{'title': '複合作品', 'url': 'https://www.amazon.co.jp/dp/B000000004'}],
            }
        ]
        original = copy.deepcopy((fetishes, compound))

        report = works_links.build_work_catalog_report(fetishes, compound_rows=compound, sample_limit=10)

        self.assertEqual(report['total_works'], 6)
        self.assertEqual(report['fetish_work_count'], 5)
        self.assertEqual(report['compound_work_count'], 1)
        self.assertEqual(report['within_owner_exact_duplicate_count'], 1)
        self.assertEqual(report['same_asin_alias_count'], 1)
        self.assertEqual(report['normalization_conflict_count'], 1)
        self.assertEqual(report['normalization_conflicts'][0]['asins'], ['B000000002', 'B000000003'])
        self.assertEqual(report['identity_policy'], 'review_only_no_automatic_merge')
        self.assertEqual((fetishes, compound), original)

    def test_app_version_default_includes_pwa_assets(self):
        self.assertIn('static/icon-192.png', app_meta.APP_VERSION_PATHS)
        self.assertIn('static/icon-512.png', app_meta.APP_VERSION_PATHS)
        self.assertIn('templates/sw.js', app_meta.APP_VERSION_PATHS)

    def test_app_version_default_includes_main_client_assets(self):
        expected = (
            'static/app.css',
            'static/app.js',
            'static/game_flow.js',
            'static/share.js',
            'static/feedback.js',
            'static/teach.js',
            'static/events.js',
        )
        for path in expected:
            self.assertIn(path, app_meta.APP_VERSION_PATHS)

    def test_app_bootstrap_canonicalizes_legacy_adsense_client(self):
        config = bootstrap.app_bootstrap(
            base_dir='/app',
            environ={'ADSENSE_CLIENT': 'ca-pub-8835165458837368'},
            app_version_fn=lambda base_dir: 'version',
        )
        self.assertEqual(config.adsense_client, 'ca-pub-8683516545883768')

    def test_app_bootstrap_groups_static_config(self):
        config = bootstrap.app_bootstrap(
            base_dir='/app',
            environ={'AMAZON_ASSOCIATE_ID': 'assoc'},
            app_version_fn=lambda base_dir: 'version',
        )
        self.assertEqual(config.app_version, 'version')
        self.assertEqual(config.display_version, 'v1.9.2')
        self.assertEqual(config.amazon_associate_id, 'assoc')
        self.assertEqual(config.guess_threshold, 0.75)
        self.assertEqual(config.soft_max_questions, 20)
        self.assertEqual(config.hard_max_questions, 30)
        self.assertEqual(config.max_questions, 20)

    def test_secret_key_requires_value_in_production_env(self):
        with open(os.devnull, 'w') as stderr:
            with self.assertRaises(RuntimeError):
                app_meta.secret_key({'APP_ENV': 'production'}, stderr=stderr)

    def test_secret_key_requires_value_with_database_url(self):
        with open(os.devnull, 'w') as stderr:
            with self.assertRaises(RuntimeError):
                app_meta.secret_key({'DATABASE_URL': 'postgres://db'}, stderr=stderr)

    def test_secret_key_uses_dev_fallback_with_warning(self):
        warnings = []
        with open(os.devnull, 'w') as stderr:
            secret = app_meta.secret_key({}, stderr=stderr, warn_fn=lambda *args, **kwargs: warnings.append(args))
        self.assertEqual(secret, app_meta.DEV_SECRET_KEY)
        self.assertEqual(warnings[0][0], app_meta.SECRET_KEY_MISSING_WARNING)

    def test_secret_key_returns_configured_value(self):
        with open(os.devnull, 'w') as stderr:
            secret = app_meta.secret_key({'SECRET_KEY': 'long_enough_secret'}, stderr=stderr)
        self.assertEqual(secret, 'long_enough_secret')

    def test_public_base_url_prefers_configured_site_base_url(self):
        request = type('Request', (), {'host_url': 'http://localhost:5000/'})()
        self.assertEqual(
            share.public_base_url({'SITE_BASE_URL': 'https://example.com/'}, request),
            'https://example.com',
        )
        self.assertEqual(share.public_base_url({}, request), 'http://localhost:5000')
        self.assertEqual(
            share.public_base_url({'APP_ENV': 'production', 'SITE_BASE_URL': 'https://prod.example/'}, request),
            'https://prod.example',
        )
        self.assertIn('SITE_BASE_URL', share.public_base_url.__doc__)

    def test_public_base_url_uses_known_origin_in_production_without_site_base_url(self):
        request = type('Request', (), {'host_url': 'https://untrusted.example/'})()
        self.assertEqual(
            share.public_base_url({'APP_ENV': 'production'}, request),
            'https://hekineitor.onrender.com',
        )
        self.assertEqual(
            share.public_base_url({'RENDER': 'true', 'RENDER_EXTERNAL_URL': 'https://public.example/'}, request),
            'https://public.example',
        )
