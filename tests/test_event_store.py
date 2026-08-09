import unittest
from datetime import datetime, timezone

from services import event_store


class _Cursor:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((' '.join(statement.split()), params))


class _Connection:
    def __init__(self, cursor=None):
        self.cursor_value = cursor or _Cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def cursor(self):
        return self.cursor_value


class EventStoreRetentionTests(unittest.TestCase):
    def setUp(self):
        event_store._LAST_RETENTION_PRUNE.clear()

    def test_postgres_retention_prunes_once_per_event_type_and_day(self):
        connections = []

        def get_conn():
            connection = _Connection()
            connections.append(connection)
            return connection

        now_fn = lambda: datetime(2026, 8, 9, tzinfo=timezone.utc)
        event = {'timestamp': '2026-08-09T00:00:00+00:00', 'event_name': 'diagnosis_summary'}
        for _ in range(2):
            event_store.record_event(
                'gameplay',
                event,
                retention_days=90,
                now_fn=now_fn,
                get_conn_fn=get_conn,
                put_conn_fn=lambda _connection: None,
            )

        deletes = [
            call
            for connection in connections
            for call in connection.cursor_value.calls
            if call[0].startswith('DELETE FROM analytics_events')
        ]
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0][1], ('gameplay', '2026-05-11T00:00:00+00:00'))
        self.assertTrue(
            any('idx_analytics_events_type_timestamp' in call[0] for call in connections[0].cursor_value.calls)
        )

    def test_failed_prune_is_retried_instead_of_marked_complete(self):
        class FailingCursor(_Cursor):
            def execute(self, statement, params=None):
                super().execute(statement, params)
                if statement.lstrip().startswith('DELETE'):
                    raise RuntimeError('delete failed')

        returned = []
        with self.assertRaisesRegex(RuntimeError, 'delete failed'):
            event_store.record_event(
                'gameplay',
                {'timestamp': '2026-08-09T00:00:00+00:00'},
                retention_days=90,
                now_fn=lambda: datetime(2026, 8, 9, tzinfo=timezone.utc),
                get_conn_fn=lambda: _Connection(FailingCursor()),
                put_conn_fn=returned.append,
            )

        self.assertNotIn('gameplay', event_store._LAST_RETENTION_PRUNE)
        self.assertEqual(len(returned), 1)


if __name__ == '__main__':
    unittest.main()
