"""Dispatch observations mark possible sends, never physical acknowledgments."""
import asyncio
import unittest
from brain.core.bus import Bus
from brain.core.registry import Registry
from brain.state import Room
from test_native_devices import device


class DispatchObservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = Registry(Room('TEST', 'Test'))
        self.bus = Bus(self.registry)
        self.phone = device(self.registry, self.bus)

    async def test_observer_follows_permission_and_cannot_break_bus_with_an_exception(self):
        observed = []
        denied = await self.bus.call('phone', 'light', {'on': True}, authorize=lambda *_: False,
                                     on_dispatch=lambda *args: observed.append(args))
        self.assertEqual(denied.code, 'PERMISSION')
        self.assertEqual(observed, [])
        self.assertEqual(self.phone.frames, [])
        def broken_observer(req, dev):
            observed.append((req, dev))
            raise RuntimeError('An observer does not grant or revoke Bus authority')
        result = await self.bus.call('phone', 'light', {'on': True}, authorize=lambda *_: True,
                                     on_dispatch=broken_observer)
        self.assertTrue(result.ok)
        self.assertEqual(observed, [(result.req, self.phone.device)])
        self.assertEqual(self.bus.pending, {})

    async def test_cancel_at_send_boundary_is_possible_send_not_acknowledged_success(self):
        observed, entered = [], asyncio.Event()
        async def blocked_send(frame):
            self.phone.frames.append(frame)
            entered.set()
            await asyncio.Event().wait()
        self.phone.send_json = blocked_send
        pending = asyncio.create_task(self.bus.call('phone', 'light', {'on': True}, authorize=lambda *_: True,
            on_dispatch=lambda req, dev: observed.append((req, dev))))
        await entered.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(observed, [(self.phone.frames[0]['req'], self.phone.device)])
        self.assertEqual(self.bus.uncertain, {observed[0][0]: self.phone.device})
        self.assertEqual(self.bus.pending, {})
        self.assertFalse(self.phone.device.busy)

    async def test_queue_deadline_has_no_dispatch_observation(self):
        observed = []
        lock = self.bus.locks['phone']
        await lock.acquire()
        try:
            result = await self.bus.call('phone', 'light', {'on': True}, timeout=.02,
                authorize=lambda *_: True, on_dispatch=lambda *args: observed.append(args))
        finally:
            lock.release()
        self.assertEqual(result.code, 'TIMEOUT')
        self.assertEqual(observed, [])
        self.assertEqual(self.phone.frames, [])


if __name__ == '__main__': unittest.main()
