"""Helper dispatch certainty with temporary contexts and fake sockets only."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.tenant_device import MAX_BYTES, invoke, main


SECRET = 'private-helper-token-never-report'
PRIVATE_SOCKET = '/private/tenant-secret-context/bus.sock'
SENSITIVE_ERROR = f'{SECRET} {PRIVATE_SOCKET}'


class FakeStream:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        self.owner.fail('stream-enter')
        return self

    def __exit__(self, *_args):
        self.owner.fail('stream-exit')

    def readline(self, limit):
        self.owner.read_limits.append(limit)
        self.owner.fail('readline')
        return self.owner.reply


class FakeSocket:
    def __init__(self, failure=None, reply=b'{"ok":true,"result":{"on":true}}\n'):
        self.failure, self.reply = failure, reply
        self.sends, self.accepted, self.read_limits = [], [], []
        self.timeouts, self.addresses = [], []

    def fail(self, stage):
        if self.failure == stage:
            raise OSError(SENSITIVE_ERROR)

    def __enter__(self):
        self.fail('enter')
        return self

    def __exit__(self, *_args):
        self.fail('exit')

    def settimeout(self, timeout):
        self.timeouts.append(timeout)
        self.fail('settimeout')

    def connect(self, address):
        self.addresses.append(address)
        self.fail('connect')

    def sendall(self, encoded):
        self.sends.append(encoded)
        if self.failure == 'partial-send':
            self.accepted.append(encoded[:7])
            raise OSError(SENSITIVE_ERROR)
        self.fail('sendall')
        self.accepted.append(encoded)

    def makefile(self, mode):
        self.fail('makefile')
        if mode != 'rb':
            raise AssertionError('Expected binary reply stream')
        return FakeStream(self)


class TenantDeviceTransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='tenant-private-context-')
        self.addCleanup(self.directory.cleanup)
        self.context_path = Path(self.directory.name) / 'private-context.json'
        self.write_context({'token': SECRET, 'socket': PRIVATE_SOCKET})

    def write_context(self, value):
        self.context_path.write_text(json.dumps(value))

    def assert_failure(self, result, code, status):
        self.assertIs(result.get('ok'), False)
        self.assertEqual(result.get('code'), code)
        self.assertEqual(result.get('status'), status)
        self.assertIsInstance(result.get('message'), str)
        self.assertTrue(result['message'])
        rendered = json.dumps(result)
        for private in (SECRET, PRIVATE_SOCKET, str(self.context_path), self.directory.name):
            self.assertNotIn(private, rendered)
        if code == 'UNKNOWN':
            self.assertIn('Do not retry or substitute', result['message'])
            self.assertIn('an action may have happened', result['message'])

    def invoke_with(self, connection=None, operation='inventory', payload=None):
        connection = connection or FakeSocket()
        with patch('agent.tenant_device.socket.socket', return_value=connection) as factory:
            result = invoke(self.context_path, operation, payload)
        self.assertLessEqual(factory.call_count, 1)
        self.assertLessEqual(len(connection.sends), 1)
        return result, connection, factory

    def test_missing_context_is_proven_unsent_and_private(self):
        self.context_path.unlink()
        result, connection, factory = self.invoke_with()
        self.assert_failure(result, 'FAILED', 'unsent')
        factory.assert_not_called()
        self.assertEqual(connection.sends, [])

    def test_context_read_failure_is_proven_unsent_and_private(self):
        with patch('agent.tenant_device.Path.read_text', side_effect=PermissionError(SENSITIVE_ERROR)):
            result, connection, factory = self.invoke_with()
        self.assert_failure(result, 'FAILED', 'unsent')
        factory.assert_not_called()
        self.assertEqual(connection.sends, [])

    def test_malformed_json_and_invalid_encoding_are_proven_unsent(self):
        for content in (b'{"token":"' + SECRET.encode(), b'\xff\xfe'):
            with self.subTest(content=content):
                self.context_path.write_bytes(content)
                result, connection, factory = self.invoke_with()
                self.assert_failure(result, 'FAILED', 'unsent')
                factory.assert_not_called()
                self.assertEqual(connection.sends, [])

    def test_invalid_context_shape_token_and_socket_never_send(self):
        valid = {'token': SECRET, 'socket': PRIVATE_SOCKET}
        invalid = [None, [], 'context', 3, {}, {'token': SECRET}, {'socket': PRIVATE_SOCKET}]
        for field in ('token', 'socket'):
            invalid.extend({**valid, field: value} for value in (None, False, 3, [], {}, ''))
        for context in invalid:
            with self.subTest(context=context):
                self.write_context(context)
                result, connection, _factory = self.invoke_with()
                self.assert_failure(result, 'FAILED', 'unsent')
                self.assertEqual(connection.sends, [])

    def test_invalid_selected_deadline_is_unsent(self):
        for field, operation, payload in (
            ('long_timeout', 'program-start', {'request_id': 'r', 'device_id': 'p', 'bpm': 90}),
            ('speech_timeout', 'call', {'request_id': 'r', 'device_id': 's', 'cap': 'say', 'args': {}}),
        ):
            for timeout in (True, None, '8', 0, -1, float('inf'), float('-inf'), float('nan')):
                with self.subTest(field=field, timeout=timeout):
                    self.write_context({'token': SECRET, 'socket': PRIVATE_SOCKET, field: timeout})
                    result, connection, _factory = self.invoke_with(operation=operation, payload=payload)
                    self.assert_failure(result, 'FAILED', 'unsent')
                    self.assertEqual(connection.sends, [])

    def test_serialization_and_size_failures_are_unsent(self):
        for payload in ({'unserializable': object()}, {'large': 'x' * MAX_BYTES}, ['invalid-payload']):
            with self.subTest(payload_type=type(payload).__name__):
                result, connection, factory = self.invoke_with(payload=payload)
                self.assert_failure(result, 'FAILED', 'unsent')
                factory.assert_not_called()
                self.assertEqual(connection.sends, [])

    def test_socket_creation_failure_is_unsent(self):
        with patch('agent.tenant_device.socket.socket', side_effect=OSError(SENSITIVE_ERROR)) as factory:
            result = invoke(self.context_path, 'inventory')
        self.assert_failure(result, 'FAILED', 'unsent')
        self.assertEqual(factory.call_count, 1)

    def test_socket_setup_and_connect_failures_are_unsent(self):
        for stage in ('enter', 'settimeout', 'connect'):
            with self.subTest(stage=stage):
                result, connection, factory = self.invoke_with(FakeSocket(failure=stage))
                self.assert_failure(result, 'FAILED', 'unsent')
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(connection.sends, [])

    def test_every_failure_once_sendall_may_run_is_unknown_and_never_replayed(self):
        for stage in ('sendall', 'partial-send', 'makefile', 'stream-enter', 'readline', 'stream-exit', 'exit'):
            with self.subTest(stage=stage):
                result, connection, factory = self.invoke_with(FakeSocket(failure=stage))
                self.assert_failure(result, 'UNKNOWN', 'unknown')
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(len(connection.sends), 1)
                if stage == 'partial-send':
                    self.assertEqual(len(connection.accepted), 1)
                    self.assertLess(len(connection.accepted[0]), len(connection.sends[0]))

    def test_invalid_replies_after_send_are_unknown(self):
        replies = (b'', b'{"ok":true}', b'{invalid}\n', b'\xff\n', b'[]\n',
                   b'{"ok":1}\n', b'{"message":"missing ok"}\n', b'{"ok":true}\n' + b'x' * MAX_BYTES)
        for reply in replies:
            with self.subTest(reply_prefix=reply[:25]):
                result, connection, factory = self.invoke_with(FakeSocket(reply=reply))
                self.assert_failure(result, 'UNKNOWN', 'unknown')
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(len(connection.sends), 1)
                self.assertEqual(connection.read_limits, [MAX_BYTES + 1])

    def test_valid_backend_success_and_failure_are_returned_unchanged(self):
        for response in ({'ok': True, 'result': {'on': True}, 'receipt': 'r'},
                         {'ok': False, 'code': 'DENIED', 'status': 'denied', 'message': 'Grant expired.'}):
            with self.subTest(response=response):
                result, connection, factory = self.invoke_with(
                    FakeSocket(reply=json.dumps(response).encode() + b'\n'))
                self.assertEqual(result, response)
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(len(connection.sends), 1)
                self.assertEqual(json.loads(connection.sends[0]), {'token': SECRET, 'operation': 'inventory'})

    def test_expected_deadline_selection_and_single_send(self):
        self.write_context({'token': SECRET, 'socket': PRIVATE_SOCKET, 'long_timeout': 151, 'speech_timeout': 23})
        for operation, payload, deadline in (
            ('inventory', None, 8), ('program-status', {'request_id': 'r', 'program_id': 'p'}, 151),
            ('light-blink', {'request_id': 'r', 'device_id': 'p'}, 151),
            ('photo-capture', {'request_id': 'r', 'source_device_id': 'p'}, 151),
            ('call', {'request_id': 'r', 'device_id': 's', 'cap': 'say', 'args': {}}, 23),
            ('call', {'request_id': 'r', 'device_id': 'p', 'cap': 'light', 'args': {'on': True}}, 8),
        ):
            with self.subTest(operation=operation, payload=payload):
                result, connection, _factory = self.invoke_with(operation=operation, payload=payload)
                self.assertTrue(result['ok'])
                self.assertEqual(connection.timeouts, [deadline])
                self.assertEqual(connection.addresses, [PRIVATE_SOCKET])
                self.assertEqual(len(connection.sends), 1)

    def test_main_invalid_stdin_and_schema_are_invalid_unsent_without_dispatch(self):
        invalid = ('{', '[]', '{}', '{"request_id":"r"}',
                   json.dumps({'request_id': 'r', 'device_id': 'p', 'cap': 'light', 'args': {}, 'extra': SECRET}),
                   'x' * (MAX_BYTES + 1))
        for stdin in invalid:
            with self.subTest(stdin_prefix=stdin[:25]), patch('sys.stdin', io.StringIO(stdin)), \
                    patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                    patch('agent.tenant_device.invoke') as dispatch:
                exit_code = main(['--context', str(self.context_path), 'call'])
                self.assertEqual(exit_code, 1)
                self.assert_failure(json.loads(stdout.getvalue()), 'INVALID', 'unsent')
                dispatch.assert_not_called()

    def test_main_preserves_invoke_uncertainty_and_nonzero_exit(self):
        result = {'ok': False, 'code': 'UNKNOWN', 'status': 'unknown',
                  'message': 'The helper result is unavailable. Do not retry or substitute; an action may have happened.'}
        with patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                patch('agent.tenant_device.invoke', return_value=result) as dispatch:
            exit_code = main(['--context', str(self.context_path), 'inventory'])
        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(stdout.getvalue()), result)
        dispatch.assert_called_once_with(str(self.context_path), 'inventory', None)

    def test_main_missing_context_prints_unsent_without_creating_socket(self):
        self.context_path.unlink()
        with patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                patch('agent.tenant_device.socket.socket') as factory:
            exit_code = main(['--context', str(self.context_path), 'inventory'])
        self.assertEqual(exit_code, 1)
        self.assert_failure(json.loads(stdout.getvalue()), 'FAILED', 'unsent')
        factory.assert_not_called()

    def test_main_unexpected_invocation_exception_is_unknown_and_private(self):
        with patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                patch('agent.tenant_device.invoke', side_effect=RuntimeError(SENSITIVE_ERROR)) as dispatch:
            exit_code = main(['--context', str(self.context_path), 'inventory'])
        self.assertEqual(exit_code, 1)
        self.assert_failure(json.loads(stdout.getvalue()), 'UNKNOWN', 'unknown')
        dispatch.assert_called_once_with(str(self.context_path), 'inventory', None)


if __name__ == '__main__':
    unittest.main()
