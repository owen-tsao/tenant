'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {fixture,photo,deferred,settle}=require('./helpers/device-photo-fixture.cjs');
const results=(f,req='p1')=>f.sockets.flatMap(ws=>ws.sent).filter(frame=>frame.req===req);
const positive=(f,req='p1')=>results(f,req).filter(frame=>frame.type==='ok');
const argsSpec={capture_id:{type:'string'},upload_url:{type:'string'},upload_token:{type:'string'}};
const stored=id=>({ok:true,status:200,json:async()=>({ok:true,capture_id:id,stored:true,state:'stored'})});

test('Join clearly explains room photo consent; permission state alone neither enrolls nor captures',async()=>{
  const f=fixture();
  const visible=f.html.split('<script>')[0];
  assert.match(visible,/Join[\s\S]*photo|photo[\s\S]*Join/i);
  assert.doesNotMatch(visible,/no photos are taken/i);
  await settle();assert.equal(f.sockets.length,0);assert.equal(f.permissionRequests,0);assert.equal(f.draws.length,0);assert.equal(f.uploads.length,0);
  await f.join();assert.equal(f.permissionRequests,1);assert.equal(f.draws.length,0);assert.equal(f.uploads.length,0);f.leave();
});
test('hello advertises exact capture arguments, plus torch only when proven',async()=>{
  for(const torch of [true,false,[false],[true],[false,true]]){
    const f=fixture({torch});await f.join();assert.equal(f.sockets.length,1);
    const caps=f.sockets[0].sent[0].caps;
    assert.deepEqual(caps['camera.capture'].args,argsSpec);
    assert.deepEqual(Object.keys(caps).sort(),torch===true||Array.isArray(torch)&&torch.includes(true)&&torch.includes(false)?['camera.capture','light']:['camera.capture']);
    assert.equal(f.uploads.length,0);assert.equal(f.draws.length,0);f.leave();
  }
});
test('camera denial or insecure context never enrolls or claims consent',async()=>{
  for(const options of [{denied:true},{secure:false}]){const f=fixture(options);await f.join();assert.equal(f.sockets.length,0);assert.equal(f.uploads.length,0);assert.equal(f.draws.length,0);assert.equal(f.document.body.dataset.state,'error');}
});
test('welcome sends consent readiness; capture waits for exact successful server acknowledgement',async()=>{
  for(const ack of [null,{type:'photo.consent',ok:false},{type:'photo.consent',ok:true,revision:0,enabled:true,ready:true},{type:'photo.consent',ok:true,revision:1,enabled:false,ready:false}]){
    const f=fixture();await f.join();assert.equal(f.sockets[0].sent.some(x=>x.type==='photo.consent'),false);
    f.frame({type:'welcome',room:'ROOM'});await settle();assert.deepEqual(f.sockets[0].sent.find(x=>x.type==='photo.consent'),{type:'photo.consent',enabled:true,ready:true});
    if(ack)f.frame(ack);f.frame(photo('unready'));await settle();assert.equal(f.draws.length,0);assert.equal(f.uploads.length,0);
    if(ack){f.frame({type:'photo.consent',ok:true,revision:2,enabled:true,ready:true});f.frame(photo('unsolicited'));await settle();assert.equal(f.draws.length,0);f.track.unmute();}
    f.frame({type:'photo.consent',ok:true,revision:2,enabled:true,ready:true});f.frame(photo());await settle();assert.equal(positive(f).length,1);f.leave();
  }
});
test('finite still pipeline draws once, bounds pixels, uploads JPEG privately, acknowledges only stored matching photo',async()=>{
  const upload=deferred();const f=fixture({width:4000,height:3000,fetch:()=>upload.promise});await f.ready();f.frame(photo());await settle();
  assert.equal(f.draws.length,1);assert.equal(f.permissionRequests,1);assert.equal(f.uploads.length,1);assert.equal(positive(f).length,0);
  assert.ok(Math.max(f.canvas.width,f.canvas.height)<=1280);assert.ok(f.canvas.width>0&&f.canvas.height>0);assert.ok(Math.abs(f.canvas.width/f.canvas.height-4/3)<.01);
  const {url,init}=f.uploads[0];assert.equal(new URL(url,'https://tenant.test').href,'https://tenant.test/photos/uploads/capture_1');
  assert.equal(init.method,'POST');assert.equal(init.credentials,'omit');assert.equal(init.redirect,'error');assert.equal(init.headers.Authorization??init.headers.authorization,'Bearer ticket-secret');assert.equal(init.headers['Content-Type']??init.headers['content-type'],'image/jpeg');assert.equal(init.body.type,'image/jpeg');assert.ok(init.body.size<=5*1024*1024);assert.ok(init.signal);
  upload.resolve(stored('capture_1'));await settle();assert.deepEqual(positive(f)[0].result,{capture_id:'capture_1',state:'captured'});assert.equal(f.constraints.length,0);f.leave();
});
test('duplicate request and duplicate capture id never take another frame or upload',async()=>{
  const upload=deferred();const f=fixture({fetch:()=>upload.promise});await f.ready();f.frame(photo());f.frame(photo());await settle();assert.equal(f.draws.length,1);assert.equal(f.uploads.length,1);
  upload.resolve(stored('capture_1'));await settle();f.frame(photo());f.frame(photo('another-request'));await settle();assert.equal(f.draws.length,1);assert.equal(f.uploads.length,1);assert.ok(positive(f).length>=1);f.leave();
});
test('wrong origins, paths, ticket fields and extra arguments fail before shutter',async()=>{
  const variants=[{upload_url:'https://evil.test/photos/uploads/capture_1'},{upload_url:'//evil.test/photos/uploads/capture_1'},{upload_url:'/photos/uploads/other'},{upload_url:'/photos/uploads/capture_1?leak=x'},{upload_url:'/photos/uploads/capture_1#x'},{upload_url:'/photos/uploads/%63apture_1'},{upload_token:''},{capture_id:'../escape'},{extra:true}];
  const f=fixture();await f.ready();for(let i=0;i<variants.length;i++)f.frame(photo('invalid'+i,{args:{...photo().args,...variants[i]}}));await settle();assert.equal(f.draws.length,0);assert.equal(f.uploads.length,0);assert.equal(positive(f).length,0);f.leave();
});
test('oversized or non-JPEG encoder result never uploads or reports captured',async()=>{
  for(const options of [{blobSize:0},{blobSize:5*1024*1024+1},{blobType:'image/png'},{encode:cb=>cb(null)}]){const f=fixture(options);await f.ready();f.frame(photo());await settle();assert.equal(f.uploads.length,0);assert.equal(positive(f).length,0);assert.equal(results(f).at(-1).type,'err');f.leave();}
});
test('upload rejection, mismatched receipt or incomplete stored receipt never acknowledges captured',async()=>{
  const replies=[{ok:false,status:403,json:async()=>({})},{ok:true,status:200,json:async()=>({ok:true,capture_id:'wrong',stored:true,state:'stored'})},{ok:true,status:200,json:async()=>({ok:true,capture_id:'capture_1',state:'stored'})},{ok:true,status:200,json:async()=>({ok:true,capture_id:'capture_1',stored:true,state:'pending'})}];
  for(const reply of replies){const f=fixture({fetch:async()=>reply});await f.ready();f.frame(photo());await settle();assert.equal(f.uploads.length,1);assert.equal(positive(f).length,0);assert.equal(results(f).at(-1).type,'err');f.leave();}
});
test('torch and photo share one busy guard without changing the existing track',async()=>{
  const action=deferred();const f=fixture({apply:()=>action.promise});await f.ready();f.frame({type:'do',req:'torch',cap:'light',args:{on:true},epoch:1,deadline_ms:1000});await settle();f.frame(photo());await settle();assert.equal(f.draws.length,0);assert.equal(results(f).at(-1).code,'BUSY');assert.equal(f.permissionRequests,1);action.resolve();await settle();f.leave();
});
test('photo timeout during JPEG encoding cannot upload or acknowledge after late callback, or recapture',async()=>{
  let encode;const f=fixture({encode:cb=>{encode=cb;}});await f.ready();f.frame(photo('p1',{deadline_ms:10}));await settle();await f.advance(11);assert.equal(positive(f).length,0);assert.equal(results(f).at(-1).code,'UNKNOWN');encode(new Blob(['late'],{type:'image/jpeg'}));await settle();f.frame(photo());f.frame(photo('new-request-same-capture'));await settle();assert.equal(f.draws.length,1);assert.equal(f.uploads.length,0);assert.equal(positive(f).length,0);assert.equal(positive(f,'new-request-same-capture').length,0);f.leave();
});
test('photo timeout during upload aborts and never acknowledges a late successful receipt',async()=>{
  const upload=deferred();const f=fixture({fetch:()=>upload.promise});await f.ready();f.frame(photo('p1',{deadline_ms:10}));await settle();await f.advance(11);assert.equal(results(f).at(-1).code,'UNKNOWN');assert.equal(f.uploads[0].init.signal.aborted,true);upload.resolve(stored('capture_1'));await settle();assert.equal(positive(f).length,0);f.frame(photo());await settle();assert.equal(f.uploads.length,1);f.leave();
});
for(const transition of ['close','leave','ended','mute','pagehide','higher epoch'])test(`${transition} invalidates pending encoding before any upload or positive acknowledgement`,async()=>{
  let encode;const f=fixture({encode:cb=>{encode=cb;}});await f.ready();f.frame(photo());await settle();assert.equal(f.draws.length,1);
  if(transition==='close')f.disconnect();
  else if(transition==='leave')f.leave();
  else if(transition==='ended'){f.track.readyState='ended';f.track.ended();}
  else if(transition==='mute')f.track.mute();
  else if(transition==='pagehide')f.windowEvents.pagehide();
  else f.frame({type:'do',req:'new-epoch',cap:'light',args:{on:false},epoch:2,deadline_ms:1000});
  encode(new Blob(['late'],{type:'image/jpeg'}));await settle();assert.equal(f.uploads.length,0);assert.equal(positive(f).length,0);f.leave();
});
test('disconnect during upload aborts and reconnect requires a new consent ack, never replays the old still',async()=>{
  const upload=deferred();const f=fixture({fetch:()=>upload.promise});await f.ready();f.frame(photo());await settle();f.disconnect();assert.equal(f.uploads[0].init.signal.aborted,true);upload.resolve(stored('capture_1'));await settle();await f.advance(500);assert.equal(f.sockets.length,2);const ws=f.sockets[1];ws.onopen();f.frame({type:'welcome',room:'ROOM'},ws);await settle();f.frame(photo(),ws);await settle();assert.equal(f.draws.length,1);assert.equal(f.uploads.length,1);assert.equal(positive(f).length,0);assert.deepEqual(ws.sent.find(x=>x.type==='photo.consent'),{type:'photo.consent',enabled:true,ready:true});f.leave();
});

test('leave, track loss, page close and higher epoch abort in-flight upload and fence late storage success',async()=>{
  for(const transition of ['leave','ended','mute','pagehide','higher epoch']){
    const upload=deferred();const f=fixture({fetch:()=>upload.promise});await f.ready();f.frame(photo());await settle();assert.equal(f.uploads.length,1);
    if(transition==='leave')f.leave();
    else if(transition==='ended'){f.track.readyState='ended';f.track.ended();}
    else if(transition==='mute')f.track.mute();
    else if(transition==='pagehide')f.windowEvents.pagehide();
    else f.frame({type:'do',req:'later',cap:'light',args:{on:false},epoch:2,deadline_ms:1000});
    assert.equal(f.uploads[0].init.signal.aborted,true,transition);upload.resolve(stored('capture_1'));await settle();assert.equal(positive(f).length,0,transition);f.leave();
  }
});

test('leaving while permission or video playback is pending cannot enroll later',async()=>{
  for(const stage of ['acquire','play']){const gate=deferred();const f=fixture({[stage]:()=>gate.promise});const joining=f.join();await settle();f.leave();gate.resolve();await joining;await settle();assert.equal(f.sockets.length,0,stage);assert.equal(f.track.readyState,'ended',stage);assert.equal(f.uploads.length,0);}
});
test('capture capability waits for a real positive-dimension ready video frame',async()=>{
  const f=fixture({videoReadyState:1,width:0,height:0});const joining=f.join();await settle();assert.equal(f.sockets.length,0);
  f.video.readyState=2;f.video.videoWidth=1280;f.video.videoHeight=720;f.videoEvents.loadeddata?.();await joining;await settle();assert.equal(f.sockets.length,1);assert.ok(f.sockets[0].sent[0].caps['camera.capture']);assert.equal(f.draws.length,0);f.leave();
});
test('hidden page denies stale consent success and never takes a frame',async()=>{
  const f=fixture();await f.ready();f.document.visibilityState='hidden';f.documentEvents.visibilitychange();
  assert.deepEqual(f.sockets[0].sent.filter(x=>x.type==='photo.consent').at(-1),{type:'photo.consent',enabled:true,ready:false});
  f.frame({type:'photo.consent',ok:true,revision:1,enabled:true,ready:true});f.frame(photo());await settle();assert.equal(f.draws.length,0);assert.equal(f.uploads.length,0);f.leave();
});
test('hidden page aborts pending encoding, then visible page needs a new acknowledged ready state',async()=>{
  let encode;const f=fixture({encode:cb=>{encode=cb;}});await f.ready();f.frame(photo());await settle();f.document.visibilityState='hidden';f.documentEvents.visibilitychange();encode(new Blob(['late'],{type:'image/jpeg'}));await settle();assert.equal(f.uploads.length,0);assert.equal(positive(f).length,0);
  f.document.visibilityState='visible';f.documentEvents.visibilitychange();f.frame(photo('before-ack',{args:{...photo().args,capture_id:'capture_2',upload_url:'/photos/uploads/capture_2'}}));await settle();assert.equal(f.draws.length,1);f.leave();
});
test('camera-only device completes the still pipeline while rejecting unproven torch control',async()=>{
  const f=fixture({torch:false});await f.ready();f.frame({type:'do',req:'torch',cap:'light',args:{on:true},epoch:1,deadline_ms:1000});await settle();assert.equal(results(f,'torch').at(-1).code,'UNSUPPORTED');assert.equal(f.constraints.length,0);f.frame(photo());await settle();assert.equal(f.draws.length,1);assert.equal(f.uploads.length,1);assert.equal(positive(f).length,1);f.leave();
});
test('video frame readiness timeout enrolls only proven torch, or no device when torch is absent',async()=>{
  for(const torch of [true,false]){const f=fixture({torch,videoReadyState:1,width:0,height:0});const joining=f.join();await settle();assert.equal(f.sockets.length,0);await f.advance(10001);await joining;await settle();if(torch){assert.deepEqual(Object.keys(f.sockets[0].sent[0].caps),['light']);f.frame({type:'welcome',room:'ROOM'});await settle();assert.equal(f.sockets[0].sent.some(x=>x.type==='photo.consent'),false);}else assert.equal(f.sockets.length,0);assert.equal(f.draws.length,0);f.leave();}
});

test('mute and unmute coalesce behind an outstanding readiness handshake without accepting its old success',async()=>{
  const f=fixture();await f.join();f.frame({type:'welcome',room:'ROOM'});await settle();
  f.track.muted=true;f.track.mute();f.track.muted=false;f.track.unmute();
  assert.equal(f.sockets[0].sent.filter(x=>x.type==='photo.consent').length,1);
  f.frame({type:'photo.consent',ok:true,revision:1,enabled:true,ready:true});f.frame(photo('stale-ack'));await settle();assert.equal(f.draws.length,0);assert.equal(f.sockets[0].sent.filter(x=>x.type==='photo.consent').length,2);
  f.frame({type:'photo.consent',ok:true,revision:1,enabled:true,ready:true});f.frame(photo());await settle();assert.equal(positive(f).length,1);f.leave();
});
test('mute handshake drains before unmute readiness can authorize another photo',async()=>{
  const f=fixture();await f.ready();f.track.muted=true;f.track.mute();f.track.muted=false;f.track.unmute();
  assert.deepEqual(f.sockets[0].sent.filter(x=>x.type==='photo.consent').at(-1),{type:'photo.consent',enabled:true,ready:false});
  f.frame({type:'photo.consent',ok:true,revision:2,enabled:true,ready:false});f.frame(photo('before-new-ready'));await settle();assert.equal(f.draws.length,0);
  assert.deepEqual(f.sockets[0].sent.filter(x=>x.type==='photo.consent').at(-1),{type:'photo.consent',enabled:true,ready:true});
  f.frame({type:'photo.consent',ok:true,revision:3,enabled:true,ready:true});f.frame(photo());await settle();assert.equal(positive(f).length,1);f.leave();
});
test('leave then rejoin completes while an old permission request is unresolved, and releases its late stream',async()=>{
  const old=deferred(),oldTrack={readyState:'live',stop(){this.readyState='ended';}};
  const f=fixture({acquire:({stream,call})=>call===1?old.promise:stream});const first=f.join();await settle();f.leave();await first;await f.join();assert.equal(f.sockets.length,1);assert.equal(f.track.readyState,'live');
  old.resolve({getTracks:()=>[oldTrack],getVideoTracks:()=>[oldTrack]});await settle();assert.equal(oldTrack.readyState,'ended');assert.equal(f.track.readyState,'live');assert.equal(f.sockets.length,1);f.leave();
});

test('authorized capture waits for a subsequent video frame callback before drawing',async()=>{
  let fresh;const f=fixture({freshFrame:cb=>{fresh=cb;}});await f.ready();f.frame(photo());await settle();assert.equal(typeof fresh,'function');assert.equal(f.draws.length,0);assert.equal(f.uploads.length,0);assert.equal(positive(f).length,0);
  fresh();await settle();assert.equal(f.draws.length,1);assert.equal(f.uploads.length,1);assert.equal(positive(f).length,1);f.leave();
});
test('missing fresh frame reaches deadline as known FAILED with no shutter and cancels its callback',async()=>{
  let fresh;const f=fixture({freshFrame:cb=>{fresh=cb;}});await f.ready();f.frame(photo('p1',{deadline_ms:10}));await settle();await f.advance(11);
  assert.equal(f.draws.length,0);assert.equal(f.uploads.length,0);assert.equal(results(f).at(-1).code,'FAILED');assert.ok(f.frameCancels.length>=1);
  fresh();await settle();assert.equal(f.draws.length,0);assert.equal(f.uploads.length,0);assert.equal(positive(f).length,0);f.leave();
});
test('late fresh frame callback after Leave cannot take or upload a photo',async()=>{
  let fresh;const f=fixture({freshFrame:cb=>{fresh=cb;}});await f.ready();f.frame(photo());await settle();f.leave();assert.ok(f.frameCancels.length>=1);fresh();await settle();assert.equal(f.draws.length,0);assert.equal(f.uploads.length,0);assert.equal(positive(f).length,0);
});
test('browsers without frame callbacks require observed media-time progress after command',async()=>{
  const f=fixture({frameCallbacks:false});await f.ready();f.frame(photo());await settle();assert.equal(f.draws.length,0);
  f.videoEvents.timeupdate?.();await settle();assert.equal(f.draws.length,0);
  f.video.currentTime+=1/30;f.videoEvents.timeupdate?.();await settle();assert.equal(f.draws.length,1);assert.equal(f.uploads.length,1);assert.equal(positive(f).length,1);f.leave();
});
test('fallback positive dimensions without media-time progress time out before shutter',async()=>{
  const f=fixture({frameCallbacks:false});await f.ready();f.frame(photo('p1',{deadline_ms:10}));await settle();f.videoEvents.timeupdate?.();await f.advance(11);assert.equal(f.draws.length,0);assert.equal(f.uploads.length,0);assert.equal(results(f).at(-1).code,'FAILED');
  f.video.currentTime+=1/30;f.videoEvents.timeupdate?.();await settle();assert.equal(f.draws.length,0);assert.equal(f.uploads.length,0);assert.equal(positive(f).length,0);f.leave();
});
