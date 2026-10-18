import asyncio
import unittest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from brain.core.registry import Registry, DeviceAlreadyConnected
from brain.core.bus import Bus
from brain.state import Room
from brain.main import create_app
from brain.config import Config


def hello(id='phone', room='TEST'):
    return {'type':'hello','id':id,'label':id,'room':room,'caps':{'light':{'description':'torch','args':{'on':{'type':'boolean'}}}}}

class Socket:
    def __init__(self): self.frames=[]; self.sent=asyncio.Event()
    async def send_json(self, frame): self.frames.append(frame); self.sent.set()

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry=Registry(Room('TEST','Test')); self.bus=Bus(self.registry)
        self.ws=Socket(); self.dev=self.registry.register(hello(),self.ws)
    def call(self, **kw):
        return asyncio.create_task(self.bus.call('phone','light',{'on':True},timeout=.1,authorize=lambda *a:True,**kw))
    async def test_registration_room_duplicate_and_empty_manifest(self):
        with self.assertRaises(ValueError) as bad: self.registry.register(hello(room='WRONG'),Socket())
        self.assertNotIsInstance(bad.exception, DeviceAlreadyConnected)
        with self.assertRaises(DeviceAlreadyConnected): self.registry.register(hello(),Socket())
        self.bus.disconnect(self.dev)
        frame=hello(); frame['caps']={}
        self.assertEqual(self.registry.register(frame,Socket()).caps,{})
    async def test_correlation_wrong_request_and_wrong_device(self):
        task=self.call(); await self.ws.sent.wait(); req=self.ws.frames[0]['req']
        other=self.registry.register(hello('other'),Socket())
        self.bus.receive(other,{'type':'ok','req':req,'result':{}})
        self.bus.receive(self.dev,{'type':'ok','req':'wrong','result':{}})
        self.assertFalse(task.done())
        self.bus.receive(self.dev,{'type':'ok','req':req,'result':{'on':True}})
        self.assertTrue((await task).ok)
        self.bus.receive(self.dev,{'type':'err','req':req,'code':'FAILED','message':'late'})
        self.assertFalse(self.bus.pending)
    async def test_serialization(self):
        first=self.call(); await self.ws.sent.wait(); second=self.call(); await asyncio.sleep(.005)
        self.assertEqual(len(self.ws.frames),1)
        self.bus.receive(self.dev,{'type':'ok','req':self.ws.frames[0]['req'],'result':{}})
        self.assertTrue((await first).ok)
        await asyncio.sleep(.005); self.assertEqual(len(self.ws.frames),2)
        self.bus.receive(self.dev,{'type':'ok','req':self.ws.frames[1]['req'],'result':{}})
        self.assertTrue((await second).ok)
    async def test_quarantine_until_valid_late_reply(self):
        self.assertEqual((await self.call()).code,'UNKNOWN')
        req=self.ws.frames[0]['req']
        self.assertEqual((await self.call()).code,'UNKNOWN'); self.assertEqual(len(self.ws.frames),1)
        self.bus.receive(self.dev,{'type':'ok','req':req})
        self.assertEqual((await self.call()).code,'UNKNOWN'); self.assertEqual(len(self.ws.frames),1)
        self.bus.receive(self.dev,{'type':'ok','req':req,'result':{'on':True}})
        nextcall=self.call(); await asyncio.sleep(.005)
        self.assertEqual(len(self.ws.frames),2)
        self.bus.receive(self.dev,{'type':'ok','req':self.ws.frames[-1]['req'],'result':{}})
        self.assertTrue((await nextcall).ok)
    async def test_canonical_light_schema(self):
        for args in ({'on':{'type':'string'}},{'toggle':{'type':'boolean'}},{'on':{'type':'boolean','minimum':'bad'}}):
            frame=hello('bad'); frame['caps']['light']['args']=args
            with self.assertRaises(ValueError): self.registry.register(frame,Socket())
    async def test_timeout_unknown_no_resend(self):
        result=await self.call(); self.assertEqual(result.code,'UNKNOWN')
        await asyncio.sleep(.005); self.assertEqual(len(self.ws.frames),1); self.assertFalse(self.bus.pending)
    async def test_queued_timeout_not_sent(self):
        first=self.call(); await self.ws.sent.wait()
        result=await self.bus.call('phone','light',{'on':False},timeout=.005,authorize=lambda *a:True)
        self.assertEqual(result.code,'TIMEOUT'); self.assertEqual(len(self.ws.frames),1)
        self.assertEqual((await first).code,'UNKNOWN')
    async def test_permission_checked_after_queue(self):
        first=self.call(); await self.ws.sent.wait(); allowed=True
        second=asyncio.create_task(self.bus.call('phone','light',{'on':False},authorize=lambda *a:allowed))
        await asyncio.sleep(.005); allowed=False
        self.bus.receive(self.dev,{'type':'ok','req':self.ws.frames[0]['req'],'result':{}})
        await first; self.assertEqual((await second).code,'PERMISSION'); self.assertEqual(len(self.ws.frames),1)
    async def test_invalid_cap_args_and_absent_permission(self):
        for cap,args,code in [('nope',{},'UNSUPPORTED'),('light',{'on':1},'INVALID'),('light',{'on':True,'extra':0},'INVALID'),('light',{},'INVALID'),('light',{'on':True},'PERMISSION')]:
            result=await self.bus.call('phone',cap,args)
            self.assertEqual(result.code,code)
        self.assertEqual(self.ws.frames,[])
    async def test_disconnect_reconnect_never_migrates_queue(self):
        first=self.call(); await self.ws.sent.wait(); second=self.call(); await asyncio.sleep(.005)
        self.bus.disconnect(self.dev); newws=Socket(); newdev=self.registry.register(hello(),newws)
        self.assertEqual((await first).code,'UNKNOWN'); self.assertEqual((await second).code,'OFFLINE')
        self.assertEqual(newws.frames,[]); self.assertTrue(newdev.online)

class EndpointTests(unittest.TestCase):
    def setUp(self):
        # HTTP calls and device sockets must share the app's single event loop.
        self.client = self.enterContext(TestClient(create_app(Config('device-secret','host-secret','TEST'))))
    def test_device_token_required(self):
        for suffix in ('','?t=wrong'):
            with self.assertRaises(WebSocketDisconnect) as caught:
                with self.client.websocket_connect('/ws/device'+suffix): pass
            self.assertEqual(caught.exception.code, 1008)
    def test_hello_welcome_ping_protocol(self):
        with self.client.websocket_connect('/ws/device?t=device-secret') as ws:
            ws.send_json(hello()); frame=ws.receive_json()
            self.assertEqual(frame['type'],'welcome'); self.assertEqual(frame['room'],'TEST')
            ws.send_json({'type':'pong'})
    def test_invalid_room_and_manifest_are_terminal_even_with_connected_id(self):
        with self.client.websocket_connect('/ws/device?t=device-secret') as original:
            original.send_json(hello()); original.receive_json()
            invalid = hello(); invalid['caps']['light']['args'] = {'on': {'type': 'string'}}
            for frame in (hello(room='BAD'), invalid):
                with self.client.websocket_connect('/ws/device?t=device-secret') as rejected:
                    rejected.send_json(frame)
                    with self.assertRaises(WebSocketDisconnect) as caught: rejected.receive_json()
                    self.assertEqual(caught.exception.code, 1008)
            self.assertTrue(self.client.app.state.registry.devices['phone'].online)

    def test_duplicate_is_retryable_preserves_original_queue_and_can_join_after_close(self):
        from concurrent.futures import ThreadPoolExecutor
        headers = {'Authorization': 'Bearer host-secret'}
        app = self.client.app
        with self.client.websocket_connect('/ws/device?t=device-secret') as original, ThreadPoolExecutor(max_workers=2) as pool:
            original.send_json(hello()); self.assertEqual(original.receive_json()['type'], 'welcome')
            device = app.state.registry.devices['phone']
            first = pool.submit(self.client.post, '/host/do', headers=headers,
                                json={'device_id': 'phone', 'cap': 'light', 'args': {'on': True}})
            pending = original.receive_json()
            second = pool.submit(self.client.post, '/host/do', headers=headers,
                                 json={'device_id': 'phone', 'cap': 'light', 'args': {'on': False}})
            with self.client.websocket_connect('/ws/device?t=device-secret') as duplicate:
                duplicate.send_json(hello())
                with self.assertRaises(WebSocketDisconnect) as caught: duplicate.receive_json()
                self.assertEqual(caught.exception.code, 1013)
                self.assertIn('already connected', caught.exception.reason)
            self.assertIs(app.state.registry.devices['phone'], device)
            self.assertTrue(device.online)
            self.assertIs(app.state.bus.pending[pending['req']][0], device)
            original.send_json({'type': 'ok', 'req': pending['req'], 'result': {'on': True}})
            queued = original.receive_json()
            self.assertEqual(queued['args'], {'on': False})
            self.assertNotEqual(queued['req'], pending['req'])
            original.send_json({'type': 'ok', 'req': queued['req'], 'result': {'on': False}})
            self.assertEqual(first.result(2).json(), {'ok': True, 'result': {'on': True}})
            self.assertEqual(second.result(2).json(), {'ok': True, 'result': {'on': False}})
            self.assertIs(app.state.registry.devices['phone'], device)
        self.assertFalse(device.online)
        with self.client.websocket_connect('/ws/device?t=device-secret') as rejoined:
            rejoined.send_json(hello())
            self.assertEqual(rejoined.receive_json()['type'], 'welcome')
            self.assertIsNot(app.state.registry.devices['phone'], device)
            self.assertTrue(app.state.registry.devices['phone'].online)
    def test_host_do_reaches_device_and_correlates(self):
        from concurrent.futures import ThreadPoolExecutor
        with self.client.websocket_connect('/ws/device?t=device-secret') as ws:
            ws.send_json(hello()); self.assertEqual(ws.receive_json()['type'],'welcome')
            with ThreadPoolExecutor(max_workers=1) as pool:
                response=pool.submit(self.client.post,'/host/do',json={'device_id':'phone','cap':'light','args':{'on':False}},headers={'Authorization':'Bearer host-secret'})
                frame=ws.receive_json()
                self.assertEqual(frame['type'],'do'); self.assertEqual(frame['args'],{'on':False})
                ws.send_json({'type':'ok','req':frame['req'],'result':{'on':False}})
                self.assertEqual(response.result(timeout=2).json(),{'ok':True,'result':{'on':False}})
    def test_host_auth_and_validation(self):
        body={'device_id':'phone','cap':'light','args':{'on':True}}
        self.assertEqual(self.client.post('/host/do',json=body).status_code,403)
        headers={'Authorization':'Bearer host-secret'}
        self.assertEqual(self.client.post('/host/do',json=body,headers=headers).json()['code'],'OFFLINE')
        self.assertEqual(self.client.post('/host/do',json={'device_id':'phone','cap':'sound'},headers=headers).status_code,400)


class HeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_pong_marks_offline(self):
        from brain.ws.devices import device_socket
        class WS:
            query_params={'t':'secret'}
            def __init__(self): self.count=0; self.frames=[]; self.closed=asyncio.Event()
            async def accept(self): pass
            async def receive_json(self):
                self.count+=1
                if self.count==1: return hello()
                await self.closed.wait()
                raise WebSocketDisconnect()
            async def send_json(self,frame): self.frames.append(frame)
            async def close(self,code=1000): self.closed.set()
        ws=WS(); registry=Registry(Room('TEST','Test')); bus=Bus(registry)
        await asyncio.wait_for(device_socket(ws,Config('secret','host','TEST'),registry,bus,heartbeat=.01),.2)
        self.assertFalse(registry.devices['phone'].online)
        self.assertTrue(any(f['type']=='ping' for f in ws.frames))

    async def test_ping_send_failure_marks_offline(self):
        from brain.ws.devices import device_socket
        class WS:
            query_params={'t':'secret'}
            def __init__(self): self.count=0; self.closed=asyncio.Event()
            async def accept(self): pass
            async def receive_json(self):
                self.count+=1
                if self.count==1: return hello()
                await self.closed.wait()
                raise WebSocketDisconnect()
            async def send_json(self,frame):
                if frame['type']=='ping': raise OSError('connection lost')
            async def close(self,code=1000): self.closed.set()
        ws=WS(); registry=Registry(Room('TEST','Test')); bus=Bus(registry)
        await asyncio.wait_for(device_socket(ws,Config('secret','host','TEST'),registry,bus,heartbeat=.01),.2)
        self.assertFalse(registry.devices['phone'].online)


if __name__=='__main__': unittest.main()
