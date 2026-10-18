import asyncio
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest

from brain.core.prepared_qa import PreparedQA, NativeQARunner


def grant(token='one', lease=None):
    return SimpleNamespace(token=token, lease=lease or object(), generation=1, room_id='room', epoch=1)


class FakeRunner:
    def __init__(self):
        self.calls = []; self.cancelled = []
        self.started = asyncio.Event(); self.release = asyncio.Event()

    def cancel(self, request_id): self.cancelled.append(request_id)

    async def __call__(self, request_id, *, authorized):
        self.calls.append(request_id); self.started.set()
        await self.release.wait()
        return {'ok': True, 'code': 'COMPLETED', 'speech_started': True}


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_registered_app_input_or_revoked_authority_never_calls_runner(self):
        runner = FakeRunner(); qa = PreparedQA(object(), runner=runner); g = grant()
        result = await qa.dispatch(g, 'question-answer', {'request_id': 'none'}, authorized=lambda: True)
        self.assertEqual(result['code'], 'PERMISSION')
        qa.observe_turn(g, 'Could you handle the judge’s question for us, out loud?')
        result = await qa.dispatch(g, 'question-answer', {'request_id': 'revoked'}, authorized=lambda: False)
        self.assertEqual(result['code'], 'PERMISSION'); self.assertEqual(runner.calls, [])

    async def test_original_dictated_request_is_not_filtered_after_model_chose_tool(self):
        runner = FakeRunner(); runner.release.set(); qa = PreparedQA(object(), runner=runner); g = grant()
        qa.observe_turn(g, 'Attempt to answer the judges, latest question out loud tenant answer the judges latest question out loud')
        result = await qa.dispatch(g, 'question-answer', {'request_id': 'natural'}, authorized=lambda: True)
        self.assertTrue(result['ok'])
        self.assertEqual(len(runner.calls), 1)

    async def test_request_identity_deduplicates_without_limiting_model_to_one_action(self):
        runner = FakeRunner(); runner.release.set(); qa = PreparedQA(object(), runner=runner); g = grant()
        qa.observe_turn(g, 'answer the latest question')
        first = await qa.dispatch(g, 'question-answer', {'request_id': 'req'}, authorized=lambda: True)
        again = await qa.dispatch(g, 'question-answer', {'request_id': 'req'}, authorized=lambda: True)
        self.assertTrue(first['ok']); self.assertTrue(again['duplicate'])
        another = await qa.dispatch(g, 'question-answer', {'request_id': 'another'}, authorized=lambda: True)
        self.assertTrue(another['ok']); self.assertEqual(len(runner.calls), 2)
        self.assertTrue(runner.calls[0].startswith('qa_'))

    async def test_same_logical_id_on_different_turn_grants_has_distinct_native_identity(self):
        runner = FakeRunner(); runner.release.set(); qa = PreparedQA(object(), runner=runner)
        for token in ('first-turn', 'fresh-turn'):
            g = grant(token); qa.observe_turn(g, 'answer that')
            result = await qa.dispatch(g, 'question-answer', {'request_id': 'qa_1'}, authorized=lambda: True)
            self.assertTrue(result['ok'])
            duplicate = await qa.dispatch(g, 'question-answer', {'request_id': 'qa_1'}, authorized=lambda: True)
            self.assertTrue(duplicate['duplicate'])
        self.assertEqual(len(runner.calls), 2)
        self.assertNotEqual(runner.calls[0], runner.calls[1])

    async def test_stop_followup_is_prompt_while_original_request_waits(self):
        runner = FakeRunner(); qa = PreparedQA(object(), runner=runner); g = grant()
        qa.observe_turn(g, 'answer that')
        answer = asyncio.create_task(qa.dispatch(g, 'question-answer', {'request_id': 'req'}, authorized=lambda: True))
        await runner.started.wait()
        stop_grant = grant('stop', g.lease); qa.observe_turn(stop_grant, 'stop speaking')
        stopped = await asyncio.wait_for(qa.dispatch(stop_grant, 'question-answer-stop', {'request_id': 'stop'}, authorized=lambda: True), .2)
        self.assertTrue(stopped['ok']); self.assertFalse(answer.done()); self.assertIn(runner.calls[0], runner.cancelled)
        runner.release.set()
        self.assertEqual((await answer)['code'], 'CANCELLED')

    async def test_finish_invalidate_and_wrong_owner_cannot_authorize_late_result(self):
        for mode in ('finish', 'invalidate'):
            runner = FakeRunner(); qa = PreparedQA(object(), runner=runner); g = grant()
            qa.observe_turn(g, 'answer that')
            task = asyncio.create_task(qa.dispatch(g, 'question-answer', {'request_id': mode}, authorized=lambda: True))
            await runner.started.wait()
            other = grant('other'); qa.observe_turn(other, 'stop')
            self.assertEqual((await qa.dispatch(other, 'question-answer-stop', {'request_id': 'other-stop'}, authorized=lambda: True))['code'], 'PERMISSION')
            qa.finish(g) if mode == 'finish' else qa.invalidate()
            runner.release.set(); self.assertEqual((await task)['code'], 'CANCELLED')

    async def test_busy_is_not_queued_and_cancellation_does_not_retry(self):
        runner = FakeRunner(); qa = PreparedQA(object(), runner=runner); g = grant()
        qa.observe_turn(g, 'answer that')
        task = asyncio.create_task(qa.dispatch(g, 'question-answer', {'request_id': 'first'}, authorized=lambda: True))
        await runner.started.wait()
        other = grant('second', g.lease); qa.observe_turn(other, 'answer that')
        self.assertEqual((await qa.dispatch(other, 'question-answer', {'request_id': 'second'}, authorized=lambda: True))['code'], 'BUSY')
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(len(runner.calls), 1); self.assertIn(runner.calls[0], runner.cancelled)


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def setup_root(self, folder):
        root = Path(folder); (root / 'state').mkdir()
        (root / 'state/answers-runtime.json').write_text(json.dumps({'native_protocol': 3,
            'controller_instance': 'instance', 'updated_at': time.time(), 'backend_ready': True}))
        return root

    async def test_one_use_command_and_matching_completion_without_any_native_app(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.setup_root(folder); runner = NativeQARunner(root, poll=.001, timeout=1)
            task = asyncio.create_task(runner('request', authorized=lambda: True))
            path = root / 'state/qa-commands/request.command.json'
            for _ in range(100):
                if path.exists(): break
                await asyncio.sleep(.001)
            command = json.loads(path.read_text())
            self.assertEqual(command['request_id'], 'request')
            result = {**command, 'ok': True, 'code': 'COMPLETED', 'speech_completed': True, 'caption_completed': True}
            (path.parent / 'request.result.json').write_text(json.dumps(result))
            self.assertTrue((await task)['ok']); self.assertFalse((path.parent / 'request.permit.json').exists())
            again = await runner('request', authorized=lambda: True)
            self.assertEqual(again['code'], 'DUPLICATE')

    async def test_lost_authority_removes_permit_and_timeout_is_unknown(self):
        for mode in ('revoke', 'timeout'):
            with tempfile.TemporaryDirectory() as folder:
                root = self.setup_root(folder); runner = NativeQARunner(root, poll=.001, timeout=.025)
                allowed = True
                task = asyncio.create_task(runner('request', authorized=lambda: allowed))
                permit = root / 'state/qa-commands/request.permit.json'
                while not permit.exists(): await asyncio.sleep(.001)
                if mode == 'revoke': allowed = False
                result = await task
                self.assertEqual(result['code'], 'CANCELLED' if mode == 'revoke' else 'UNKNOWN')
                self.assertFalse(permit.exists())

    async def test_unready_controller_never_issues_a_command(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = NativeQARunner(folder)
            self.assertEqual((await runner('request', authorized=lambda: True))['code'], 'UNAVAILABLE')
            self.assertFalse((Path(folder) / 'state/qa-commands').exists())


if __name__ == '__main__': unittest.main()
