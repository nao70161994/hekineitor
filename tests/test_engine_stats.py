import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import engine_stats


class TestEngineStatsHelpers(unittest.TestCase):
    def test_read_json_path_returns_default_for_missing_or_invalid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, 'missing.json')
            invalid = os.path.join(tmp, 'invalid.json')
            with open(invalid, 'w', encoding='utf-8') as f:
                f.write('{bad json')
            self.assertEqual(engine_stats.read_json_path(missing, {'x': 1}), {'x': 1})
            self.assertEqual(engine_stats.read_json_path(invalid, {'x': 1}), {'x': 1})

    def test_increment_and_daily_counter_files_use_atomic_write(self):
        lock = threading.RLock()
        writes = []

        with tempfile.TemporaryDirectory() as tmp:
            stats_path = os.path.join(tmp, 'stats.json')
            history_path = os.path.join(tmp, 'stats_history.json')
            with open(stats_path, 'w', encoding='utf-8') as f:
                json.dump({'play': 2}, f)

            def write(path, data):
                writes.append((path, data))

            engine_stats.increment_counter_file(stats_path, 'play', lock=lock, atomic_write=write)
            engine_stats.record_daily_counter_file(
                history_path, 'learn', '2026-05-23', lock=lock, atomic_write=write
            )

        self.assertEqual(writes[0][1], {'play': 3})
        self.assertEqual(writes[1][1], {'2026-05-23': {'learn': 1}})

    def test_counters_and_history_rows_preserve_engine_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats_path = os.path.join(tmp, 'stats.json')
            history_path = os.path.join(tmp, 'stats_history.json')
            with open(stats_path, 'w', encoding='utf-8') as f:
                json.dump({'play_count': 5}, f)
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump({'2026-05-23': {'start': 4, 'completion': 2, 'play': 2, 'wrong': 1, 'dropoff': 1}}, f)

            self.assertEqual(
                engine_stats.counters_from_file(stats_path, ('play_count', 'learn_count')),
                {'play_count': 5, 'learn_count': 0},
            )
            self.assertEqual(
                engine_stats.history_rows_from_file(history_path, ['2026-05-22', '2026-05-23']),
                [
                    {'date': '2026-05-22', 'start': 0, 'play': 0, 'completion': 0, 'learn': 0, 'correct': 0, 'wrong': 0, 'dropoff': 0},
                    {'date': '2026-05-23', 'start': 4, 'play': 2, 'completion': 2, 'learn': 0, 'correct': 0, 'wrong': 1, 'dropoff': 1},
                ],
            )

    def test_disabled_questions_helpers_sort_on_save(self):
        writes = []
        engine_stats.save_disabled_questions_file(
            '/tmp/question_flags.json',
            {3, 1, 2},
            atomic_write=lambda path, data: writes.append((path, data)),
        )
        self.assertEqual(writes, [('/tmp/question_flags.json', {'disabled': [1, 2, 3]})])

    def test_fetish_log_helpers_preserve_integer_keys_on_read(self):
        lock = threading.RLock()
        writes = []
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'fetish_log.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'10': {'guessed': 1, 'correct': 0, 'wrong': 0}}, f)

            engine_stats.increment_fetish_log_file(
                path, 10, 'correct', lock=lock, atomic_write=lambda p, data: writes.append((p, data))
            )
            self.assertEqual(
                engine_stats.load_fetish_log_file(path),
                {10: {'guessed': 1, 'correct': 0, 'wrong': 0}},
            )

        self.assertEqual(writes[0][1], {'10': {'guessed': 1, 'correct': 1, 'wrong': 0}})
