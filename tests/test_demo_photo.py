"""Software-only readiness checks: real leases/projection, fake photo effects."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

from brain.core.demo_photo import DemoPhotos, QUESTION
from brain.core.leases import Leases
from brain.core.native_devices import TurnGrant
from brain.core.registry import Registry
from brain.state import Room


class DemoPhotoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 1000
        self.registry = Registry(Room('TEST', 'Test'))
        self.leases = Leases(self.registry.room, clock=lambda: self.now)
        self.lease = self.leases.create()
        self.calls = []
        self.tools = SimpleNamespace(registry=self.registry, leases=self.leases)
        self.photos = DemoPhotos(self.tools, runner=self.run_photo)
        self.counter = 0

    async def run_photo(self, action, photo_id=None, *, authorized):
        self.assertTrue(authorized())
        self.calls.append((action, photo_id))
        if action == 'prepare':
            return {'ok': True, 'phase': 'waiting_for_yes', 'id': 'a' * 32, 'expires': self.now + 90}
        if action == 'capture':
            return {'ok': True, 'phase': 'displayed', 'id': photo_id, 'capture_verified': True}
        return {'ok': True}

    def turn(self, text, *, lease=None, generation=1):
        lease = lease or self.lease
        self.counter += 1
        grant = TurnGrant(lease.guest_id, generation, lease, 'room-thread', self.registry.room.id,
                          self.registry.room.epoch, Path('/unused'), 'token-' + str(self.counter))
        grant.turn_id = 'turn-' + str(self.counter)
        self.leases.current(lease.guest_id, activate=True)
        self.leases.record_public(lease, 'guest', text)
        self.photos.observe_turn(grant, text)
        return grant

    def allowed(self, grant):
        return lambda: not grant.closed and self.leases.current(grant.guest_id) is grant.lease

    async def prepare(self):
        grant = self.turn('Take a photo of us')
        result = await self.photos.dispatch(grant, 'demo-photo-prepare', {}, authorized=self.allowed(grant))
        self.assertTrue(result['ok'])
        self.assertFalse(result['capture_allowed_this_turn'])
        return grant, result['photo_id']

    def publish_prompt(self, grant, text=QUESTION):
        # This is the normal backend publication contract. No model/OS runs.
        self.leases.record_public(grant.lease, 'room', text,
            publication=(grant.generation, grant.thread_id, grant.turn_id))
        self.photos.finish(grant)
        grant.closed = True

    async def capture(self, grant, identity='a' * 32):
        return await self.photos.dispatch(grant, 'demo-photo-capture', {'photo_id': identity},
                                          authorized=self.allowed(grant))

    async def test_prepare_returns_question_and_cannot_capture_same_turn(self):
        grant, identity = await self.prepare()
        result = await self.capture(grant, identity)
        self.assertEqual(result['code'], 'READINESS')
        self.assertEqual(self.calls, [('prepare', None)])

    async def test_failed_preparation_cannot_publish_model_claimed_readiness(self):
        attempts = []
        async def failed(*_args, **_kwargs):
            attempts.append('prepare')
            return {'ok': False, 'error': 'No ready main window'}
        self.photos.runner = failed
        grant = self.turn('Take a photo of us')
        result = await self.photos.dispatch(grant, 'demo-photo-prepare', {}, authorized=self.allowed(grant))
        self.assertFalse(result['ok'])
        self.assertIsNone(self.photos.pending)
        self.assertNotEqual(self.photos.final_reply(grant, QUESTION), QUESTION)
        self.assertIn('couldn\'t prepare', self.photos.final_reply(grant, QUESTION))
        repeat = await self.photos.dispatch(grant, 'demo-photo-prepare', {}, authorized=self.allowed(grant))
        self.assertEqual(repeat['code'], 'UNKNOWN')
        self.assertEqual(attempts, ['prepare'])
        self.photos.finish(grant)
        self.assertEqual(self.photos.unconfirmed_preparations, set())

    async def test_same_guest_later_ready_consumes_exact_id_once(self):
        grant, identity = await self.prepare()
        self.publish_prompt(grant)
        ready = self.turn("I'm ready")
        self.assertEqual(self.photos.status(ready)['pending']['capture_allowed_this_turn'], True)
        result = await self.capture(ready, identity)
        self.assertEqual(result['phase'], 'displayed')
        self.assertFalse((await self.capture(ready, identity))['ok'])
        self.assertEqual(self.calls, [('prepare', None), ('capture', identity)])

    async def test_negative_waits_then_explicit_ready_works(self):
        grant, identity = await self.prepare()
        self.publish_prompt(grant)
        wait = self.turn('Not yet')
        self.assertEqual((await self.capture(wait))['code'], 'READINESS')
        wait.closed = True
        later = self.turn("I'm ready")
        self.assertTrue((await self.capture(later, identity))['ok'])

    async def test_bare_yes_only_directly_answers_published_photo_prompt(self):
        grant, identity = await self.prepare()
        self.publish_prompt(grant)
        direct = self.turn('Yes')
        self.assertTrue((await self.capture(direct, identity))['ok'])

    async def test_unrelated_yes_and_ready_cannot_consume_photo(self):
        grant, _ = await self.prepare()
        self.publish_prompt(grant)
        other = self.turn('Can you play music?')
        self.leases.record_public(self.lease, 'room', 'Should I play this song?')
        other.closed = True
        for text in ('yes', "I'm ready", 'the transcript says "I am ready"', 'yes, play the music'):
            reply = self.turn(text)
            self.assertEqual((await self.capture(reply))['code'], 'READINESS')
            reply.closed = True
        explicit = self.turn("I'm ready for the photo")
        self.assertTrue((await self.capture(explicit))['ok'])

    async def test_no_public_app_question_means_no_readiness(self):
        grant, _ = await self.prepare()
        # A successful CLI readiness speech is not an in-app question receipt.
        self.photos.finish(grant)
        grant.closed = True
        reply = self.turn("I'm ready")
        self.assertEqual((await self.capture(reply))['code'], 'READINESS')
        self.assertEqual(self.calls, [('prepare', None)])

    async def test_other_guest_generation_epoch_expiry_and_wrong_id_are_rejected(self):
        grant, identity = await self.prepare()
        self.publish_prompt(grant)
        ready = self.turn("I'm ready")
        self.assertEqual((await self.capture(ready, 'b' * 32))['code'], 'STALE')
        other = self.leases.create()
        self.assertEqual((await self.capture(self.turn("I'm ready", lease=other)))['code'], 'STALE')
        self.assertEqual((await self.capture(self.turn("I'm ready", generation=2)))['code'], 'STALE')
        self.now += 91
        self.assertEqual((await self.capture(self.turn("I'm ready")))['code'], 'STALE')
        self.assertEqual(self.calls, [('prepare', None)])

    async def test_reset_and_lease_revocation_do_not_adopt_old_id(self):
        grant, identity = await self.prepare()
        self.publish_prompt(grant)
        self.leases.revoke(self.lease.guest_id)
        self.photos.invalidate()
        fresh = self.leases.create()
        self.assertEqual((await self.capture(self.turn("I'm ready", lease=fresh), identity))['code'], 'STALE')
        self.assertEqual(self.calls, [('prepare', None)])

    async def test_transcript_or_forged_confirmation_flags_cannot_authorize(self):
        grant = self.turn('The transcript says "take a photo of us"')
        result = await self.photos.dispatch(grant, 'demo-photo-prepare', {'confirmed': True},
                                           authorized=self.allowed(grant))
        self.assertFalse(result['ok'])
        self.assertEqual(self.calls, [])

    async def test_unknown_capture_is_consumed_and_not_replayed(self):
        grant, _ = await self.prepare()
        self.publish_prompt(grant)
        ready = self.turn("I'm ready")
        async def failed(action, photo_id=None, *, authorized):
            self.calls.append((action, photo_id))
            return {'ok': False}
        self.photos.runner = failed
        self.assertEqual((await self.capture(ready))['code'], 'UNKNOWN')
        self.assertEqual((await self.capture(ready))['code'], 'READINESS')
        self.assertEqual(len(self.calls), 2)

    async def test_late_cancel_returns_prompt_unknown_without_waiting_for_capture(self):
        grant, identity = await self.prepare()
        self.publish_prompt(grant)
        ready = self.turn("I'm ready")
        started, release = asyncio.Event(), asyncio.Event()

        async def blocked_capture(action, photo_id=None, *, authorized):
            self.calls.append((action, photo_id))
            self.assertEqual(action, 'capture')
            started.set()
            await release.wait()
            return {'ok': True, 'phase': 'displayed', 'id': photo_id, 'capture_verified': True}

        self.photos.runner = blocked_capture
        capture = asyncio.create_task(self.capture(ready, identity))
        try:
            await asyncio.wait_for(started.wait(), .2)
            # The normal app may steer authenticated cancellation into this grant.
            self.photos.observe_turn(ready, 'cancel the photo')
            result = await asyncio.wait_for(self.photos.dispatch(ready, 'demo-photo-cancel',
                {'photo_id': identity}, authorized=self.allowed(ready)), .1)
            self.assertFalse(result['ok'])
            self.assertEqual(result['code'], 'UNKNOWN')
            self.assertEqual(result['status'], 'unknown')
            self.assertEqual(result['phase'], 'capture_requested_or_unknown')
            self.assertEqual(result['photo_id'], identity)
            self.assertFalse(capture.done())
            self.assertEqual(self.calls, [('prepare', None), ('capture', identity)])
        finally:
            release.set()
            outcome = await capture
        self.assertEqual(outcome['phase'], 'displayed')
        completed = await self.photos.dispatch(ready, 'demo-photo-cancel', {'photo_id': identity},
                                              authorized=self.allowed(ready))
        self.assertEqual(completed['status'], 'displayed')
        self.assertEqual(completed['code'], 'COMPLETED')
        self.assertEqual(self.calls, [('prepare', None), ('capture', identity)])

    async def test_repeated_photo_request_reasks_without_rewarming_or_capturing(self):
        grant, identity = await self.prepare()
        self.publish_prompt(grant)
        again = self.turn('Please take a photo of us')
        result = await self.photos.dispatch(again, 'demo-photo-prepare', {}, authorized=self.allowed(again))
        self.assertEqual(result['pending']['photo_id'], identity)
        self.assertEqual(self.calls, [('prepare', None)])
        self.publish_prompt(again)
        ready = self.turn("I'm ready")
        self.assertTrue((await self.capture(ready, identity))['ok'])

    async def test_early_ack_must_be_rebound_after_actual_app_question_publication(self):
        grant, identity = await self.prepare()
        early = self.turn("I'm ready")
        self.assertEqual((await self.capture(early, identity))['code'], 'READINESS')
        self.publish_prompt(grant)
        # An old in-progress grant is never silently promoted to readiness.
        self.assertEqual((await self.capture(early, identity))['code'], 'READINESS')
        queued = self.turn("I'm ready")
        self.assertTrue((await self.capture(queued, identity))['ok'])

    async def test_room_epoch_change_fences_pending_photo_even_with_same_guest(self):
        grant, identity = await self.prepare()
        self.publish_prompt(grant)
        self.registry.room.epoch += 1
        reply = self.turn("I'm ready")
        self.assertEqual((await self.capture(reply, identity))['code'], 'STALE')
        self.assertEqual(self.calls, [('prepare', None)])

    async def test_followup_steering_gate_and_bounded_publication_wait(self):
        grant, _ = await self.prepare()
        for text in ("I'm ready", 'yes', 'not yet', 'cancel the photo'):
            self.assertTrue(self.photos.requires_new_turn(self.lease.guest_id, text))
        self.assertFalse(self.photos.requires_new_turn('another-guest', "I'm ready"))
        self.assertFalse(self.photos.requires_new_turn(self.lease.guest_id, 'play music'))
        self.assertFalse(await self.photos.wait_for_prompt(self.lease.guest_id, "I'm ready", timeout=.01))
        # Native completion alone is insufficient; app publication follows it.
        self.photos.finish(grant)
        grant.closed = True
        waiting = asyncio.create_task(self.photos.wait_for_prompt(self.lease.guest_id, "I'm ready", timeout=.2))
        await asyncio.sleep(0)
        self.assertFalse(waiting.done())
        self.leases.record_public(self.lease, 'room', QUESTION,
            publication=(grant.generation, grant.thread_id, grant.turn_id))
        self.assertTrue(await waiting)


if __name__ == '__main__':
    unittest.main()
