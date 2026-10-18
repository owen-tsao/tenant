"""Photon 2.0 beta is a second transport for the existing room conversation.

No model, prompt interpreter or native thread is created here. Durable inbound
claims are committed before ``core.agent.turn``; uncertain work is never replayed.
The private SQLite store contains identifiers and hashed handles, never messages.
See https://photon.codes/docs/beta/api-reference and the deployed OpenAPI schema.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from urllib.parse import quote

import httpx
from brain.state import PhotonBinding


class PhotonError(Exception):
    """Safe public error: never includes a credential, phone or response body."""
    def __init__(self, code='UNAVAILABLE', status=503):
        self.code, self.status = code, status
        messages = {
            'INVALID_PHONE': 'Enter a mobile number with its country code, such as +1 for the US.',
            'PHONE_IN_USE': 'This phone already has a room setup. Continue in the browser that started it, or choose Chat here.',
            'ALREADY_BOUND': 'This room session is already linked to another phone. Continue there, or choose Chat here.',
            'SETUP_UNCONFIRMED': 'The previous text setup is unconfirmed. Choose Chat here while the host checks it.',
            'UNKNOWN': 'Text setup could not be confirmed. Choose Chat here while the host checks it.',
            'GUEST_EXPIRED': 'This room access has ended. Scan the current room code to join again.',
            'INVITATION_EXPIRED': 'This room invitation has changed. Scan the current room code to join again.',
            'CAPACITY': 'Room texting is full right now. Choose Chat here.',
        }
        super().__init__(messages.get(code, 'Room texting is unavailable right now. Choose Chat here.'))


def phone_number(value):
    if not isinstance(value, str) or len(value) > 40:
        raise PhotonError('INVALID_PHONE', 400)
    value = re.sub(r'[ ()\-.]', '', value)
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', value):
        raise PhotonError('INVALID_PHONE', 400)
    return value


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Missing timezone')
    return parsed.timestamp()


class PhotonClient:
    """Small httpx equivalent of the repository's verified urllib beta spike.

    Deliberately no automatic retries. A 202 is acceptance, never delivery.
    """
    def __init__(self, project_id, api_key, *, transport=None):
        if not re.fullmatch(r'pho_prj_[0-7][0-9a-hjkmnp-tv-z]{25}', project_id or '') or not api_key:
            raise PhotonError('CONFIGURATION')
        self.project_id = project_id
        self.http = httpx.AsyncClient(
            base_url='https://api.photon.codes/v1/projects/' + project_id + '/',
            headers={'Authorization': 'Bearer ' + api_key, 'Accept': 'application/json',
                     'User-Agent': 'tenant-dubhacks/0.2 (+https://github.com/owen-tsao/tenant)'},
            timeout=10, follow_redirects=False, transport=transport)

    async def _request(self, method, path, *, expected=(200,), **kwargs):
        try:
            result = await self.http.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise PhotonError('UNKNOWN') from None
        if result.status_code not in expected:
            raise PhotonError('HTTP_' + str(result.status_code))
        try:
            body = result.json()
        except ValueError:
            raise PhotonError('UNREADABLE') from None
        if not isinstance(body, dict):
            raise PhotonError('UNREADABLE')
        return body

    async def assignments(self):
        records, token, seen = [], None, set()
        for _ in range(10):
            page = await self._request('GET', 'platforms/imessage/assignments',
                                       params={'pageSize': 100, **({'pageToken': token} if token else {})})
            items = page.get('assignments')  # Beta schema: not the old spike's `items`.
            if not isinstance(items, list):
                raise PhotonError('UNREADABLE')
            records.extend(items)
            token = page.get('nextPageToken')
            if not token:
                return records
            if not isinstance(token, str) or token in seen:
                raise PhotonError('PAGINATION')
            seen.add(token)
        raise PhotonError('TOO_MANY_PAGES')

    async def assign(self, handle, key):
        return await self._request('POST', 'platforms/imessage/assignments', expected=(201,),
                                   json={'handle': handle}, headers={'Idempotency-Key': key})

    async def release(self, assignment_id):
        try:
            result = await self.http.delete('platforms/imessage/assignments/' + quote(assignment_id, safe=''))
        except httpx.HTTPError:
            raise PhotonError('UNKNOWN') from None
        if result.status_code not in (200, 204, 404):
            raise PhotonError('HTTP_' + str(result.status_code))

    async def messages(self, query):
        return await self._request('GET', 'messages', params=query)

    async def send(self, space_id, sender_id, text, key):
        # Shared iMessage lines reject parentMessageId (verified repository spike).
        return await self._request('POST', 'messages', expected=(202,),
                                   json={'spaceId': space_id, 'senderId': sender_id,
                                         'content': {'type': 'text', 'format': 'plain', 'text': text}},
                                   headers={'Idempotency-Key': key})

    async def close(self):
        await self.http.aclose()


class PhotonStore:
    """Synchronous small transactions; commit is the native-execution boundary."""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bindings (
                handle_hash TEXT PRIMARY KEY, guest_id TEXT NOT NULL UNIQUE,
                assignment_id TEXT, agent_number TEXT, created_at REAL NOT NULL,
                owned INTEGER NOT NULL, state TEXT NOT NULL, request_key TEXT NOT NULL,
                space_id TEXT, sender_id TEXT, agent_id TEXT);
            CREATE TABLE IF NOT EXISTS claims (
                message_id TEXT PRIMARY KEY, guest_id TEXT NOT NULL,
                claimed_at REAL NOT NULL, outcome TEXT NOT NULL);
        ''')
        row = self.db.execute("SELECT value FROM settings WHERE key='salt'").fetchone()
        self.salt = row[0] if row else secrets.token_hex(32)
        self.db.execute("INSERT OR IGNORE INTO settings VALUES ('salt', ?)", (self.salt,))
        self.db.commit()

    def fingerprint(self, handle):
        return hmac.new(bytes.fromhex(self.salt), handle.encode(), hashlib.sha256).hexdigest()

    def binding(self, fingerprint):
        with self.lock:
            return self.db.execute('SELECT * FROM bindings WHERE handle_hash=?', (fingerprint,)).fetchone()

    def bindings(self):
        with self.lock:
            return list(self.db.execute('SELECT * FROM bindings'))

    def write(self, sql, args=()):
        with self.lock:
            try:
                self.db.execute(sql, args)
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def claim(self, message_id, guest_id, now):
        # Unique key and synchronous commit precede model execution or queueing.
        try:
            self.write('INSERT INTO claims VALUES (?, ?, ?, ?)', (message_id, guest_id, now, 'CLAIMED'))
            return True
        except sqlite3.IntegrityError:
            return False

    def outcome(self, message_id, value):
        self.write('UPDATE claims SET outcome=? WHERE message_id=?', (value, message_id))

    def close(self):
        with self.lock:
            self.db.close()


@dataclass(frozen=True)
class PhotonEnrollment:
    lease: object
    new_guest: bool
    imessage_number: str
    sms_link: str


class PhotonChannel:
    """One project poller, one bounded worker, one unchanged core agent.

    ``guest_id`` passed to enroll MUST have been authenticated by the HTTP caller.
    Without it, a genuinely new joining lease is created. Neither path activates
    a lease until Photon has supplied an actual matching received direct message.
    The same guest can keep using web chat; credential rotation is not performed.
    """
    def __init__(self, core, client, store_path, *, poll_interval=2, max_age=60, queue_size=8):
        self.core, self.client = core, client
        self.store = PhotonStore(store_path)
        self.poll_interval, self.max_age = max(2, poll_interval), max_age
        self.started_at = self.core.leases.clock()
        self.queue = asyncio.Queue(maxsize=queue_size)
        self._enroll_lock, self._poll_lock = asyncio.Lock(), asyncio.Lock()
        self._task, self._worker = None, None
        self._stopped, self._ready, self._closed = False, False, False
        self._page_query, self._page_token, self._page_tokens = None, None, set()
        self.healthy = True

    def _log(self, status, guest_id=None):
        self.core.log.append('photon', 'Room text-channel status was recorded.',
                             guest_id=guest_id, photon_status=status)

    def _live(self, row):
        return self.core.leases.current(row['guest_id'])

    def _can_reply(self, frames, lease):
        receipt = getattr(frames, 'completed_reply', None)
        return (receipt is not None and receipt.lease is lease
                and self.core.leases.current(lease.guest_id) is lease
                and self.core.agent.allows_reply(receipt))

    async def start(self):
        if self._task is not None:
            return
        if not hasattr(self.core.agent, 'allows_reply'):
            raise PhotonError('CONVERSATION_REQUIRED')
        await self.maintain()  # Orphan records never reconstruct or renew authority.
        self._ready = True
        self._worker = asyncio.create_task(self._consume())
        self._task = asyncio.create_task(self.run())

    def bound_guest(self, handle):
        """Return an identifier, never authority; the HTTP caller must verify it.

        Used only to recover this browser's own repeat enrollment when the
        unchanged phone form omits guest_id. A phone number alone grants nothing.
        """
        handle = phone_number(handle)
        row = self.store.binding(self.store.fingerprint(handle))
        return row['guest_id'] if row else None

    async def enroll(self, handle, *, guest_id=None, authorize=None):
        if not self.healthy or not self._ready or self._stopped:
            raise PhotonError('UNAVAILABLE')
        handle = phone_number(handle)
        fingerprint = self.store.fingerprint(handle)
        async with self._enroll_lock:
            if authorize is not None and not authorize():
                raise PhotonError('INVITATION_EXPIRED', 404)
            old = self.store.binding(fingerprint)
            lease = self.core.leases.current(guest_id) if guest_id else None
            if guest_id and lease is None:
                raise PhotonError('GUEST_EXPIRED', 403)
            if old:
                if old['state'] != 'active':
                    raise PhotonError('SETUP_UNCONFIRMED', 409)
                if lease is None or old['guest_id'] != guest_id or old['state'] != 'active' or not self._live(old):
                    raise PhotonError('PHONE_IN_USE', 409)
                return self._enrollment(lease, False, old['agent_number'])
            bindings = self.store.bindings()
            if guest_id and any(row['guest_id'] == guest_id for row in bindings):
                raise PhotonError('ALREADY_BOUND', 409)
            if len(bindings) >= 25:
                raise PhotonError('CAPACITY')
            # Read before allocating; preserve unrelated pre-existing assignments.
            assignments = await self.client.assignments()
            # The room may reset, or this exact linked lease may end, while
            # assignment preflight is waiting. Neither may mint fresh authority.
            if authorize is not None and not authorize():
                raise PhotonError('INVITATION_EXPIRED', 404)
            if guest_id and self.core.leases.current(guest_id) is not lease:
                raise PhotonError('GUEST_EXPIRED', 403)
            matches = [a for a in assignments if isinstance(a, dict) and a.get('handle') == handle
                       and not a.get('releasedAt')]
            if len(matches) > 1:
                raise PhotonError('AMBIGUOUS_ASSIGNMENT')
            new_guest = lease is None
            lease = lease or self.core.leases.create(channel='photon')
            now = self.core.leases.clock()
            key = 'tenant-enroll-' + secrets.token_hex(16)
            # Record intent before an allocation that can succeed without a response.
            self.store.write('INSERT INTO bindings (handle_hash,guest_id,created_at,owned,state,request_key) VALUES (?,?,?,?,?,?)',
                             (fingerprint, lease.guest_id, now, int(not matches), 'allocating', key))
            try:
                assignment = matches[0] if matches else await self.client.assign(handle, key)
                assignment_id, number = assignment.get('assignmentId'), assignment.get('assignedPhoneNumber')
                if (not isinstance(assignment_id, str) or not assignment_id
                        or assignment.get('projectId') != self.client.project_id
                        or assignment.get('platform') != 'imessage' or assignment.get('handle') != handle):
                    raise PhotonError('UNREADABLE_ASSIGNMENT')
                number = phone_number(number)
                self.store.write('UPDATE bindings SET assignment_id=?,agent_number=?,state=? WHERE handle_hash=?',
                                 (assignment_id, number, 'active', fingerprint))
                if (self.core.leases.current(lease.guest_id) is not lease
                        or (authorize is not None and not authorize())):
                    raise PhotonError('GUEST_EXPIRED')
                lease.photon = PhotonBinding(assignment_id, number, handle)
                return self._enrollment(lease, new_guest, number)
            except BaseException:
                if new_guest:
                    self.core.revoke(lease.guest_id)
                self.store.write("UPDATE bindings SET state='release_pending' WHERE handle_hash=?", (fingerprint,))
                raise

    def _enrollment(self, lease, new_guest, number):
        # Current Owen UI expects this exact response shape; code is convenience,
        # not a parser. The user's entire first real text reaches the same agent.
        body = quote('Hello Tenant', safe='')
        return PhotonEnrollment(lease, new_guest, number, 'sms:' + number + '?&body=' + body)

    async def maintain(self):
        """Best-effort owned seat cleanup; never delays local lease revocation."""
        for row in self.store.bindings():
            if row['state'] in ('active', 'allocating') and self._live(row):
                continue
            self.store.write("UPDATE bindings SET state='release_pending' WHERE handle_hash=?", (row['handle_hash'],))
            assignment_id = row['assignment_id']
            try:
                if row['owned'] and not assignment_id:
                    # A matching handle/time in an eventually-consistent list
                    # cannot prove our timed-out POST owns that assignment.
                    # Keep the durable intent for host reconciliation; do not
                    # retry the allocation or release another client's seat.
                    self._log('CLEANUP_UNCONFIRMED', row['guest_id'])
                    continue
                if row['owned'] and assignment_id:
                    await self.client.release(assignment_id)
                self.store.write('DELETE FROM bindings WHERE handle_hash=?', (row['handle_hash'],))
                self._log('RELEASED' if row['owned'] else 'DETACHED_PREEXISTING', row['guest_id'])
            except (PhotonError, ValueError):
                self._log('CLEANUP_UNCONFIRMED', row['guest_id'])

    def _matching(self, message):
        if not isinstance(message, dict):
            return None
        sent, received, space, content = (message.get(x) for x in ('sentBy', 'receivedBy', 'space', 'content'))
        if not all(isinstance(x, dict) for x in (sent, received, space, content)):
            return None
        if any(x.get('projectId') != self.client.project_id or x.get('platform') != 'imessage'
               for x in (message, sent, received, space)):
            return None
        try:
            handle = phone_number(sent.get('handle'))
            created = timestamp(message.get('createdAt'))
        except (PhotonError, ValueError):
            return None
        row = self.store.binding(self.store.fingerprint(handle))
        now = self.core.leases.clock()
        if (not row or row['state'] != 'active' or not self._live(row)
                or message.get('status') != 'received' or sent.get('kind') != 'human'
                or received.get('kind') != 'agent' or received.get('handle') != row['agent_number']
                or not isinstance(message.get('id'), str) or not message['id'].startswith('pho_msg_')
                or not isinstance(sent.get('id'), str) or not sent['id'].startswith('pho_usr_')
                or not isinstance(received.get('id'), str) or not received['id'].startswith('pho_usr_')
                or not isinstance(space.get('id'), str) or not space['id'].startswith('pho_spc_')
                or space.get('kind') != 'direct'
                or not isinstance(space.get('participantIds'), list)
                or len(space['participantIds']) != 2
                or not all(isinstance(item, str) for item in space['participantIds'])
                or sorted(space['participantIds']) != sorted([sent['id'], received['id']])
                or sent['id'] == received['id']
                or content.get('type') != 'text' or content.get('format') != 'plain'
                or not isinstance(content.get('text'), str) or not 0 < len(content['text'].strip()) <= 4000
                or created < max(self.started_at, row['created_at'], now - self.max_age) or created > now + 5):
            return None
        expected = (row['space_id'], row['sender_id'], row['agent_id'])
        actual = (space['id'], sent['id'], received['id'])
        if row['space_id'] and expected != actual:
            return None
        return row, actual

    async def poll_once(self):
        """Continue exact pagination before starting another overlapping time window."""
        async with self._poll_lock:
            if not self.healthy or self._stopped:
                return
            if self._page_query is None:
                now = self.core.leases.clock()
                self._page_query = {'createdSince': stamp(max(self.started_at, now - self.max_age)),
                                    'createdBefore': stamp(now + .001), 'direction': 'received',
                                    'order': 'asc', 'pageSize': 100, 'platform': 'imessage'}
            for _ in range(5):
                query = {**self._page_query, **({'pageToken': self._page_token} if self._page_token else {})}
                page = await self.client.messages(query)
                if not isinstance(page, dict) or not isinstance(page.get('items'), list):
                    raise PhotonError('UNREADABLE')
                for message in page['items']:
                    matched = self._matching(message)
                    if not matched:
                        continue
                    row, identity = matched
                    if not self.store.claim(message['id'], row['guest_id'], self.core.leases.clock()):
                        continue
                    if self.queue.full():
                        self.store.outcome(message['id'], 'DROPPED_BUSY')
                        self._log('BUSY', row['guest_id'])
                        continue
                    self.store.write('UPDATE bindings SET space_id=?,sender_id=?,agent_id=? WHERE handle_hash=?',
                                     (*identity, row['handle_hash']))
                    self.queue.put_nowait((message, row['guest_id']))
                token = page.get('nextPageToken')
                if not token:
                    self._page_query, self._page_token, self._page_tokens = None, None, set()
                    return
                if not isinstance(token, str) or token in self._page_tokens:
                    raise PhotonError('PAGINATION')
                self._page_tokens.add(token)
                self._page_token = token  # Empty pages may still have more data.

    async def process_one(self):
        message, guest_id = await self.queue.get()
        message_id = message['id']
        accepted = False
        try:
            if not self.healthy:
                return
            matched = self._matching(message)
            lease = self.core.leases.current(guest_id)
            if not matched or lease is None or matched[0]['guest_id'] != guest_id:
                self.store.outcome(message_id, 'PERMISSION')
                return
            # Exactly the same object as webchat, bound to the fixed native chat.
            frames = await self.core.agent.turn(guest_id, message['content']['text'])
            if not self._can_reply(frames, lease):
                self.store.outcome(message_id, 'PERMISSION')
                return
            text = '\n'.join(frame['text'] for frame in frames
                             if frame.get('type') == 'assistant' and isinstance(frame.get('text'), str))
            if not text or len(text) > 12000:
                self.store.outcome(message_id, 'UNSUPPORTED_REPLY')
                return
            # Mark before the send; cancellation/timeout after acceptance never resends.
            self.store.outcome(message_id, 'SENDING')
            # No await between live receipt check and starting this exact HTTP send.
            if not self._can_reply(frames, lease):
                self.store.outcome(message_id, 'PERMISSION')
                return
            await self.client.send(message['space']['id'], message['receivedBy']['id'], text,
                                           'tenant-reply-' + message_id)
            accepted = True
            self.store.outcome(message_id, 'ACCEPTED')
            self._log('ACCEPTED_NOT_DELIVERED', guest_id)
            if getattr(self.core, 'speech', None) is not None and self._can_reply(frames, lease):
                await self.core.speech.speak_reply(frames)
        except asyncio.CancelledError:
            self.store.outcome(message_id, 'ACCEPTED' if accepted else 'UNKNOWN')
            raise
        except sqlite3.Error:
            self.healthy = False
            self._log('STORAGE_UNAVAILABLE', guest_id)
        except Exception:
            self.store.outcome(message_id, 'ACCEPTED' if accepted else 'UNKNOWN')
            self._log('AUDIO_UNCONFIRMED' if accepted else 'UNKNOWN_NO_RETRY', guest_id)
        finally:
            self.queue.task_done()

    async def _consume(self):
        while not self._stopped and self.healthy:
            await self.process_one()

    async def run(self):
        try:
            while not self._stopped and self.healthy:
                if self._worker is not None and self._worker.done():
                    self.healthy = False
                    self._log('WORKER_UNAVAILABLE')
                    return
                try:
                    await self.maintain()
                    await self.poll_once()
                except PhotonError:
                    self._log('POLL_UNAVAILABLE')
                except (sqlite3.Error, OSError):
                    self.healthy = False
                    self._log('STORAGE_UNAVAILABLE')
                    return
                await asyncio.sleep(self.poll_interval)
        finally:
            self._ready = False

    async def close(self):
        if self._closed:
            return
        self._closed, self._stopped, self._ready = True, True, False
        tasks = [task for task in (self._task, self._worker) if task is not None]
        for task in tasks:
            task.cancel()
        try:
            # A previously failed task must not prevent settling its peer.
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            # Shutdown detaches local authority first; leases are not persisted.
            for row in self.store.bindings():
                self.store.write("UPDATE bindings SET state='release_pending' WHERE handle_hash=?", (row['handle_hash'],))
            with suppress(PhotonError):
                await self.maintain()
        finally:
            # Startup/storage failure must still close the HTTP pool and DB.
            try:
                await self.client.close()
            finally:
                self.store.close()
