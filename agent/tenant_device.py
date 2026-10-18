"""Private native-turn device helper. Standard library only; never retries."""
import argparse
import json
import math
from pathlib import Path
import socket
import sys

MAX_BYTES = 16_384


def unavailable(*, sent):
    if not sent:
        return {'ok': False, 'code': 'FAILED', 'status': 'unsent',
                'message': 'The helper could not send this request. Nothing was sent.'}
    return {'ok': False, 'code': 'UNKNOWN', 'status': 'unknown',
            'message': 'The helper result is unavailable. Do not retry or substitute; an action may have happened.'}


def invoke(context_path, operation, payload=None):
    send_started = False
    try:
        context = json.loads(Path(context_path).read_text())
        if (not isinstance(context, dict) or not isinstance(context.get('token'), str)
                or not context['token'] or not isinstance(context.get('socket'), str)
                or not context['socket']):
            raise ValueError('Invalid helper context')
        request = {'token': context['token'], 'operation': operation, **(payload or {})}
        encoded = json.dumps(request, separators=(',', ':')).encode() + b'\n'
        if len(encoded) > MAX_BYTES:
            raise ValueError('Request too large')
        timeout = context.get('long_timeout', 122) if operation in ('light-blink', 'photo-capture', 'question-answer') or operation.startswith(('program-', 'demo-photo-')) else 8
        if operation == 'call' and isinstance(payload, dict) and payload.get('cap') == 'say':
            timeout = context.get('speech_timeout', 17)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Invalid helper deadline')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(context['socket'])
            # sendall may transmit a prefix before raising. From this point on,
            # failure cannot prove that the controller received no request.
            send_started = True
            connection.sendall(encoded)
            with connection.makefile('rb') as stream:
                line = stream.readline(MAX_BYTES + 1)
        if not line.endswith(b'\n') or len(line) > MAX_BYTES:
            raise ValueError('Invalid reply')
        response = json.loads(line)
        if not isinstance(response, dict) or type(response.get('ok')) is not bool:
            raise ValueError('Invalid reply')
        return response
    except Exception:
        return unavailable(sent=send_started)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Use the current Tenant native-turn device grant.')
    parser.add_argument('--context', required=True)
    parser.add_argument('operation', choices=('inventory', 'call', 'light-blink', 'program-start',
                                             'program-update', 'program-stop', 'program-status', 'reply-voice',
                                             'photo-capture', 'photo-status', 'demo-photo-prepare',
                                             'demo-photo-capture', 'demo-photo-cancel', 'demo-photo-status',
                                             'question-answer', 'question-answer-stop'))
    args = parser.parse_args(argv)
    try:
        payload = None
        if args.operation != 'inventory':
            text = sys.stdin.read(MAX_BYTES + 1)
            if len(text.encode()) > MAX_BYTES:
                raise ValueError('Request too large')
            payload = json.loads(text)
            valid = (isinstance(payload, dict) and (
                (args.operation in ('question-answer', 'question-answer-stop') and set(payload) == {'request_id'}) or
                (args.operation in ('demo-photo-prepare', 'demo-photo-status') and set(payload) == {'request_id'}) or
                (args.operation in ('demo-photo-capture', 'demo-photo-cancel') and set(payload) == {'request_id', 'photo_id'}
                 and isinstance(payload['photo_id'], str)) or
                (args.operation == 'photo-capture' and set(payload) == {'request_id', 'source_device_id'}) or
                (args.operation == 'photo-status' and set(payload) == {'request_id', 'capture_request_id'}) or
                (args.operation == 'call' and set(payload) == {'request_id', 'device_id', 'cap', 'args'}) or
                (args.operation == 'light-blink' and {'request_id', 'device_id'} <= set(payload)
                 and set(payload) <= {'request_id', 'device_id', 'count'}) or
                (args.operation == 'reply-voice' and type(payload.get('enabled')) is bool
                 and isinstance(payload.get('request_id'), str)
                 and ((payload['enabled'] is False and set(payload) == {'request_id', 'enabled'})
                      or (payload['enabled'] is True
                          and set(payload) == {'request_id', 'enabled', 'device_id', 'speaker_ref'}
                          and isinstance(payload['device_id'], str) and isinstance(payload['speaker_ref'], str)))) or
                (args.operation == 'program-start' and set(payload) in (
                    {'request_id', 'device_id', 'bpm'}, {'request_id', 'device_id', 'song_id'})) or
                (args.operation == 'program-update' and set(payload) == {'request_id', 'program_id', 'visual'}
                 and type(payload.get('visual')) is bool) or
                (args.operation == 'program-update' and {'request_id', 'program_id'} < set(payload)
                 and set(payload) <= {'request_id', 'program_id', 'bpm', 'light_device_id', 'remove_light_device_id', 'light_beats_per_state'}
                 and ('light_beats_per_state' not in payload or 'light_device_id' in payload)) or
                (args.operation in ('program-stop', 'program-status') and set(payload) == {'request_id', 'program_id'})))
            if not valid:
                raise ValueError('Invalid call')
    except Exception:
        result = {'ok': False, 'code': 'INVALID', 'status': 'unsent',
                  'message': 'Invalid helper input. Nothing was sent.'}
    else:
        try:
            result = invoke(args.context, args.operation, payload)
        except Exception:
            # An unexpected invocation failure has no proven transport stage.
            result = unavailable(sent=True)
    print(json.dumps(result, separators=(',', ':')))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
