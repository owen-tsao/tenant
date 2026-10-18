"""Explicit local demo services, detached from a chat's command session.

Usage: python scripts/runtime.py start|status|stop brain|audio|tunnel
Logs and process ownership records stay private in .venv/tenant-runtime/.
This does not install a login item or schedule a recurring task.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / '.venv' / 'tenant-runtime'


class InspectionError(RuntimeError):
    pass


def identity(pid):
    try:
        result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart=,command='],
                                capture_output=True, text=True, timeout=2)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
            return None
        raise InspectionError('Process inspection failed; ownership record preserved.')
    except (OSError, subprocess.TimeoutExpired):
        raise InspectionError('Process inspection unavailable; ownership record preserved.') from None


def group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        raise InspectionError('Process group could not be inspected; ownership record preserved.') from None


def inspect(saved):
    if not saved:
        return False
    actual = identity(saved['pid'])
    if saved.get('identity') and actual == saved['identity']:
        return True
    if not actual or not saved.get('identity'):
        if group_alive(saved['pid']):
            raise InspectionError('A service group remains active without verified identity; ownership record preserved.')
    return False


def save(record, data):
    record.write_text(json.dumps(data) + '\n')
    record.chmod(0o600)


def rollback(process, record):
    # This is the new session we just created, never an arbitrary saved PID.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return  # Keep the provisional record for explicit recovery.
    try:
        if not group_alive(process.pid):
            record.unlink(missing_ok=True)
    except InspectionError:
        pass


def commands():
    uv = shutil.which('uv')
    return {
        'brain': [uv, 'run', '--env-file', '.env', '.venv/bin/python', '-m', 'uvicorn',
                  'brain.main:app', '--host', '127.0.0.1', '--port', '8000',
                  '--no-access-log', '--log-level', 'warning'],
        'audio': [uv, 'run', '--env-file', '.env', '.venv/bin/python', 'agent/laptop.py'],
        'tunnel': [shutil.which('cloudflared'), 'tunnel', '--no-autoupdate', '--url',
                   'http://127.0.0.1:8000', '--protocol', 'http2'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'status', 'stop'))
    parser.add_argument('service', choices=('brain', 'audio', 'tunnel'))
    args = parser.parse_args()
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    record = STATE / (args.service + '.json')
    saved = json.loads(record.read_text()) if record.exists() else None
    owned = inspect(saved)
    if args.action == 'status':
        print(json.dumps({'service': args.service, 'running': owned,
                          'stopping': bool(owned and saved.get('stopping'))}))
        return
    if args.action == 'stop':
        if owned:
            if os.getpgid(saved['pid']) != saved['pid']:
                raise SystemExit('Process ownership changed; refusing to stop it.')
            os.killpg(saved['pid'], signal.SIGTERM)
            saved['stopping'] = True
            save(record, saved)
            if inspect(saved):
                print(args.service + ': stopping; still running')
                return
        record.unlink(missing_ok=True)
        print(args.service + ': stopped' if owned else args.service + ': already stopped')
        return
    if owned:
        print(args.service + ': already running')
        return
    command = commands()[args.service]
    if not command[0]:
        raise SystemExit('Required executable is unavailable; nothing started.')
    log = STATE / (args.service + '.log')
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True, close_fds=True)
    try:
        save(record, {'pid': process.pid, 'identity': None})
        time.sleep(.15)
        if process.poll() is not None:
            raise InspectionError('Service launcher exited during startup.')
        signature = identity(process.pid)
        if not signature:
            raise InspectionError('Could not verify the started process.')
        save(record, {'pid': process.pid, 'identity': signature})
    except (OSError, InspectionError):
        rollback(process, record)
        raise SystemExit(args.service + ': startup verification failed; new process stopped or its recovery record retained.') from None
    print(args.service + ': started')


if __name__ == '__main__':
    try:
        main()
    except InspectionError as exc:
        raise SystemExit(str(exc)) from None
