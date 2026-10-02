"""Failure recovery at the persistent session-to-history boundary."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'thor_session_outbox_test',
    Path(__file__).parents[1] / 'custom_components/growatt_thor/sessions/outbox.py',
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SessionOutboxTest(unittest.IsolatedAsyncioTestCase):
    def test_restore_ignores_rows_without_valid_identity(self):
        outbox = module.SessionOutbox()
        outbox.restore([None, {}, {"session_id": 1}, {"session_id": ""},
                        {"session_id": "one", "energy_kwh": 2}])
        self.assertEqual(outbox.snapshot(), [{"session_id": "one", "energy_kwh": 2}])
        for row in [{}, {"session_id": 1}, {"session_id": ""}]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                outbox.enqueue(row)

    async def test_restart_after_append_before_acknowledgement(self):
        outbox = module.SessionOutbox()
        outbox.enqueue({'session_id': 'one', 'energy_kwh': 2})
        saved = []
        delivered = {}

        async def save():
            if saved:
                raise OSError('checkpoint unavailable after append')
            saved.append(outbox.snapshot())

        async def append(row):
            delivered.setdefault(row['session_id'], row)

        with self.assertRaises(OSError):
            await outbox.flush(save, append)
        self.assertEqual(len(outbox.snapshot()), 1)
        restored = module.SessionOutbox()
        restored.restore(saved[-1])

        async def save_recovered():
            saved.append(deepcopy(restored.snapshot()))

        await restored.flush(save_recovered, append)
        self.assertEqual(list(delivered), ['one'])
        self.assertEqual(saved[-1], [])

    async def test_failed_checkpoint_never_delivers(self):
        outbox = module.SessionOutbox()
        outbox.enqueue({'session_id': 'one'})
        delivered = []

        async def save():
            raise OSError('disk unavailable')

        async def append(row):
            delivered.append(row)

        with self.assertRaises(OSError):
            await outbox.flush(save, append)
        self.assertEqual(delivered, [])
        self.assertEqual(len(outbox.snapshot()), 1)

    async def test_failed_append_keeps_durable_row(self):
        outbox = module.SessionOutbox()
        outbox.enqueue({'session_id': 'one'})
        saved = []

        async def save():
            saved.append(outbox.snapshot())

        async def append(row):
            raise OSError('history unavailable')

        with self.assertRaises(OSError):
            await outbox.flush(save, append)
        self.assertEqual(saved[-1], outbox.snapshot())
