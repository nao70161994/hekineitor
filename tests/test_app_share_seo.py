# ruff: noqa: F403, F405

from tests._app_test_support import *


class TestShareAndSEO(APITestCase):
    def test_sw_js_served(self):
        res = self.client.get('/sw.js')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'hekineitor', res.data)

    def test_manifest_served(self):
        res = self.client.get('/manifest.json')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'standalone', res.data)

    def test_ads_txt_served(self):
        res = self.client.get('/ads.txt')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'text/plain')
        self.assertIn(b'google.com, pub-8683516545883768, DIRECT, f08c47fec0942fa0', res.data)

    def test_result_share_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with patch.dict(os.environ, {'SHARE_LINKS_PATH': path}):
                res = self.client.get('/r?f=NTR&p=82&d=テスト')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('NTR', body)
        self.assertIn('82', body)
        self.assertIn('あなたの『癖』は……', body)
        self.assertIn('AI精度82%', body)
        self.assertIn('次はあなたの番です……', body)
        self.assertNotIn('称号', body)
        self.assertNotIn('レア度', body)
        self.assertIn('og:url', body)
        self.assertIn('/r?f=NTR&amp;p=82&amp;d=', body)
        self.assertNotRegex(body, r'https?://[^" ]+/r/[0-9A-Za-z]{4,12}')
        self.assertIn('あなたの『癖』は…… NTR', body)
        self.assertIn('/ogp.png?f=NTR&amp;p=82', body)
        self.assertEqual(res.headers.get('X-Robots-Tag'), 'noindex, follow')
        self.assertIn('name="robots" content="noindex,follow"', body)

    def test_legacy_result_share_does_not_create_short_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with patch.dict(os.environ, {'SHARE_LINKS_PATH': path}):
                res = self.client.get('/r?f=NTR&p=82&d=テスト')
                self.assertEqual(res.status_code, 200)
                self.assertFalse(os.path.exists(path))

    def test_share_result_link_round_trip_uses_longer_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with patch.dict(os.environ, {'SHARE_LINKS_PATH': path}):
                created = self.client.post(
                    '/api/share_link',
                    json={
                        'fetish': '感覚遮断落とし穴',
                        'percent': '93',
                        'desc': 'テスト説明',
                    },
                )
                self.assertEqual(created.status_code, 200)
                data = created.get_json()
                self.assertEqual(data['status'], 'ok')
                self.assertRegex(data['share_id'], r'^[0-9A-Za-z]{8}$')
                self.assertEqual(data['share_url'], f'/r/{data["share_id"]}')

                res = self.client.get(data['share_url'])
                self.assertEqual(res.status_code, 200)
                body = res.data.decode('utf-8')
                self.assertIn('感覚遮断落とし穴', body)
                self.assertIn('AI精度93%', body)
                self.assertIn(f'/r/{data["share_id"]}', body)
                self.assertIn(
                    '/ogp.png?f=%E6%84%9F%E8%A6%9A%E9%81%AE%E6%96%AD%E8%90%BD%E3%81%A8%E3%81%97%E7%A9%B4&amp;p=93', body
                )

    def test_legacy_four_character_share_link_still_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with open(path, 'w', encoding='utf-8') as file_obj:
                json.dump(
                    {
                        'Ab12': {
                            'name': '旧リンク結果',
                            'probability': '71',
                            'desc': '旧形式',
                        },
                    },
                    file_obj,
                    ensure_ascii=False,
                )
            with patch.dict(os.environ, {'SHARE_LINKS_PATH': path}):
                res = self.client.get('/r/Ab12')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('旧リンク結果', body)
        self.assertIn('AI精度71%', body)

    def test_result_share_by_id_rate_limit_can_be_enforced(self):
        import app as app_module

        app.config['ENFORCE_RATE_LIMIT'] = True
        app.config['RATE_LIMIT_OVERRIDES'] = {'result_share_by_id': (1, 60)}
        app_module._RATE_LIMIT_BUCKETS.clear()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, 'share_links.json')
                with open(path, 'w', encoding='utf-8') as file_obj:
                    json.dump({'Ab12Cd34': {'name': '共有結果', 'probability': '88'}}, file_obj, ensure_ascii=False)
                with patch.dict(os.environ, {'SHARE_LINKS_PATH': path}):
                    self.assertEqual(self.client.get('/r/Ab12Cd34').status_code, 200)
                    limited = self.client.get('/r/Ab12Cd34')
            self.assertEqual(limited.status_code, 429)
            self.assertIn('Retry-After', limited.headers)
        finally:
            app.config.pop('ENFORCE_RATE_LIMIT', None)
            app.config.pop('RATE_LIMIT_OVERRIDES', None)
            app_module._RATE_LIMIT_BUCKETS.clear()

    def test_share_link_api_rejects_missing_name(self):
        res = self.client.post('/api/share_link', json={'probability': '88'})
        self.assertEqual(res.status_code, 400)

    def test_ogp_png_image(self):
        res = self.client.get('/ogp.png?f=NTR&p=82')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'image/png')
        self.assertTrue(res.data.startswith(b'\x89PNG\r\n\x1a\n'))
        width, height = struct.unpack('>II', res.data[16:24])
        self.assertEqual((width, height), (1200, 630))

    def test_ogp_png_rate_limit_can_be_enforced(self):
        import app as app_module

        app.config['ENFORCE_RATE_LIMIT'] = True
        app.config['RATE_LIMIT_OVERRIDES'] = {'ogp_png': (1, 60)}
        app_module._RATE_LIMIT_BUCKETS.clear()
        try:
            self.assertEqual(self.client.get('/ogp.png?f=NTR&p=82').status_code, 200)
            limited = self.client.get('/ogp.png?f=NTR&p=82')
            self.assertEqual(limited.status_code, 429)
            self.assertIn('Retry-After', limited.headers)
        finally:
            app.config.pop('ENFORCE_RATE_LIMIT', None)
            app.config.pop('RATE_LIMIT_OVERRIDES', None)
            app_module._RATE_LIMIT_BUCKETS.clear()

    def test_ogp_font_path_env_is_preferred(self):
        with patch.dict(os.environ, {'OGP_FONT_PATH': '/tmp/custom-ogp-font.ttf'}):
            self.assertEqual(next(ogp_service._ogp_font_candidates()), '/tmp/custom-ogp-font.ttf')

    def test_ogp_texts_fall_back_to_ascii_when_cjk_font_is_missing(self):
        texts = ogp_service._ogp_texts('眼鏡', '88', cjk_supported=False)
        self.assertEqual(texts['label'], 'Your observed pattern is...')
        self.assertEqual(texts['name'], 'Megane')
        self.assertEqual(texts['prob'], 'AI Precision 88%')
        self.assertEqual(texts['side'], 'Next observation: you.')
        self.assertEqual(texts['mark_sub'], 'LOG')

    def test_ogp_texts_keep_japanese_when_cjk_font_is_available(self):
        texts = ogp_service._ogp_texts('眼鏡', '88', cjk_supported=True)
        self.assertEqual(texts['label'], 'あなたの『癖』は……')
        self.assertEqual(texts['name'], '眼鏡')
        self.assertEqual(texts['prob'], 'AI精度 88%')
        self.assertEqual(texts['mark'], 'AI')
        self.assertEqual(texts['mark_sub'], '観測ログ')

    def test_legacy_svg_ogp_uses_ai_badge_instead_of_question_mark(self):
        svg = ogp_service.render_svg('眼鏡', '88')
        self.assertIn('>あなたの『癖』は……</text>', svg)
        self.assertIn('>AI精度 88%</text>', svg)
        self.assertNotIn('>?</text>', svg)

    def test_result_share_clamps_probability(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_links.json')
            with patch.dict(os.environ, {'SHARE_LINKS_PATH': path}):
                res = self.client.get('/r?f=NTR&p=999&d=テスト')
        body = res.data.decode('utf-8')
        self.assertIn('AI精度100%', body)
        self.assertIn('/ogp.png?f=NTR&amp;p=100', body)
        self.assertIn('/r?f=NTR&amp;p=100&amp;d=', body)

    def test_share_event_api_records_minimal_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                res = self.client.post(
                    '/api/share_event',
                    json={
                        'event_name': 'share_button_click',
                        'result_name': 'NTR（寝取られ）',
                        'channel': 'button',
                        'success': True,
                        'ignored': 'not persisted',
                    },
                )
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json()['recorded'])
            with open(path, encoding='utf-8') as file_obj:
                event = json.loads(file_obj.readline())
        self.assertEqual(set(event), {'timestamp', 'event_name', 'result_name', 'channel', 'success'})
        self.assertEqual(event['event_name'], 'share_button_click')
        self.assertEqual(event['result_name'], 'NTR（寝取られ）')
        self.assertEqual(event['channel'], 'button')
        self.assertTrue(event['success'])
        self.assertNotIn('ip', event)
        self.assertNotIn('user_agent', event)
        self.assertNotIn('session', event)

    def test_share_event_api_records_work_click_without_personal_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                res = self.client.post(
                    '/api/share_event',
                    json={
                        'event_name': 'work_click',
                        'result_name': '白衣',
                        'channel': 'work',
                        'success': True,
                        'work_title': 'おすすめ作品',
                        'work_id': 'wrk_example-1',
                        'edition_id': 'wed_example-1',
                        'page': 'result_works',
                        'url': 'https://example.com/secret',
                    },
                )
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json()['recorded'])
            event = share_events_service.read_events(path=path, limit=10)[0]
        self.assertEqual(event['event_name'], 'work_click')
        self.assertEqual(event['work_title'], 'おすすめ作品')
        self.assertEqual(event['work_id'], 'wrk_example-1')
        self.assertEqual(event['edition_id'], 'wed_example-1')
        self.assertEqual(event['page'], 'result_works')
        self.assertNotIn('url', event)
        self.assertNotIn('ip', event)
        self.assertNotIn('user_agent', event)

    def test_share_event_api_ignores_unknown_result_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                res = self.client.post(
                    '/api/share_event',
                    json={
                        'event_name': 'share_button_click',
                        'result_name': 'health',
                        'channel': 'button',
                        'success': True,
                    },
                )

        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.get_json()['recorded'])
        self.assertFalse(os.path.exists(path))

    def test_share_event_api_ignores_unknown_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            with patch.dict(os.environ, {'SHARE_EVENT_LOG_PATH': path}):
                res = self.client.post('/api/share_event', json={'event_name': 'unknown_event'})
                self.assertEqual(res.status_code, 200)
                self.assertFalse(res.get_json()['recorded'])
                self.assertFalse(os.path.exists(path))

    def test_result_share_and_ogp_views_are_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'share_events.jsonl')
            with patch.dict(
                os.environ, {'SHARE_EVENT_LOG_PATH': path, 'SHARE_LINKS_PATH': os.path.join(tmp, 'share_links.json')}
            ):
                self.client.get('/r?f=白衣&p=82&d=テスト')
                self.client.get('/ogp.png?f=白衣&p=82')
                self.client.get('/ogp?f=白衣&p=82')
                events = share_events_service.read_events(path=path, limit=10)
        names = [event['event_name'] for event in events]
        self.assertIn('result_page_view', names)
        self.assertIn('ogp_png_view', names)
        self.assertIn('ogp_svg_view', names)
        self.assertTrue(all('ip' not in event and 'user_agent' not in event for event in events))

    def test_result_feedback_cta_is_simplified(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('data-action="quick-feedback" data-feedback="yes"', body)
        self.assertIn('data-action="quick-feedback" data-feedback="maybe"', body)
        self.assertIn('data-action="quick-feedback" data-feedback="no"', body)
        self.assertIn('detail-feedback-panel hidden', body)
        self.assertIn('詳細に○△×を付ける', body)

    def test_public_index_links_to_crawlable_pages(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('<link rel="canonical"', body)
        self.assertIn('property="og:url"', body)
        self.assertIn('href="/fetishes"', body)
        self.assertIn('href="/stats"', body)

    def test_fetish_index_page(self):
        res = self.client.get('/fetishes')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('性癖一覧', body)
        self.assertIn('<link rel="canonical"', body)
        self.assertIn('application/ld+json', body)
        self.assertIn('href="/fetish/0"', body)
        self.assertIn('data-href="/fetish/0"', body)
        self.assertIn("event.target.closest('a')", body)
        self.assertIn('id="catalog-search"', body)
        self.assertIn('id="catalog-category"', body)
        self.assertIn('id="catalog-discovery"', body)
        self.assertIn('id="catalog-random"', body)
        self.assertIn('data-category="', body)
        self.assertIn('/static/catalog.js', body)

    def test_fetish_index_links_work_examples_with_affiliate_tag(self):
        from app import BOOTSTRAP
        from app import engine as app_engine

        fid = app_engine.fetishes[0]['id']
        original_provider = app_engine.get_recommended_works
        test_works = [
            {'title': 'ListDirect', 'url': 'https://www.amazon.co.jp/dp/B000000000'},
            'ListSearch',
            {'title': 'UnsafeList', 'url': 'javascript:alert(1)'},
        ]
        original_associate_id = BOOTSTRAP.amazon_associate_id
        try:
            BOOTSTRAP.amazon_associate_id = 'hekinator-22'
            with patch.object(
                app_engine,
                'get_recommended_works',
                side_effect=lambda fetish_id: test_works if fetish_id == fid else original_provider(fetish_id),
            ):
                res = self.client.get('/fetishes')
            self.assertEqual(res.status_code, 200)
            body = res.data.decode('utf-8')
            self.assertIn('href="https://www.amazon.co.jp/dp/B000000000?tag=hekinator-22"', body)
            self.assertIn('href="https://www.amazon.co.jp/s?k=ListSearch&amp;tag=hekinator-22"', body)
            self.assertIn('UnsafeList', body)
            self.assertNotIn('javascript:alert', body)
            self.assertIn('rel="noopener sponsored"', body)
        finally:
            BOOTSTRAP.amazon_associate_id = original_associate_id

    def test_stats_page_has_seo_metadata(self):
        res = self.client.get('/stats')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('<link rel="canonical"', body)
        self.assertIn('property="og:url"', body)
        self.assertIn('name="twitter:card"', body)

    def test_sitemap_indexes_public_content_only(self):
        res = self.client.get('/sitemap.xml')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('/fetishes', body)
        self.assertIn('/stats', body)
        self.assertIn('/fetish/0', body)
        self.assertNotIn('/admin', body)
        self.assertNotIn('/api/', body)
        self.assertNotIn('/offline', body)
        self.assertNotIn('/r</loc>', body)

    def test_robots_points_to_sitemap(self):
        res = self.client.get('/robots.txt')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('Disallow: /admin', body)
        self.assertIn('Disallow: /api/', body)
        self.assertIn('Sitemap:', body)

    def test_site_base_url_controls_canonical_urls(self):
        with patch.dict(os.environ, {'SITE_BASE_URL': 'https://example.test'}, clear=False):
            res = self.client.get('/fetishes')
        body = res.data.decode('utf-8')
        self.assertIn('href="https://example.test/fetishes"', body)

    def test_merge_fetishes_rejects_non_integer_ids(self):
        headers = self._admin_headers()
        res = self.client.post(
            '/api/admin/merge_fetishes', json={'id_keep': 'x', 'id_remove': 0, 'confirm_text': 'MERGE'}, headers=headers
        )
        self.assertEqual(res.status_code, 400)

    def test_fetish_detail_shows_search_fallback_separately_without_works(self):
        from app import BOOTSTRAP
        from app import engine as app_engine

        fid = app_engine.fetishes[0]['id']
        original_associate_id = BOOTSTRAP.amazon_associate_id
        try:
            BOOTSTRAP.amazon_associate_id = 'hekinator-22'
            with patch.object(app_engine, 'get_recommended_works', return_value=[]):
                res = self.client.get(f'/fetish/{fid}')
            self.assertEqual(res.status_code, 200)
            body = res.data.decode('utf-8')
            self.assertNotIn('<h2 class="section-title">おすすめ作品</h2>', body)
            self.assertIn('<h2 class="section-title">関連作品を探す</h2>', body)
            self.assertIn('https://www.amazon.co.jp/s?k=', body)
            self.assertIn('tag=hekinator-22', body)
            self.assertLess(
                body.index('<div class="section-title">この性癖とは</div>'),
                body.index('<h2 class="section-title">関連作品を探す</h2>'),
            )
        finally:
            BOOTSTRAP.amazon_associate_id = original_associate_id

    def test_fetish_detail_drops_unsafe_work_url(self):
        from app import engine as app_engine

        fid = app_engine.fetishes[0]['id']
        with patch.object(
            app_engine,
            'get_recommended_works',
            return_value=[{'title': 'Unsafe', 'url': 'javascript:alert(1)'}],
        ):
            res = self.client.get(f'/fetish/{fid}')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('Unsafe', body)
        self.assertNotIn('javascript:alert', body)
        self.assertNotIn('href=""', body)

    def test_fetish_detail_uses_feedback_accuracy(self):
        from app import engine as app_engine

        fid = app_engine.fetishes[0]['id']
        with patch.object(app_engine, 'get_fetish_log', return_value={fid: {'guessed': 100, 'correct': 1, 'wrong': 3}}):
            res = self.client.get(f'/fetish/{fid}')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn('25%', body)

    def test_fetish_detail_has_seo_content(self):
        from app import engine as app_engine

        fid = app_engine.fetishes[0]['id']
        name = app_engine.fetishes[0]['name']
        res = self.client.get(f'/fetish/{fid}')
        self.assertEqual(res.status_code, 200)
        body = res.data.decode('utf-8')
        self.assertIn(f'{name}とは？性癖診断・おすすめ作品', body)
        self.assertIn('<link rel="canonical"', body)
        self.assertIn('application/ld+json', body)
        self.assertIn('この性癖とは', body)
