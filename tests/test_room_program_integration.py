"""Real helper/Core/program composition, with fake native turns and bridges only."""
import asyncio
import copy
from dataclasses import replace
import io
import json
import unittest
from unittest.mock import patch

from agent.beat_audio import capabilities
from agent.room_session import MAX_APPLICATION_CONTEXT
from agent.tenant_device import invoke, main
from brain.config import Config
from brain.main import create_app
from brain.state import CapSpec
from test_room_conversation import Clock, NativeSession, settings_for
from test_room_programs import Socket


class ProgramIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.native, self.clock = NativeSession(), Clock()
        self.native.auto_finish = False
        self.app = create_app(Config('device-private', 'host-private', 'TEST', 'https://tenant.test'),
                              conversation=settings_for(self.native))
        self.core, self.agent = self.app.state.core, self.app.state.core.agent
        self.core.leases.clock = self.clock
        self.lease = self.core.leases.create()
        self.audio = self.register('laptop', {**capabilities(),
            'music.play': {'description': 'Prepared music', 'args': {}}})
        self.phone = self.register('phone', {'light': {'description': 'Light', 'args': {'on': {'type': 'boolean'}}}})
        self.assertEqual(self.agent.programs.audio_queue_timeout,
                         self.agent.settings.cleanup_timeout + self.agent.device_tools.action_timeout)
        self.agent.programs.action_timeout = .03
        self.agent.programs.audio_queue_timeout = self.agent.settings.cleanup_timeout + .03
        self.agent.device_tools.action_timeout = .03
        self.agent.device_tools.speech_timeout = .03
        self.assertEqual(self.core.speech.timeout, self.agent.settings.cleanup_timeout)
        self.assertGreater(self.agent.program_cleanup_timeout(), self.agent.programs.audio_queue_timeout)
        self.turn = None
    async def asyncTearDown(self):
        if self.turn is not None and not self.turn.done():
            self.turn.cancel()
            await asyncio.gather(self.turn, return_exceptions=True)
        await self.agent.close()

    def register(self, name, caps):
        socket = Socket(self.core.bus)
        socket.device = self.core.registry.register({'type': 'hello', 'id': name, 'label': name,
            'room': 'TEST', 'caps': caps}, socket)
        return socket

    async def begin(self, text='Start a beat.', *, lease=None):
        self.native.started.clear()
        self.turn = asyncio.create_task(self.agent.turn((lease or self.lease).guest_id, text))
        await self.native.started.wait()
        self.grant = next(iter(self.agent.device_tools._grants.values()))
        self.assertLessEqual(len(self.native.application_contexts[-1]), MAX_APPLICATION_CONTEXT)
        return self.grant

    async def finish(self, text='The requested result is recorded.'):
        await self.native.finish(self.native.active_turn_id, text)
        result = await self.turn
        self.turn = None
        return result

    async def call(self, operation, request_id, **payload):
        return await asyncio.to_thread(invoke, self.grant.path, operation, {'request_id': request_id, **payload})

    async def start(self, *, bpm=600):
        await self.begin()
        result = await self.call('program-start', 'start', device_id='laptop', bpm=bpm)
        self.assertTrue(result['ok'], result)
        return self.agent.programs.programs[result['result']['program_id']]

    async def attach(self, program, *, light_beats_per_state=None):
        cadence = {} if light_beats_per_state is None else {'light_beats_per_state': light_beats_per_state}
        result = await self.call('program-update', 'attach', program_id=program.id, light_device_id='phone', **cadence)
        self.assertTrue(result['ok'], result)
        return result

    async def test_one_chat_starts_replies_then_later_turn_attaches_and_stops_same_program(self):
        program = await self.start()
        old_grant = self.grant
        first = await self.finish('The beat is running.')
        self.assertEqual(first[-1]['text'], 'The beat is running.')
        self.assertTrue(old_grant.closed)
        self.assertTrue(program.active)
        self.assertTrue(self.agent.allows_program(self.lease, program.owner.generation))
        self.assertFalse(self.agent.allows_program(copy.copy(self.lease), program.owner.generation))
        await self.begin('Now add my phone to that beat.')
        inventory = await asyncio.to_thread(invoke, self.grant.path, 'inventory')
        self.assertEqual(inventory['programs']['programs'][0]['program_id'], program.id)
        self.assertTrue(inventory['programs']['audio_devices'][0]['generated_beat'])
        self.assertNotIn('beat.start', [cap['name'] for cap in inventory['devices'][0]['caps']])
        await self.attach(program)
        frames = [await asyncio.wait_for(self.phone.events.get(), 1) for _ in range(2)]
        self.assertEqual([frame['args']['on'] for frame in frames], [True, False])
        status = await self.call('program-status', 'status', program_id=program.id)
        self.assertFalse(status['result']['physical_sync_measured'])
        self.assertEqual(sum(frame['cap'] == 'beat.start' for frame in self.audio.frames), 1)
        stopped = await self.call('program-stop', 'stop', program_id=program.id)
        self.assertTrue(stopped['ok'], stopped)
        self.assertFalse(program.active)
        await self.finish('The program stopped.')

    async def test_attach_pending_until_first_on_and_off_ack_never_claims_physical_verification(self):
        self.agent.settings = replace(self.agent.settings, turn_timeout=4)
        self.agent.device_tools.turn_timeout = 4
        self.agent.programs.action_timeout = .5
        program = await self.start(bpm=60)
        self.phone.ack = False
        attached = asyncio.create_task(self.call('program-update', 'attach-first-cycle',
            program_id=program.id, light_device_id='phone'))
        try:
            on = await asyncio.wait_for(self.phone.events.get(), 1.5)
            self.assertIs(on['args']['on'], True)
            self.assertFalse(attached.done())
            pending = await self.call('program-status', 'pending-on', program_id=program.id)
            participant = pending['result']['participants']['phone']
            self.assertEqual(participant['participant_state'], 'pending')
            self.assertFalse(participant['first_cycle']['on_ack'])
            self.assertNotIn('phone', pending['result']['light_device_ids'])
            self.core.bus.receive(self.phone.device, {'type': 'ok', 'req': on['req'], 'result': {'on': True}})
            off = await asyncio.wait_for(self.phone.events.get(), .75)
            self.assertIs(off['args']['on'], False)
            self.assertFalse(attached.done())
            pending = await self.call('program-status', 'pending-off', program_id=program.id)
            cycle = pending['result']['participants']['phone']['first_cycle']
            self.assertTrue(cycle['on_ack'])
            self.assertFalse(cycle['off_ack'])
            self.assertNotIn('phone', pending['result']['light_device_ids'])
            self.core.bus.receive(self.phone.device, {'type': 'ok', 'req': off['req'], 'result': {'on': False}})
            receipt = await asyncio.wait_for(attached, .3)
            self.assertTrue(receipt['ok'], receipt)
            participant = receipt['result']['participants']['phone']
            self.assertEqual(participant['participant_state'], 'following')
            self.assertTrue(participant['first_cycle']['on_ack'])
            self.assertTrue(participant['first_cycle']['off_ack'])
            self.assertFalse(participant['first_cycle']['physical_verified'])
            self.assertIn('phone', receipt['result']['light_device_ids'])
            self.assertFalse(receipt['result']['physical_sync_measured'])
        finally:
            self.phone.ack = True
            if not attached.done():
                attached.cancel()
            await asyncio.gather(attached, return_exceptions=True)
        await self.finish('The first phone cycle was acknowledged; physical sync is unverified.')

    async def test_first_phone_on_unknown_returns_failed_attach_and_same_id_cannot_replay(self):
        program = await self.start()
        self.phone.ack = False
        receipt = await self.call('program-update', 'attach-unknown', program_id=program.id, light_device_id='phone')
        self.assertFalse(receipt['ok'], receipt)
        self.assertEqual(receipt['code'], 'UNKNOWN')
        self.assertIn('phone', receipt['unknown_device_ids'])
        self.assertFalse(program.active)
        self.assertNotIn('phone', receipt['result']['light_device_ids'])
        self.assertNotEqual(receipt['result']['participants']['phone']['participant_state'], 'following')
        frames = list(self.phone.frames)
        duplicate = await self.call('program-update', 'attach-unknown', program_id=program.id, light_device_id='phone')
        self.assertEqual(duplicate, receipt)
        blocked = await self.call('program-update', 'attach-new-id', program_id=program.id, light_device_id='phone')
        self.assertEqual(blocked['code'], 'UNKNOWN')
        self.assertEqual(self.phone.frames, frames)
        self.phone.ack = True
        await self.finish('Phone attachment is unknown and was not repeated.')

    async def test_leave_while_first_cycle_pending_cannot_return_success_or_send_later_on(self):
        self.agent.settings = replace(self.agent.settings, turn_timeout=4)
        self.agent.device_tools.turn_timeout = 4
        self.agent.programs.action_timeout = .5
        program = await self.start(bpm=60)
        self.phone.ack = False
        attached = asyncio.create_task(self.call('program-update', 'attach-then-leave',
            program_id=program.id, light_device_id='phone'))
        try:
            on = await asyncio.wait_for(self.phone.events.get(), 1.5)
            self.assertIs(on['args']['on'], True)
            self.assertFalse(attached.done())
            self.core.revoke(self.lease.guest_id, actor='guest')
            receipt = await asyncio.wait_for(attached, .5)
            self.assertFalse(receipt['ok'], receipt)
            self.assertFalse(program.active)
            self.assertFalse(self.agent.allows_program(self.lease, program.owner.generation))
            # The already-dispatched ON may finish after revocation. Settle its
            # real receipt; graceful owned cleanup can then send OFF, never ON.
            self.phone.ack = True
            self.core.bus.receive(self.phone.device, {'type': 'ok', 'req': on['req'], 'result': {'on': True}})
            await asyncio.wait_for(program.cleanup_task, .3)
            self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False])
        finally:
            self.phone.ack = True
            if not attached.done():
                attached.cancel()
            await asyncio.gather(attached, return_exceptions=True)

    async def test_conflict_detach_then_original_steady_light_in_same_native_turn(self):
        program = await self.start()
        await self.attach(program)
        await asyncio.wait_for(self.phone.events.get(), 1)
        async with asyncio.timeout(.2):
            conflict = await self.call('call', 'steady-before', device_id='phone', cap='light', args={'on': True})
        self.assertEqual(conflict['code'], 'CONFLICT')
        self.assertEqual(conflict['program_id'], program.id)
        self.assertTrue(conflict['requires_new_request_id_after_confirmed_detach'])
        detached = await self.call('program-update', 'detach', program_id=program.id, remove_light_device_id='phone')
        self.assertTrue(detached['ok'], detached)
        self.assertTrue(program.active)
        steady = await self.call('call', 'steady-after', device_id='phone', cap='light', args={'on': True})
        self.assertTrue(steady['ok'], steady)
        self.assertEqual(self.phone.frames[-1]['args'], {'on': True})
        self.assertEqual(sum(frame['cap'] == 'beat.start' for frame in self.audio.frames), 1)
        await self.finish('The phone is steady; the beat continues.')

    async def test_helper_routes_whole_beat_cadence_without_audio_restart_and_retains_unknown_barrier(self):
        program = await self.start()
        run_id, phase = program.run_id, program.phase
        receipt = await self.call('program-update', 'whole-beat', program_id=program.id,
            light_device_id='phone', light_beats_per_state=1)
        self.assertTrue(receipt['ok'], receipt)
        participant = receipt['result']['participants']['phone']
        self.assertEqual(participant['light_beats_per_state'], 1)
        self.assertEqual(participant['on_duration_ms'], 100)  # Synthetic600BPM makes one beat100ms.
        self.assertEqual(participant['off_duration_ms'], 100)
        self.assertEqual(participant['participant_state'], 'following')
        self.assertFalse(participant['first_cycle']['physical_verified'])
        self.assertEqual((program.run_id, program.phase), (run_id, phase))
        self.assertEqual(sum(frame['cap'] == 'beat.start' for frame in self.audio.frames), 1)
        changed = await self.call('program-update', 'whole-beat', program_id=program.id,
            light_device_id='phone', light_beats_per_state=True)
        self.assertEqual(changed['code'], 'INVALID')  # Bool must not equal cached numeric1.
        self.grant.unknown_devices.add('phone')
        blocked = await self.call('program-update', 'different-cadence', program_id=program.id,
            light_device_id='phone', light_beats_per_state=.5)
        self.assertEqual(blocked['code'], 'UNKNOWN')
        self.assertEqual(program.participants['phone']['light_beats_per_state'], 1)
        malformed = await self.call('program-update', 'missing-phone', program_id=program.id,
                                    light_beats_per_state=1)
        self.assertEqual(malformed['code'], 'INVALID')
        stopped = await self.call('program-stop', 'stop-after-unknown', program_id=program.id)
        self.assertTrue(stopped['ok'], stopped)
        await self.finish('The requested cadence was recorded; physical sync remains unverified.')

    async def test_unknown_detach_preserves_reservation_and_refuses_raw_actions_without_wait(self):
        program = await self.start()
        await self.attach(program)
        await asyncio.wait_for(self.phone.events.get(), 1)
        self.phone.ack = False
        detached = await self.call('program-update', 'detach', program_id=program.id, remove_light_device_id='phone')
        self.assertEqual(detached['code'], 'UNKNOWN')
        before = len(self.phone.frames)
        async with asyncio.timeout(.2):
            conflict = await self.call('light-blink', 'blink', device_id='phone', count=5)
        self.assertEqual(conflict['code'], 'CONFLICT')
        self.assertEqual(len(self.phone.frames), before)
        self.assertTrue(program.active)
        self.assertEqual(self.agent.programs.device_busy('phone'), program.id)
        self.phone.ack = True
        await self.finish('Phone cleanup is unknown; the beat continues.')
        next_guest = self.core.leases.create()
        await self.begin('Use the phone.', lease=next_guest)
        blocked = await self.call('call', 'new-owner-phone', device_id='phone', cap='light', args={'on': True})
        self.assertEqual(blocked['code'], 'CONFLICT')
        self.assertEqual(blocked['recovery'], 'host_reset')
        self.assertNotIn('program_id', blocked)
        await self.finish('The host needs to recover the phone.')

    async def test_new_requested_off_waits_for_prior_uncertainty_then_releases_stopped_claim_without_reset(self):
        program = await self.start()
        await self.attach(program)
        self.phone.ack = False
        detached = await self.call('program-update', 'uncertain-detach', program_id=program.id, remove_light_device_id='phone')
        self.assertEqual(detached['code'], 'UNKNOWN')
        await self.call('program-stop', 'stop-old-program', program_id=program.id)
        await self.finish('The old OFF result is unknown.')
        unresolved = next(req for req, dev in self.core.bus.uncertain.items() if dev is self.phone.device)
        await self.begin('OK, turn off the flashlight.')
        self.grant.unknown_devices.add('phone')  # OFF must work despite this device-local quarantine.
        identity = self.core.registry.room.code, self.core.registry.room.epoch
        entered = asyncio.Event()
        original = self.agent.programs.explicit_off
        async def observed(*args, **kwargs):
            entered.set()
            return await original(*args, **kwargs)
        self.agent.programs.explicit_off = observed
        before = len(self.phone.frames)
        pending = asyncio.create_task(self.call('call', 'fresh-off', device_id='phone', cap='light', args={'on': False}))
        try:
            await entered.wait()
            self.assertEqual(len(self.phone.frames), before)
            self.phone.ack = True
            self.core.bus.receive(self.phone.device, {'type': 'ok', 'req': unresolved, 'result': {'on': False}})
            receipt = await pending
            self.assertTrue(receipt['ok'], receipt)
            self.assertEqual(receipt['result'], {'on': False})
            self.assertTrue(receipt['req'])
            self.assertEqual([frame['args']['on'] for frame in self.phone.frames[before:]], [False])
            self.assertIsNone(self.agent.programs.device_busy('phone'))
            self.assertEqual((self.core.registry.room.code, self.core.registry.room.epoch), identity)
            duplicate = await self.call('call', 'fresh-off', device_id='phone', cap='light', args={'on': False})
            self.assertEqual(duplicate, receipt)
            blocked_on = await self.call('call', 'no-old-on-replay', device_id='phone', cap='light', args={'on': True})
            self.assertEqual(blocked_on['code'], 'UNKNOWN')
            self.assertEqual(len(self.phone.frames), before + 1)
        finally:
            self.agent.programs.explicit_off = original
            await asyncio.gather(pending, return_exceptions=True)
        await self.finish('The phone acknowledged the newly requested OFF.')

    async def test_unknown_new_off_cannot_be_retried_under_another_id_in_same_native_turn(self):
        await self.begin('Turn the phone off.')
        self.phone.ack = False
        first = await self.call('call', 'off-once', device_id='phone', cap='light', args={'on': False})
        self.assertEqual(first['code'], 'UNKNOWN')
        before = len(self.phone.frames)
        self.phone.ack = True
        for req, dev in list(self.core.bus.uncertain.items()):
            self.core.bus.receive(dev, {'type': 'ok', 'req': req, 'result': {'on': False}})
        duplicate = await self.call('call', 'off-once', device_id='phone', cap='light', args={'on': False})
        self.assertEqual(duplicate, first)
        new_id = await self.call('call', 'no-new-id-retry', device_id='phone', cap='light', args={'on': False})
        self.assertEqual(new_id['code'], 'UNKNOWN')
        self.assertIn('Disconnect', new_id['message'])
        self.assertEqual(len(self.phone.frames), before)
        await self.finish('The OFF result is unknown; use the phone device page Disconnect.')

    async def test_explicit_off_loses_authority_while_bus_queued_and_sends_nothing(self):
        await self.begin('Turn the phone off.')
        lock = self.core.bus.locks['phone']
        await lock.acquire()
        queued = asyncio.Event()
        original = self.core.bus.call
        async def observed(*args, **kwargs):
            if args[:2] == ('phone', 'light'): queued.set()
            return await original(*args, **kwargs)
        self.core.bus.call = observed
        pending = asyncio.create_task(self.call('call', 'queued-off', device_id='phone', cap='light', args={'on': False}))
        try:
            await queued.wait()
            self.core.revoke(self.lease.guest_id)
            lock.release()
            result = await pending
            self.assertFalse(result['ok'])
            self.assertEqual(self.phone.frames, [])
        finally:
            if lock.locked(): lock.release()
            self.core.bus.call = original
            await asyncio.gather(pending, return_exceptions=True)

    async def test_concurrent_off_waiter_rechecks_unknown_latch_after_first_timeout_and_late_ack(self):
        await self.begin('Turn the phone off.')
        self.phone.ack = False
        self.agent.device_tools.action_timeout = .1
        entered = asyncio.Event()
        original = self.agent.programs.explicit_off
        calls = 0
        async def observed(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                entered.set()
                return await original(*args, **kwargs)
            result = await original(*args, **kwargs)
            # Keep the first receipt from latching until the waiter entered,
            # even if a loaded executor delays the second helper connection.
            await asyncio.wait_for(entered.wait(), .2)
            return result
        self.agent.programs.explicit_off = observed
        first = asyncio.create_task(self.call('call', 'first-off', device_id='phone', cap='light', args={'on': False}))
        frame = await asyncio.wait_for(self.phone.events.get(), .2)
        self.agent.device_tools.action_timeout = .4
        second = asyncio.create_task(self.call('call', 'waiting-off', device_id='phone', cap='light', args={'on': False}))
        try:
            await asyncio.wait_for(entered.wait(), .2)
            self.assertEqual((await first)['code'], 'UNKNOWN')
            self.phone.ack = True
            self.core.bus.receive(self.phone.device, {'type': 'ok', 'req': frame['req'], 'result': {'on': False}})
            self.assertFalse((await second)['ok'])
            self.assertEqual(len(self.phone.frames), 1)
        finally:
            self.agent.programs.explicit_off = original
            await asyncio.gather(first, second, return_exceptions=True)
        await self.finish('An OFF result was unknown; no waiting OFF was replayed.')

    async def test_program_ledger_deduplicates_start_and_does_not_limit_distinct_programs(self):
        first = await self.start()
        duplicate = await self.call('program-start', 'start', device_id='laptop', bpm=600)
        self.assertEqual(duplicate['result']['program_id'], first.id)
        changed = await self.call('program-start', 'start', device_id='laptop', bpm=300)
        self.assertEqual(changed['code'], 'INVALID')
        second = await self.call('program-start', 'start-two', device_id='laptop', bpm=300)
        self.assertTrue(second['ok'], second)
        self.assertNotEqual(second['result']['program_id'], first.id)
        self.assertEqual(sum(frame['cap'] == 'beat.start' for frame in self.audio.frames), 2)
        await self.finish()

    async def test_raw_unknown_then_late_ack_cannot_launch_program_on_same_mac(self):
        await self.begin('Play music, then use a beat only if confirmed.')
        self.audio.ack = False
        unknown = await self.call('call', 'raw-unknown', device_id='laptop', cap='music.play', args={})
        self.assertEqual(unknown['code'], 'UNKNOWN')
        frame = self.audio.frames[0]
        self.core.bus.receive(self.audio.device, {'type': 'ok', 'req': frame['req'], 'result': {'state': 'playing'}})
        self.audio.ack = True
        blocked = await self.call('program-start', 'new-id-program', device_id='laptop', bpm=600)
        self.assertEqual(blocked['code'], 'UNKNOWN')
        self.assertFalse(any(frame['cap'].startswith('beat.') for frame in self.audio.frames))
        independent = await self.call('call', 'independent-phone', device_id='phone', cap='light', args={'on': True})
        self.assertTrue(independent['ok'])
        await self.finish('The audio outcome is unknown; the phone is on.')

    async def test_program_unknown_then_late_ack_cannot_replay_raw_audio_on_same_mac(self):
        await self.begin('Start a generated beat.')
        self.audio.ack = False
        unknown = await self.call('program-start', 'program-unknown', device_id='laptop', bpm=600)
        self.assertEqual(unknown['code'], 'UNKNOWN')
        frame = self.audio.frames[0]
        self.core.bus.receive(self.audio.device, {'type': 'ok', 'req': frame['req'],
            'result': {'state': 'prepared', 'program_id': frame['args']['program_id']}})
        self.audio.ack = True
        before = len(self.audio.frames)
        blocked = await self.call('call', 'new-id-raw', device_id='laptop', cap='music.play', args={})
        self.assertEqual(blocked['code'], 'UNKNOWN')
        self.assertEqual(len(self.audio.frames), before)
        independent = await self.call('call', 'independent-phone', device_id='phone', cap='light', args={'on': True})
        self.assertTrue(independent['ok'])
        await self.finish('The beat outcome is unknown; the phone is on.')

    async def test_guest_leave_and_exact_expiry_invalidate_program_authority_immediately(self):
        program = await self.start()
        await self.attach(program, light_beats_per_state=1)
        generation = program.owner.generation
        await self.finish()
        before_on = sum(frame['args']['on'] is True for frame in self.phone.frames)
        self.core.revoke(self.lease.guest_id, actor='guest')
        self.assertFalse(program.active)
        self.assertFalse(self.agent.allows_program(self.lease, generation))
        await asyncio.wait_for(program.cleanup_task, .3)
        self.assertEqual(program.cleanup['audio'], 'confirmed')
        self.assertEqual(program.cleanup['phone'], 'confirmed')
        self.assertEqual(sum(frame['args']['on'] is True for frame in self.phone.frames), before_on)

    async def test_exact_expiry_sweep_stops_a_program_after_native_turn_finished(self):
        program = await self.start()
        await self.attach(program, light_beats_per_state=1)
        await self.finish()
        before_on = sum(frame['args']['on'] is True for frame in self.phone.frames)
        self.clock.now = self.lease.expires_at
        self.core.sweep()
        self.assertFalse(program.active)
        self.assertFalse(self.agent.allows_program(self.lease, program.owner.generation))
        await asyncio.wait_for(program.cleanup_task, .3)
        self.assertEqual(program.cleanup['phone'], 'confirmed')
        self.assertEqual(sum(frame['args']['on'] is True for frame in self.phone.frames), before_on)

    async def test_new_guest_has_clean_context_and_cannot_adopt_previous_program(self):
        program = await self.start()
        await self.finish('A previous guest beat.')
        other = self.core.leases.create()
        await self.begin('I am a new guest.', lease=other)
        self.assertFalse(program.active)
        self.assertEqual(self.lease.state, 'released')
        denied = await self.call('program-status', 'old-status', program_id=program.id)
        self.assertEqual(denied['code'], 'PERMISSION')
        self.assertEqual(self.native.history[-1]['text'], 'I am a new guest.')
        self.assertEqual(len(self.native.history), 2)
        await self.finish()

    async def test_host_reset_invalidates_program_then_cleans_native_anchor(self):
        program = await self.start()
        await self.finish()
        result = await self.core.reset()
        self.assertEqual(result['context_cleanup'], 'confirmed')
        self.assertFalse(program.active)
        self.assertFalse(self.agent.allows_program(self.lease, program.owner.generation))
        self.assertEqual([turn['id'] for turn in self.native.history], list(self.agent.settings.anchor_turn_ids))
        await asyncio.wait_for(program.cleanup_task, .3)
        self.assertFalse(self.agent.programs._closed)
        other = self.core.leases.create()
        await self.begin('Start a fresh guest beat.', lease=other)
        restarted = await self.call('program-start', 'new-guest-beat', device_id='laptop', bpm=300)
        self.assertTrue(restarted['ok'], restarted)
        self.assertNotEqual(restarted['result']['program_id'], program.id)
        await self.finish('A new guest beat started.')
        await self.agent.close()
        self.assertTrue(self.agent.programs._closed)

    async def test_existing_host_reset_off_receipt_recovers_unknown_phone_for_next_guest(self):
        program = await self.start()
        await self.attach(program)
        first_cycle = [await asyncio.wait_for(self.phone.events.get(), 1) for _ in range(2)]
        self.assertEqual([frame['args']['on'] for frame in first_cycle], [True, False])
        self.phone.ack = False
        ended = asyncio.Event()
        invalidate = self.agent.programs._invalidate
        def observed_invalidation(current, reason, device_id=None):
            invalidate(current, reason, device_id)
            if current is program: ended.set()
        self.agent.programs._invalidate = observed_invalidation
        unknown_frame = await asyncio.wait_for(self.phone.events.get(), 1)
        await asyncio.wait_for(ended.wait(), 1)
        await asyncio.wait_for(program.cleanup_task, .3)
        self.assertEqual(self.agent.programs.device_busy('phone'), program.id)
        self.assertIn(unknown_frame['req'], self.core.bus.uncertain)
        self.core.bus.receive(self.phone.device, {'type': 'ok', 'req': unknown_frame['req'], 'result': {'on': False}})
        self.phone.ack = True
        await self.finish('The phone outcome needs recovery.')
        before = len(self.phone.frames)
        reset = await self.core.reset()
        self.assertEqual(reset['program_cleanup'], 'confirmed', reset)
        self.assertEqual(reset['cleanup'], 'confirmed', reset)
        self.assertEqual(len(self.phone.frames), before + 1)  # Existing host OFF only.
        self.assertIsNone(self.agent.programs.device_busy('phone'))
        new_guest = self.core.leases.create()
        await self.begin('Turn the phone on.', lease=new_guest)
        result = await self.call('call', 'new-guest-on', device_id='phone', cap='light', args={'on': True})
        self.assertTrue(result['ok'], result)
        await self.finish('The phone is on.')

    async def test_host_reset_does_not_claim_full_cleanup_when_audio_stop_is_unknown(self):
        program = await self.start()
        await self.finish()
        self.audio.ack = False
        reset = await self.core.reset()
        self.assertEqual(reset['program_cleanup'], 'unconfirmed')
        self.assertEqual(reset['cleanup'], 'unconfirmed')
        self.assertEqual(program.cleanup['audio'], 'unknown')
        self.audio.ack = True

    def mac_cleanup_budgets(self):
        self.agent.settings = replace(self.agent.settings, cleanup_timeout=.6)
        self.agent.device_tools.action_timeout = .2
        self.agent.device_tools.speech_timeout = self.core.speech.timeout = .6
        self.agent.programs.audio_queue_timeout = .8
        self.audio.device.caps['say'] = CapSpec('say', {'text': {'type': 'string'}}, 'Speech')
        self.audio.device.caps['music.pause'] = CapSpec('music.pause', {}, 'Pause music')

    async def test_host_reset_phone_off_is_parallel_while_pause_waits_for_accepted_narration(self):
        self.mac_cleanup_budgets()
        started, release = asyncio.Event(), asyncio.Event()
        async def mac(frame):
            self.audio.frames.append(frame)
            if frame['cap'] == 'say':
                started.set()
                await release.wait()
                result = {'spoken': True}
            else:
                self.assertEqual(frame['cap'], 'music.pause')
                result = {'state': 'paused'}
            self.core.bus.receive(self.audio.device, {'type': 'ok', 'req': frame['req'], 'result': result})
        self.audio.send_json = mac
        narration = asyncio.create_task(self.core.bus.call('laptop', 'say', {'text': 'Accepted narration'},
            timeout=self.core.speech.timeout, authorize=lambda *_: True))
        reset = None
        try:
            await started.wait()
            reset = asyncio.create_task(self.core.reset())
            off = await asyncio.wait_for(self.phone.events.get(), .2)
            self.assertIs(off['args']['on'], False)
            self.assertFalse(reset.done())
            self.assertEqual([frame['cap'] for frame in self.audio.frames], ['say'])
            await asyncio.sleep(.25)  # Accepted speech outlasts the ordinary .2s action budget.
            release.set()
            self.assertTrue((await narration).ok)
            result = await asyncio.wait_for(reset, .4)
            self.assertEqual(result['cleanup'], 'confirmed', result)
            self.assertEqual([frame['cap'] for frame in self.audio.frames], ['say', 'music.pause'])
            self.assertGreater(self.audio.frames[-1]['deadline_ms'], 200)
        finally:
            release.set()
            await asyncio.gather(narration, *([reset] if reset else []), return_exceptions=True)

    async def test_host_reset_never_settling_mac_queue_is_bounded_and_known_unsent(self):
        self.mac_cleanup_budgets()
        lock = self.core.bus.locks['laptop']
        await lock.acquire()
        try:
            reset = asyncio.create_task(self.core.reset())
            off = await asyncio.wait_for(self.phone.events.get(), .2)
            self.assertIs(off['args']['on'], False)
            result = await asyncio.wait_for(reset, 1.2)
            self.assertEqual(result['cleanup'], 'unconfirmed')
            rows = [row['audit'] for row in self.core.log.audit_rows
                    if row.get('audit', {}).get('actor') == 'host.reset'
                    and row.get('audit', {}).get('cap') == 'music.pause']
            self.assertEqual(rows[-1]['code'], 'TIMEOUT')
            self.assertIsNone(rows[-1]['req'])
            self.assertFalse(any(frame['cap'] == 'music.pause' for frame in self.audio.frames))
        finally:
            lock.release()

    async def test_reset_waits_for_program_queue_budget_beyond_native_cleanup_budget(self):
        await self.start()
        await self.finish()
        self.agent.settings = replace(self.agent.settings, cleanup_timeout=.01)
        self.agent.programs.audio_queue_timeout = .2
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.agent.programs.quiesce
        async def delayed_queue_settlement():
            entered.set()
            await release.wait()
            return await original()
        self.agent.programs.quiesce = delayed_queue_settlement
        reset = asyncio.create_task(self.core.reset())
        try:
            await entered.wait()
            await asyncio.sleep(.03)  # Beyond the separate native cleanup budget.
            self.assertFalse(reset.done())
            release.set()
            result = await asyncio.wait_for(reset, .3)
            self.assertEqual(result['program_cleanup'], 'confirmed', result)
            self.assertEqual(result['cleanup'], 'confirmed', result)
        finally:
            release.set()
            await asyncio.gather(reset, return_exceptions=True)
            self.agent.programs.quiesce = original

    async def test_program_close_timeout_still_closes_native_and_private_helper_resources(self):
        program = await self.start()
        await self.finish()
        directory = self.agent.device_tools._directory.name
        original = self.agent.programs.close
        async def hung_program_close():
            await asyncio.Event().wait()
        self.agent.programs.close = hung_program_close
        try:
            async with asyncio.timeout(.6):
                await self.agent.close()
            self.assertTrue(self.native.closed)
            from pathlib import Path
            self.assertFalse(Path(directory).exists())
            self.assertFalse(program.active)
            self.assertFalse(self.agent.allows_program(self.lease, program.owner.generation))
        finally:
            self.agent.programs.close = original
            await original()

    async def test_completed_turn_before_queued_start_never_launches_old_program(self):
        await self.begin()
        lock = self.core.bus.locks['laptop']
        await lock.acquire()
        queued = asyncio.Event()
        original = self.core.bus.call
        async def with_queue_barrier(*args, **kwargs):
            if args[1] == 'beat.prepare': queued.set()
            return await original(*args, **kwargs)
        self.core.bus.call = with_queue_barrier
        pending = asyncio.create_task(self.call('program-start', 'queued-start', device_id='laptop', bpm=600))
        await queued.wait()
        await self.finish('Nothing started yet.')
        lock.release()
        result = await pending
        self.assertFalse(result['ok'])
        self.assertFalse(any(frame['cap'] in ('beat.prepare', 'beat.start') for frame in self.audio.frames))

    async def test_helper_explicit_speech_receipt_suppresses_duplicate_auto_narration(self):
        speaker = self.register('speaker', {'say': {'description': 'Speech', 'args': {'text': {'type': 'string'}}}})
        original = speaker.send_json
        async def speech_ack(frame):
            if frame['cap'] == 'say':
                speaker.frames.append(frame)
                self.core.bus.receive(speaker.device, {'type': 'ok', 'req': frame['req'], 'result': {'spoken': True}})
            else:
                await original(frame)
        speaker.send_json = speech_ack
        await self.begin('Say hello on the speaker.')
        result = await self.call('call', 'say-once', device_id='speaker', cap='say', args={'text': 'Hello.'})
        self.assertTrue(result['ok'])
        frames = await self.finish('Hello.')
        self.assertTrue(frames.completed_reply.explicit_speech_attempted)
        await self.core.speech.speak_reply(frames)
        self.assertEqual(len(speaker.frames), 1)

    async def test_unknown_explicit_speech_is_not_narrated_or_retried(self):
        speaker = self.register('speaker', {'say': {'description': 'Speech', 'args': {'text': {'type': 'string'}}}})
        speaker.ack = False
        await self.begin('Say hello on the speaker.')
        result = await self.call('call', 'say-unknown', device_id='speaker', cap='say', args={'text': 'Hello.'})
        self.assertEqual(result['code'], 'UNKNOWN')
        frames = await self.finish('Speech could not be confirmed.')
        self.assertTrue(frames.completed_reply.explicit_speech_attempted)
        await self.core.speech.speak_reply(frames)
        self.assertEqual(len(speaker.frames), 1)

    async def test_explicit_speech_frame_uses_speech_policy_bounded_by_live_lease(self):
        speaker = self.register('speaker', {'say': {'description': 'Speech', 'args': {'text': {'type': 'string'}}}})
        async def speech_ack(frame):
            speaker.frames.append(frame)
            self.core.bus.receive(speaker.device, {'type': 'ok', 'req': frame['req'], 'result': {'spoken': True}})
        speaker.send_json = speech_ack
        self.agent.device_tools.speech_timeout = .25
        self.lease.expires_at = self.clock.now + .12
        await self.begin('Say hello.')
        result = await self.call('call', 'speech-budget', device_id='speaker', cap='say', args={'text': 'Hello.'})
        self.assertTrue(result['ok'])
        self.assertGreater(speaker.frames[0]['deadline_ms'], 30)  # Ordinary action budget is .03s.
        self.assertLessEqual(speaker.frames[0]['deadline_ms'], 120)
        await self.finish('Hello.')

    def test_cli_program_update_schema_accepts_detach_and_rejects_extra_actions(self):
        payload = {'request_id': 'detach', 'program_id': 'owned', 'remove_light_device_id': 'phone'}
        with patch('agent.tenant_device.invoke', return_value={'ok': True}) as dispatch:
            with patch('sys.stdin', io.StringIO(json.dumps(payload))), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(['--context', '/private/fake-context', 'program-update']), 0)
            self.assertEqual(dispatch.call_args.args[2], payload)
        payload['shell'] = 'unsupported'
        with patch('agent.tenant_device.invoke') as dispatch:
            with patch('sys.stdin', io.StringIO(json.dumps(payload))), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(['--context', '/private/fake-context', 'program-update']), 1)
            dispatch.assert_not_called()

    def test_cli_whole_beat_cadence_requires_an_explicit_phone(self):
        payload = {'request_id': 'whole-beat', 'program_id': 'owned',
                   'light_device_id': 'phone', 'light_beats_per_state': 1}
        with patch('agent.tenant_device.invoke', return_value={'ok': True}) as dispatch:
            with patch('sys.stdin', io.StringIO(json.dumps(payload))), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(['--context', '/private/fake-context', 'program-update']), 0)
            self.assertEqual(dispatch.call_args.args[2], payload)
        payload.pop('light_device_id')
        with patch('agent.tenant_device.invoke') as dispatch:
            with patch('sys.stdin', io.StringIO(json.dumps(payload))), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(['--context', '/private/fake-context', 'program-update']), 1)
            dispatch.assert_not_called()


if __name__ == '__main__': unittest.main()
