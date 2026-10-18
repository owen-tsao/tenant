"""Private native-turn device helper. Standard library only; never retries."""
import argparse
import json
from pathlib import Path
import socket
import sys

MAX_BYTES = 16_384


def invoke(context_path, operation, payload=None):
    context = json.loads(Path(context_path).read_text())
    request = {'token': context['token'], 'operation': operation, **(payload or {})}
    encoded = json.dumps(request, separators=(',', ':')).encode() + b'\n'
    if len(encoded) > MAX_BYTES:
        raise ValueError('Request too large')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(8)
        connection.connect(context['socket'])
        connection.sendall(encoded)
        with connection.makefile('rb') as stream:
            line = stream.readline(MAX_BYTES + 1)
    if not line.endswith(b'\n') or len(line) > MAX_BYTES:
        raise ValueError('Invalid reply')
    response = json.loads(line)
    if not isinstance(response, dict) or type(response.get('ok')) is not bool:
        raise ValueError('Invalid reply')
    return response


def main(argv=None):
    parser = argparse.ArgumentParser(description='Use the current Tenant native-turn device grant.')
    parser.add_argument('--context', required=True)
    parser.add_argument('operation', choices=('inventory', 'call'))
    args = parser.parse_args(argv)
    try:
        payload = None
        if args.operation == 'call':
            text = sys.stdin.read(MAX_BYTES + 1)
            if len(text.encode()) > MAX_BYTES:
                raise ValueError('Request too large')
            payload = json.loads(text)
            if not isinstance(payload, dict) or set(payload) != {'request_id', 'device_id', 'cap', 'args'}:
                raise ValueError('Invalid call')
        result = invoke(args.context, args.operation, payload)
    except Exception:
        result = {'ok': False, 'code': 'UNKNOWN',
                  'message': 'The helper result is unavailable. Do not retry or substitute; an action may have happened.'}
    print(json.dumps(result, separators=(',', ':')))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
