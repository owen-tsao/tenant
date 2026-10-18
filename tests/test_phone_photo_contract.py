"""Actual candidate phone JS ↔ actual photo backend, with entirely fake I/O.

Node runs the candidate inline JS in a fake DOM/camera fixture. JSON lines stand
in for WebSocket and fetch. Pillow produces inert test JPEG bytes; no camera,
network listener, deployed service, model, browser, or physical viewer is used.
"""
import asyncio
import base64
from contextlib import suppress
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import unittest

from PIL import Image

from brain.core.bus import Bus
from brain.core.leases import Leases
from brain.core.photos import CAPTURE_ARGS, PhotoError, PhotoService
from brain.core.registry import Registry
from brain.state import Room


ROOT = Path(__file__).resolve().parents[1]


class PhonePhotoContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now, self.mono = 1000., 500.
        self.registry = Registry(Room('ROOM', 'Fake photo contract room'))
        self.registry.metadata.clock = lambda: self.now
        self.registry.metadata.monotonic = lambda: self.mono
        self.bus = Bus(self.registry)
        self.leases = Leases(self.registry.room, clock=lambda: self.now)
        self.lease = self.leases.create(scopes={'camera.capture', 'photo.show'})
        self.leases.current(self.lease.guest_id, activate=True)
        self.service = PhotoService(self.registry, self.bus, self.leases,
            authority=lambda lease, generation: lease is self.lease and generation == 7)
        self.registry.metadata.camera_ready = self.service.camera_ready
        output = BytesIO()
        Image.new('RGB', (32, 24), 'orange').save(output, 'JPEG')
        self.jpeg = output.getvalue()
        self.proc = await asyncio.create_subprocess_exec(shutil.which('node') or 'node',
            str(ROOT / 'tests/helpers/phone-photo-contract-worker.cjs'),
            cwd=ROOT, env=os.environ.copy(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.tasks = []
        await self.send({'op':'init', 'jpeg':base64.b64encode(self.jpeg).decode()})
        hello = (await self.event('socket'))['frame']
        self.assertEqual(hello['type'], 'hello')
        self.assertEqual(hello['caps']['camera.capture']['args'], CAPTURE_ARGS)
        owner = self
        class Socket:
            async def send_json(self, frame):
                await owner.send({'op':'frame', 'frame':frame})
        self.phone = self.registry.register(hello, Socket())
        self.phone.last_seen = self.mono
        self.service.configure(self.phone.id, 'fake-mac')
        self.viewer = self.service.enroll_viewer('fake-mac')
        await self.send({'op':'frame', 'frame':{'type':'welcome', 'room':'ROOM'}})
        consent = (await self.event('socket'))['frame']
        self.assertEqual(consent, {'type':'photo.consent','enabled':True,'ready':True})
        ack = self.service.device_event(self.phone, consent)
        await self.send({'op':'frame','frame':ack})

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done(): task.cancel()
            with suppress(asyncio.CancelledError): await task
        if getattr(self, 'proc', None):
            if self.proc.stdin: self.proc.stdin.close()
            try: await asyncio.wait_for(self.proc.wait(), 2)
            except TimeoutError:
                self.proc.kill()
                await self.proc.wait()
            stderr = (await self.proc.stderr.read()).decode()
            self.assertEqual(self.proc.returncode, 0, stderr)

    async def send(self, value):
        self.proc.stdin.write((json.dumps(value)+'\n').encode())
        await self.proc.stdin.drain()

    async def event(self, expected):
        line = await asyncio.wait_for(self.proc.stdout.readline(), 3)
        self.assertTrue(line, 'Fake phone worker ended unexpectedly')
        value = json.loads(line)
        self.assertEqual(value.get('event'), expected, value)
        return value

    async def begin(self, request_id='contract-request'):
        task = asyncio.create_task(self.service.capture(self.lease, request_id, self.phone.id, generation=7))
        self.tasks.append(task)
        upload = await self.event('upload')
        self.assertEqual(base64.b64decode(upload['body']), self.jpeg)
        capture_id = upload['url'].split('/')[-1]
        self.assertEqual(upload['url'], '/photos/uploads/'+capture_id)
        return task, upload, capture_id

    async def upload(self, upload, capture_id):
        headers = {key.lower(): value for key,value in upload['headers'].items()}
        self.assertEqual(headers['content-type'], 'image/jpeg')
        self.assertTrue(headers['authorization'].startswith('Bearer '))
        return await self.service.upload(capture_id, headers['authorization'][7:],
            base64.b64decode(upload['body']), headers['content-type'])

    async def test_candidate_one_frame_upload_ack_and_selected_viewer_receipt(self):
        task, upload, capture_id = await self.begin()
        stored = await self.upload(upload, capture_id)
        self.assertEqual((stored['state'],stored['stored'],stored['captured']), ('stored',True,False))
        self.assertIsNone(self.service.viewer_state(self.viewer)['photo'])
        await self.send({'op':'upload_response','number':upload['number'],'status':200,'body':stored})
        ack = (await self.event('socket'))['frame']
        self.assertEqual(ack['result'], {'capture_id':capture_id,'state':'captured'})
        self.bus.receive(self.phone, ack)
        captured = await asyncio.wait_for(task, 2)
        self.assertEqual((captured['state'],captured['captured'],captured['stored'],captured['displayed']), ('ready',True,True,False))
        photo = self.service.viewer_state(self.viewer)['photo']
        body = self.service.image(self.viewer, photo['photo_id'])
        with Image.open(BytesIO(body)) as image:
            self.assertEqual((image.format,image.size), ('JPEG',(32,24)))
        self.assertEqual(self.service.viewer_receipt(self.viewer, photo['photo_id'],photo['version'])['state'], 'displayed')
        duplicate = await self.service.capture(self.lease,'contract-request',self.phone.id,generation=7)
        self.assertEqual(duplicate['state'], 'displayed')
        await self.send({'op':'stats'})
        self.assertEqual(await self.event('stats'), {'event':'stats','draws':1,'uploads':1})

    async def test_remote_revoke_while_upload_pending_rejects_publication(self):
        await self.assert_pending_upload_invalidated('revoke')

    async def test_remote_host_reset_while_upload_pending_rejects_publication(self):
        await self.assert_pending_upload_invalidated('reset')

    async def assert_pending_upload_invalidated(self, transition):
        task, upload, capture_id = await self.begin(transition+'-request')
        if transition == 'revoke':
            self.leases.revoke(self.lease.guest_id)
            self.service.invalidate_guest(self.lease.guest_id)
        else:
            # Actual synchronous PhotoService host-reset fence; no Core hook
            # is mocked or claimed exercised by this isolated contract test.
            self.service.reset()
        with self.assertRaises(PhotoError) as caught:
            await self.upload(upload,capture_id)
        self.assertEqual(caught.exception.code, 'STALE')
        await self.send({'op':'upload_response','number':upload['number'],'status':410,
            'body':{'ok':False,'code':'STALE','message':'Photo authority ended.'}})
        ack = (await self.event('socket'))['frame']
        self.assertEqual(ack['type'], 'err')
        self.bus.receive(self.phone, ack)
        result = await asyncio.wait_for(task, 2)
        self.assertEqual(result['state'], 'cancelled')
        self.assertFalse(result['stored'])
        self.assertFalse(result['displayed'])
        self.assertIsNone(self.service.viewer_state(self.viewer)['photo'])
        await self.send({'op':'stats'})
        self.assertEqual(await self.event('stats'), {'event':'stats','draws':1,'uploads':1})
