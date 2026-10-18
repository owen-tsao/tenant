"""A bounded, one-device blink derived from acknowledged boolean light edges."""
import asyncio
import copy
import io
import json
import unittest
from unittest.mock import patch

from agent.tenant_device import invoke, main
from brain.core.bus import Bus
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.core.native_devices import NativeDevices
from brain.core.registry import Registry
from brain.state import Room
from test_native_devices import device
from test_room_conversation import Clock


class BlinkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = Registry(Room('TEST', 'Test'))
        self.bus, self.clock = Bus(self.registry), Clock()
        self.leases = Leases(self.registry.room, clock=self.clock)
        self.lease = self.leases.create()
        self.leases.current(self.lease.guest_id, activate=True)
        self.active = True
        self.tools = NativeDevices(self.registry, self.bus, self.leases, EventLog(),
                                   lambda _: self.active, action_timeout=.03)
        self.phone = device(self.registry, self.bus)
        self.grant = await self.tools.prepare(self.lease.guest_id, 1, self.lease, 'thread')
        self.tools.activate(self.grant, 'turn')
        self.intervals = []
        async def fake_sleep(interval):
            self.intervals.append(interval)
            await asyncio.sleep(0)
        self.tools._blink_sleep = fake_sleep
    async def asyncTearDown(self):
        await self.tools.close()
    def request(self, **changes):
        return {'token': self.grant.token, 'operation': 'light-blink', 'request_id': 'blink-1',
                'device_id': 'phone', **changes}
    async def new_grant(self):
        self.tools.finish(self.grant)
        self.grant = await self.tools.prepare(self.lease.guest_id, 1, self.lease, 'thread')
        self.tools.activate(self.grant, 'turn')

    async def test_default_three_cycles_is_six_acknowledged_edges_ending_off(self):
        result = await asyncio.to_thread(invoke, self.grant.path, 'light-blink',
                                         {'request_id': 'blink-1', 'device_id': 'phone'})
        self.assertTrue(result['ok'])
        self.assertEqual([f['args']['on'] for f in self.phone.frames], [True, False] * 3)
        self.assertEqual(self.intervals, [.5] * 5)
        self.assertEqual(result['result'], {'count': 3, 'cycles_completed': 3, 'edges_confirmed': 6,
                                          'edges_dispatched': 6, 'edges_acknowledged': 6,
                                          'on': False, 'final_off_confirmed': True, 'operation_complete': True})
        rows = [row['audit'] for row in self.tools.log.audit_rows if row.get('audit', {}).get('req')]
        self.assertEqual([row['req'] for row in rows], [f['req'] for f in self.phone.frames])
        self.assertEqual({row['turn_id'] for row in rows}, {'turn'})

    async def test_count_bounds_default_and_inventory_are_truthful(self):
        inventory = await self.tools.dispatch({'token': self.grant.token, 'operation': 'inventory'})
        operation = inventory['devices'][0]['derived_operations'][0]
        self.assertEqual(operation['name'], 'light-blink')
        self.assertEqual(operation['args']['count'], {'type': 'integer', 'minimum': 1, 'default': 3})
        self.assertEqual(operation['interval_ms'], 500)
        self.assertEqual(operation['bounded_by'], 'current_turn_and_lease')
        for count in (0, -1, True, 1.5, '3', None):
            with self.subTest(count=count):
                await self.new_grant()
                result = await self.tools.dispatch(self.request(count=count))
                self.assertEqual(result['code'], 'INVALID')
                self.assertEqual(self.phone.frames, [])
        for count in (1, 2, 3, 10):
            with self.subTest(valid=count):
                await self.new_grant()
                before = len(self.phone.frames)
                result = await self.tools.dispatch(self.request(count=count))
                self.assertTrue(result['ok'])
                self.assertEqual(len(self.phone.frames) - before, count * 2)

    async def test_duplicate_never_replays_but_distinct_requested_operations_are_allowed(self):
        original = await self.tools.dispatch(self.request())
        self.assertEqual(await self.tools.dispatch(self.request(count=3)), original)
        self.assertEqual((await self.tools.dispatch(self.request(count=3.0)))['code'], 'INVALID')
        self.assertEqual((await self.tools.dispatch(self.request(count=2)))['code'], 'INVALID')
        ordinary = {'token': self.grant.token, 'operation': 'call', 'request_id': 'extra',
                    'device_id': 'phone', 'cap': 'light', 'args': {'on': True}}
        self.assertTrue((await self.tools.dispatch(ordinary))['ok'])
        self.assertEqual(len(self.phone.frames), 7)

    async def test_concurrent_duplicate_waits_for_same_recorded_sequence(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def paused(_interval):
            entered.set()
            await release.wait()
        self.tools._blink_sleep = paused
        first = asyncio.create_task(self.tools.dispatch(self.request(count=1)))
        await entered.wait()
        duplicate = asyncio.create_task(self.tools.dispatch(self.request(count=1)))
        release.set()
        self.assertEqual(await first, await duplicate)
        self.assertEqual([f['args']['on'] for f in self.phone.frames], [True, False])

    async def test_distinct_blinks_on_one_phone_produce_two_serial_real_cycles(self):
        entered, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class ObservedLock(asyncio.Lock):
            async def acquire(self):
                if self.locked(): queued.set()
                return await super().acquire()
        self.tools.device_locks['phone'] = ObservedLock()
        async def first_on_interval(_interval):
            if not entered.is_set():
                entered.set()
                await release.wait()
        self.tools._blink_sleep = first_on_interval
        async with asyncio.timeout(.2):
            first = asyncio.create_task(self.tools.dispatch(self.request(count=1)))
            await entered.wait()
            second = asyncio.create_task(self.tools.dispatch(self.request(request_id='blink-2', count=1)))
            await queued.wait()
            self.assertEqual([f['args']['on'] for f in self.phone.frames], [True])
            release.set()
            self.assertTrue((await first)['ok'])
            self.assertTrue((await second)['ok'])
        self.assertEqual([f['args']['on'] for f in self.phone.frames], [True, False, True, False])

    async def test_unknown_on_or_off_halts_and_never_claims_final_off_or_substitutes(self):
        for failed_edge in (0, 1):
            with self.subTest(edge=failed_edge):
                await self.new_grant()
                self.phone.frames.clear()
                original_send = self.phone.send_json
                async def selective_ack(frame):
                    if len(self.phone.frames) == failed_edge:
                        self.phone.frames.append(frame)
                        self.phone.sent.set()
                    else:
                        await original_send(frame)
                self.phone.send_json = selective_ack
                result = await self.tools.dispatch(self.request())
                self.assertEqual(result['code'], 'UNKNOWN')
                self.assertFalse(result['result']['final_off_confirmed'])
                self.assertEqual(len(self.phone.frames), failed_edge + 1)
                self.assertEqual(await self.tools.dispatch(self.request()), result)
                self.assertEqual(len(self.phone.frames), failed_edge + 1)
                self.phone.send_json = original_send
                self.bus.uncertain.clear()  # New independent fake trial only.

    async def test_wrong_state_ack_stops_instead_of_inventing_success(self):
        async def wrong_state(frame):
            self.phone.frames.append(frame)
            self.bus.receive(self.phone.device, {'type': 'ok', 'req': frame['req'], 'result': {'on': False}})
        self.phone.send_json = wrong_state
        result = await self.tools.dispatch(self.request())
        self.assertEqual(result['code'], 'UNKNOWN')
        self.assertTrue(result['result']['final_off_confirmed'])  # The actual mismatched ACK said OFF.
        self.assertFalse(result['result']['operation_complete'])
        self.assertEqual(len(self.phone.frames), 1)

    async def test_ending_access_during_on_interval_sends_no_more_edges(self):
        for change in ('revoke', 'expiry', 'new_controller', 'native_end', 'disconnect', 'scope', 'reset'):
            with self.subTest(change=change):
                self.active = True
                self.lease = self.leases.create()
                self.leases.current(self.lease.guest_id, activate=True)
                await self.new_grant()
                self.phone.frames.clear()
                self.phone.device.online = True
                async def change_during_sleep(_interval):
                    if change == 'revoke': self.leases.revoke(self.lease.guest_id)
                    elif change == 'expiry': self.clock.now = self.lease.expires_at
                    elif change in ('new_controller', 'native_end'): self.active = False
                    elif change == 'disconnect': self.bus.disconnect(self.phone.device)
                    elif change == 'scope': self.lease.scopes.clear()
                    else: self.leases.reset()
                self.tools._blink_sleep = change_during_sleep
                result = await self.tools.dispatch(self.request())
                self.assertFalse(result['ok'])
                self.assertFalse(result['result']['final_off_confirmed'])
                self.assertEqual([f['args']['on'] for f in self.phone.frames], [True])

    async def test_access_ending_while_next_on_waits_in_bus_queue_sends_no_later_on(self):
        lock = self.bus.locks['phone']
        queued = asyncio.Event()
        sleeps = 0
        async def queue_before_second_on(_interval):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2:
                await lock.acquire()
                queued.set()
        self.tools._blink_sleep = queue_before_second_on
        pending = asyncio.create_task(self.tools.dispatch(self.request()))
        await queued.wait()
        await asyncio.sleep(0)
        self.leases.revoke(self.lease.guest_id)
        lock.release()
        result = await pending
        self.assertEqual(result['code'], 'PERMISSION')
        self.assertEqual([f['args']['on'] for f in self.phone.frames], [True, False])
        self.assertTrue(result['result']['final_off_confirmed'])
        self.assertFalse(result['result']['operation_complete'])

    async def test_reconnected_original_id_never_receives_remaining_edges(self):
        replacement = None
        async def replace_connection(_interval):
            nonlocal replacement
            self.bus.disconnect(self.phone.device)
            replacement = device(self.registry, self.bus)
        self.tools._blink_sleep = replace_connection
        result = await self.tools.dispatch(self.request())
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.phone.frames), 1)
        self.assertEqual(replacement.frames, [])

    async def test_one_total_deadline_covers_sleeps_and_caches_unknown(self):
        entered = asyncio.Event()
        async def never_wakes(_interval):
            entered.set()
            await asyncio.Event().wait()
        self.tools._blink_sleep = never_wakes
        self.grant.deadline = asyncio.get_running_loop().time() + .02
        async with asyncio.timeout(.2):
            result = await self.tools.dispatch(self.request())
        self.assertTrue(entered.is_set())
        self.assertEqual(result['code'], 'TIMEOUT')
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['result']['final_off_confirmed'])
        self.assertEqual(len(self.phone.frames), 1)
        self.assertEqual((await self.tools.dispatch(self.request()))['code'], 'PERMISSION')
        self.assertEqual(len(self.phone.frames), 1)

    async def test_one_total_deadline_bounds_a_bus_queue_and_inflight_wait(self):
        for sent in (False, True):
            with self.subTest(sent=sent):
                await self.new_grant()
                self.phone.frames.clear()
                self.phone.auto = False
                lock = self.bus.locks['phone']
                if not sent: await lock.acquire()
                try:
                    self.grant.deadline = asyncio.get_running_loop().time() + .02
                    async with asyncio.timeout(.2):
                        result = await self.tools.dispatch(self.request())
                finally:
                    if lock.locked(): lock.release()
                self.assertFalse(result['ok'])
                self.assertFalse(result['result']['final_off_confirmed'])
                self.assertEqual(result['status'], 'unknown' if sent else 'unsent')
                self.assertEqual(result['code'], 'UNKNOWN' if sent else 'TIMEOUT')
                self.assertEqual(result['result']['edges_dispatched'], int(sent))
                self.assertEqual(len(self.phone.frames), int(sent))
                self.assertEqual(self.bus.pending, {})
                self.bus.uncertain.clear()

    async def test_client_disconnect_cancels_sleep_and_never_continues_sequence(self):
        entered, settled = asyncio.Event(), asyncio.Event()
        async def waiting(_interval):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                settled.set()
        self.tools._blink_sleep = waiting
        reader, writer = await asyncio.open_unix_connection(self.grant.path.parent / 'bus.sock')
        writer.write(json.dumps(self.request()).encode() + b'\n')
        await writer.drain()
        await entered.wait()
        writer.close()
        await writer.wait_closed()
        async with asyncio.timeout(.2):
            await settled.wait()
            while self.tools._clients:
                await asyncio.sleep(0)
        cached = await self.tools.dispatch(self.request())
        self.assertEqual(cached['code'], 'CANCELLED')
        self.assertEqual(cached['status'], 'partial')
        self.assertEqual([f['args']['on'] for f in self.phone.frames], [True])

    async def test_client_cancel_while_next_on_is_bus_queued_keeps_confirmed_off_receipt(self):
        lock, queued = self.bus.locks['phone'], asyncio.Event()
        sleeps = 0
        async def hold_before_second_on(_interval):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2: await lock.acquire()
        original = self.bus.call
        async def mark_queue(*args, **kwargs):
            if len(self.phone.frames) == 2: queued.set()
            return await original(*args, **kwargs)
        self.tools._blink_sleep = hold_before_second_on
        self.bus.call = mark_queue
        reader, writer = await asyncio.open_unix_connection(self.grant.path.parent / 'bus.sock')
        try:
            writer.write(json.dumps(self.request()).encode() + b'\n')
            await writer.drain()
            async with asyncio.timeout(.2):
                await queued.wait()
                writer.close()
                await writer.wait_closed()
                receipt = await asyncio.shield(self.grant.calls['blink-1'][1])
            self.assertEqual(receipt['code'], 'CANCELLED')
            self.assertTrue(receipt['result']['final_off_confirmed'])
            self.assertFalse(receipt['result']['operation_complete'])
            self.assertEqual(receipt['result']['edges_dispatched'], 2)
        finally:
            if lock.locked(): lock.release()
            writer.close()
            await writer.wait_closed()
        self.assertEqual([f['args']['on'] for f in self.phone.frames], [True, False])

    async def test_cli_exposes_only_the_narrow_blink_payload(self):
        with patch('agent.tenant_device.invoke', return_value={'ok': True, 'result': {'on': False}}) as call:
            with patch('sys.stdin', io.StringIO('{"request_id":"one","device_id":"phone","count":3}')):
                with patch('sys.stdout', new_callable=io.StringIO):
                    self.assertEqual(main(['--context', str(self.grant.path), 'light-blink']), 0)
            self.assertEqual(call.call_args.args[1], 'light-blink')
        with patch('agent.tenant_device.invoke') as call:
            with patch('sys.stdin', io.StringIO('{"request_id":"one","device_id":"phone","count":3,"interval":0.01}')):
                with patch('sys.stdout', new_callable=io.StringIO):
                    self.assertEqual(main(['--context', str(self.grant.path), 'light-blink']), 1)
            call.assert_not_called()


if __name__ == '__main__': unittest.main()
