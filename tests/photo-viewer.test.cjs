'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {createPhotoViewer} = require('../agent/photo_viewer.js');

const SECRET = 'private-test-host-token';
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a; reject=b;}); return {promise,resolve,reject}; };
const tick = async () => { for(let i=0;i<25;i++) await Promise.resolve(); };
const photo = (id='p1', version=3, stateVersion=7) => ({ok:true, version:stateVersion, pending:true, photo:{photo_id:id, version, image_url:'/photos/images/'+id, captured_at:1, source_label:'Phone'}});
const empty = (version=0) => ({ok:true, version, photo:null, pending:false});
const json = (value, status=200) => ({ok:status>=200 && status<300, status, json:async()=>value, headers:{get:()=>null}});
const jpeg = (size=100, type='image/jpeg') => ({ok:true,status:200,headers:{get:n=>n.toLowerCase()==='content-type'?type:null},blob:async()=>({size,type})});

function harness(extra={}) {
  const states=[], images=[], receipts=[], calls=[], log=[], rafs=new Map(), timers=new Map(), revoked=[], created=[];
  let nextId=1, tokenReads=0, latestState=empty(0);
  const mount={children:[],isConnected:true,replaceChildren(...nodes){this.children=nodes; log.push(['mount',...nodes]);},contains(node){return this.children.includes(node);}};
  const listeners=new Map();
  const doc={addEventListener(n,fn){listeners.set(n,fn);},removeEventListener(n,fn){if(listeners.get(n)===fn)listeners.delete(n);},visibilityState:'visible',hidden:false,defaultView:{getComputedStyle:()=>({display:'block',visibility:'visible',opacity:'1'})},createElement:()=>makeImage()};
  function makeImage(){
    const spec=images.shift() || {};
    const img={naturalWidth:640,naturalHeight:480,isConnected:true,style:{},alt:'',setAttribute(k,v){this[k]=v;},remove(){mount.children=mount.children.filter(n=>n!==this);},getBoundingClientRect:()=>({width:640,height:480}),decode(){log.push(['decode',this]); return spec.decode ? spec.decode() : Promise.resolve();},...spec};
    return img;
  }
  const opts={viewerId:'mac-viewer',mount,document:doc,createImage:makeImage,
    createObjectURL(blob){const url='blob:test-'+nextId++;created.push(url);log.push(['objectURL',url]);return url;},
    revokeObjectURL(url){revoked.push(url);},
    requestAnimationFrame(fn){const id=nextId++;rafs.set(id,fn);return id;},cancelAnimationFrame(id){rafs.delete(id);},
    setTimeout(fn,delay){const id=nextId++;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},
    isVisible(img,node){return doc.visibilityState==='visible' && node.children.includes(img) && img.visible!==false;},
    getHostToken(){tokenReads++;return SECRET;},
    async fetch(url,init={}) {
      calls.push({url,init});log.push(['fetch',url]);
      if(url==='/host/photos/viewer') return extra.enrollment || json({ok:true,viewer_id:'mac-viewer'});
      let item;
      if(url==='/photos/viewer/state') item=states.length ? states.shift() : json(latestState);
      else if(url.startsWith('/photos/images/')) item=receiptsImage.length ? receiptsImage.shift() : jpeg();
      else if(url==='/photos/viewer/receipt') {
        const body=JSON.parse(init.body);
        item=receipts.length ? receipts.shift() : json({ok:true,state:'displayed',photo_id:body.photo_id,version:body.version});
      } else throw new Error('Unexpected URL');
      if(typeof item==='function') return item(url,init);
      return await item;
    },...extra.options};
  const receiptsImage=[];
  const viewer=createPhotoViewer(opts);
  return {viewer,opts,states,images,receipts,imageResponses:receiptsImage,calls,log,mount,doc,rafs,timers,revoked,created,
    get tokenReads(){return tokenReads;},
    state(v){latestState=v;states.push(json(v));},
    count(url){return calls.filter(c=>c.url===url).length;},
    async frame(){await tick();const pending=[...rafs];rafs.clear();for(const [,fn] of pending)fn(1);await tick();},
    async painted(){await tick();for(let i=0;i<8 && rafs.size;i++)await this.frame();await viewer.whenIdle();await tick();},
  };
}
async function started(h, state=empty()) {h.state(state);await h.viewer.start();await tick();return h;}
async function rendered(h, state=photo()) {await started(h,state);await h.painted();return h;}

// These tests use only synthetic documents, local promises and fake HTTP responses.
// No browser, camera, network, real timers or device commands are involved.
test('creation is inert and inactive polling cannot fetch', async()=>{
  const h=harness();assert.equal(h.calls.length,0);assert.equal(h.timers.size,0);assert.equal(h.tokenReads,0);
  await h.viewer.pollOnce();assert.equal(h.calls.length,0);assert.equal(h.viewer.status().active,false);
});

test('cookie-only start never obtains or propagates a host token', async()=>{
  const h=await rendered(harness());assert.equal(h.tokenReads,0);
  assert.equal(h.count('/host/photos/viewer'),0);
  for(const {url,init} of h.calls){assert.equal(init.credentials,'same-origin');assert.equal(init.redirect,'error');assert.equal(init.cache,'no-store');assert.equal(new Headers(init.headers).has('authorization'),false);assert.ok(!url.includes(SECRET));}
  h.viewer.stop();
});

test('explicit enrollment uses bearer once then uses cookie requests only', async()=>{
  const h=harness();h.state(photo());await h.viewer.start({enroll:true});await h.painted();
  assert.equal(h.count('/host/photos/viewer'),1);assert.equal(h.tokenReads,1);
  const first=h.calls[0];assert.equal(first.url,'/host/photos/viewer');assert.equal(first.init.method,'POST');
  assert.equal(new Headers(first.init.headers).get('authorization'),'Bearer '+SECRET);assert.deepEqual(JSON.parse(first.init.body),{viewer_id:'mac-viewer'});
  for(const c of h.calls.slice(1))assert.equal(new Headers(c.init.headers).has('authorization'),false);
  assert.ok(!JSON.stringify(h.viewer.status()).includes(SECRET));assert.ok(!JSON.stringify(h.mount).includes(SECRET));h.viewer.stop();
});

test('failed enrollment stops before state or image access and sanitizes errors', async()=>{
  const h=harness({enrollment:json({ok:false,message:SECRET},403)});await h.viewer.start({enroll:true});await tick();
  assert.equal(h.calls.length,1);assert.equal(h.viewer.status().active,false);assert.equal(h.viewer.status().phase,'unavailable');
  assert.ok(!JSON.stringify(h.viewer.status()).includes(SECRET));assert.equal(h.mount.children.length,0);
});

test('receipt follows decode, mount, visibility and two separate paint opportunities', async()=>{
  const decode=deferred(),h=harness();h.images.push({decode:()=>decode.promise});await started(h,photo('camera-pic',4,99));
  assert.equal(h.count('/photos/viewer/receipt'),0);assert.equal(h.mount.children.length,0);
  decode.resolve();await tick();assert.equal(h.mount.children.length,1);assert.equal(h.count('/photos/viewer/receipt'),0);
  await h.frame();assert.equal(h.count('/photos/viewer/receipt'),0);
  await h.frame();await h.viewer.whenIdle();
  assert.equal(h.count('/photos/viewer/receipt'),1);
  const receipt=h.calls.find(c=>c.url==='/photos/viewer/receipt');assert.deepEqual(JSON.parse(receipt.init.body),{photo_id:'camera-pic',version:4});
  assert.equal(h.viewer.status().phase,'displayed');assert.equal(h.viewer.status().photoId,'camera-pic');h.viewer.stop();
});

test('polling can apply authoritative reset while decode is still pending', async()=>{
  const decode=deferred(),h=harness();h.images.push({decode:()=>decode.promise});await started(h,photo('old',1,10));
  h.state(empty(11));await h.viewer.pollOnce();assert.equal(h.mount.children.length,0);
  decode.resolve();await h.painted();assert.equal(h.count('/photos/viewer/receipt'),0);assert.equal(h.mount.children.length,0);
  assert.equal(h.viewer.status().stateVersion,11);h.viewer.stop();
});

test('newer photo wins over late completion of older decode', async()=>{
  const decode=deferred(),h=harness();h.images.push({decode:()=>decode.promise});await started(h,photo('old',1,10));
  h.state(photo('new',2,11));await h.viewer.pollOnce();await h.painted();decode.resolve();await tick();
  assert.equal(h.viewer.status().photoId,'new');assert.equal(h.count('/photos/viewer/receipt'),1);
  assert.deepEqual(JSON.parse(h.calls.find(c=>c.url==='/photos/viewer/receipt').init.body),{photo_id:'new',version:2});h.viewer.stop();
});

test('older state cannot clear or regress a displayed image', async()=>{
  const h=await rendered(harness(),photo('current',5,20)),committed=h.mount.children[0];
  h.state(empty(19));await h.viewer.pollOnce();await tick();assert.equal(h.mount.children[0],committed);assert.equal(h.viewer.status().stateVersion,20);
  assert.equal(h.count('/photos/viewer/receipt'),1);h.viewer.stop();
});

for(const failure of ['fetch','decode','hidden','zero-dimensions'])test('previous committed image survives '+failure+' failure without receipt',async()=>{
  const h=await rendered(harness(),photo('previous',1,10)),committed=h.mount.children[0];
  if(failure==='fetch')h.imageResponses.push(Promise.reject(new Error('private-fetch-'+SECRET)));
  if(failure==='decode')h.images.push({decode:()=>Promise.reject(new Error('private-decode-'+SECRET))});
  if(failure==='hidden')h.images.push({visible:false});
  if(failure==='zero-dimensions')h.images.push({naturalWidth:0,naturalHeight:0});
  h.state(photo('candidate',2,11));await h.viewer.pollOnce();await h.painted();
  assert.equal(h.mount.children[0],committed);assert.equal(h.count('/photos/viewer/receipt'),1);assert.ok(!JSON.stringify(h.viewer.status()).includes(SECRET));h.viewer.stop();
});

for(const url of ['https://example.test/photos/images/p1','//example.test/photos/images/p1','/photos/images/p1?token=secret','/photos/images/p1#secret','/photos/images/other','/photos/images/../p1','/photos/images/%70%31','javascript:alert(1)'])test('rejects untrusted image URL '+url,async()=>{
  const h=harness(),s=photo();s.photo.image_url=url;await started(h,s);await h.painted();
  assert.equal(h.calls.filter(c=>c.url.startsWith('/photos/images/')).length,0);assert.equal(h.count('/photos/viewer/receipt'),0);assert.equal(h.mount.children.length,0);h.viewer.stop();
});

for(const bad of [jpeg(5*1024*1024+1),jpeg(20,'text/html')])test('oversized or non-JPEG response never renders or acknowledges',async()=>{
  const h=harness();h.imageResponses.push(bad);await started(h,photo());await h.painted();
  assert.equal(h.count('/photos/viewer/receipt'),0);assert.equal(h.mount.children.length,0);h.viewer.stop();
});

test('hidden document has no receipt even if decode succeeds',async()=>{
  const h=harness();h.doc.visibilityState='hidden';await started(h,photo());await h.painted();
  assert.equal(h.count('/photos/viewer/receipt'),0);assert.equal(h.mount.children.length,0);h.viewer.stop();
});

test('authoritative newer null state clears mounted image and its object URL',async()=>{
  const h=await rendered(harness(),photo('p1',4,10));assert.equal(h.mount.children.length,1);
  h.state(empty(11));await h.viewer.pollOnce();await tick();assert.equal(h.mount.children.length,0);assert.ok(h.revoked.includes(h.created[0]));h.viewer.stop();
});

test('unknown receipt outcome is never automatically posted twice for the same photo',async()=>{
  const h=harness();h.receipts.push(()=>Promise.reject(new Error('receipt response lost '+SECRET)));await rendered(h,photo('p1',3,10));
  assert.equal(h.count('/photos/viewer/receipt'),1);assert.notEqual(h.viewer.status().phase,'displayed');
  h.state(photo('p1',3,11));await h.viewer.pollOnce();await h.painted();assert.equal(h.count('/photos/viewer/receipt'),1);
  assert.ok(!JSON.stringify(h.viewer.status()).includes(SECRET));h.viewer.stop();
});

test('stale receipt response does not claim display and permits state re-poll',async()=>{
  const h=harness();h.receipts.push(json({ok:false,code:'STALE'},409));await rendered(h,photo('p1',3,10));
  assert.notEqual(h.viewer.status().phase,'displayed');h.state(empty(11));await h.viewer.pollOnce();await h.painted();
  assert.equal(h.mount.children.length,0);assert.equal(h.count('/photos/viewer/receipt'),1);h.viewer.stop();
});

test('false or malformed receipt success cannot become displayed',async()=>{
  const h=harness();h.receipts.push(json({ok:true,state:'stored',photo_id:'p1',version:3}));await rendered(h);
  assert.notEqual(h.viewer.status().phase,'displayed');h.viewer.stop();
});

test('stop aborts pending image work, cancels scheduling, revokes URLs and suppresses late receipt',async()=>{
  const decode=deferred(),h=harness();h.images.push({decode:()=>decode.promise});await started(h,photo());
  const signals=h.calls.map(c=>c.init.signal).filter(Boolean);assert.ok(signals.length);
  h.viewer.stop();decode.resolve();await tick();assert.equal(h.viewer.status().active,false);assert.equal(h.viewer.status().phase,'stopped');
  assert.equal(h.mount.children.length,0);assert.equal(h.rafs.size,0);assert.equal(h.timers.size,0);assert.equal(h.count('/photos/viewer/receipt'),0);
  assert.ok(signals.some(s=>s.aborted));for(const u of h.created)assert.ok(h.revoked.includes(u));
  const count=h.calls.length;await h.viewer.pollOnce();assert.equal(h.calls.length,count);
});

test('failed candidate does not relabel retained image or suppress a later successful load',async()=>{
  const h=await rendered(harness(),photo('previous',1,10)),committed=h.mount.children[0];
  h.images.push({decode:()=>Promise.reject(new Error('decode unavailable'))});h.state(photo('candidate',2,11));
  await h.viewer.pollOnce();await h.painted();assert.equal(h.mount.children[0],committed);
  h.state(photo('candidate',2,11));await h.viewer.pollOnce();await h.painted();
  assert.notEqual(h.mount.children[0],committed);assert.equal(h.count('/photos/images/candidate'),2);
  assert.equal(h.count('/photos/viewer/receipt'),2);assert.equal(h.viewer.status().phase,'displayed');h.viewer.stop();
});

test('becoming invisible after first paint opportunity prevents receipt and restores retained photo',async()=>{
  const h=await rendered(harness(),photo('previous',1,10)),committed=h.mount.children[0];
  h.state(photo('candidate',2,11));await h.viewer.pollOnce();await tick();await h.frame();
  h.mount.children[0].visible=false;await h.frame();await h.viewer.whenIdle();
  assert.equal(h.mount.children[0],committed);assert.equal(h.count('/photos/viewer/receipt'),1);h.viewer.stop();
});

test('stopping between paint opportunities cancels remaining frame and receipt',async()=>{
  const h=await started(harness(),photo());assert.equal(h.rafs.size,1);await h.frame();assert.equal(h.rafs.size,1);
  h.viewer.stop();await h.viewer.whenIdle();assert.equal(h.rafs.size,0);assert.equal(h.count('/photos/viewer/receipt'),0);
});

test('fresh prepaint HTTP state reset suppresses stale DOM paint and receipt',async()=>{
  const decode=deferred(),h=harness();h.images.push({decode:()=>decode.promise});await started(h,photo('stale',1,10));
  h.state(empty(11));decode.resolve();await h.painted();
  assert.ok(h.count('/photos/viewer/state')>=2);assert.equal(h.mount.children.length,0);
  assert.equal(h.count('/photos/viewer/receipt'),0);assert.equal(h.viewer.status().stateVersion,11);h.viewer.stop();
});

test('fresh prereceipt HTTP state reset suppresses receipt after paint opportunities',async()=>{
  const h=await started(harness(),photo('stale',1,10));
  assert.equal(h.mount.children.length,1);assert.equal(h.count('/photos/viewer/receipt'),0);
  h.state(empty(11));await h.painted();
  assert.ok(h.count('/photos/viewer/state')>=3);assert.equal(h.count('/photos/viewer/receipt'),0);
  assert.equal(h.mount.children.length,0);assert.equal(h.viewer.status().stateVersion,11);h.viewer.stop();
});

test('fresh prereceipt HTTP authorization failure suppresses receipt and restores committed image',async()=>{
  const h=await rendered(harness(),photo('previous',1,10)),committed=h.mount.children[0];
  h.state(photo('candidate',2,11));await h.viewer.pollOnce();await tick();assert.notEqual(h.mount.children[0],committed);
  h.states.push(json({ok:false,code:'PHOTO_AUTH_REQUIRED'},403));await h.painted();
  assert.equal(h.count('/photos/viewer/receipt'),1);assert.equal(h.mount.children[0],committed);
  assert.notEqual(h.viewer.status().phase,'displayed');h.viewer.stop();
});

test('fresh prepaint HTTP authorization failure cannot reuse cached local authority',async()=>{
  const decode=deferred(),h=harness();h.images.push({decode:()=>decode.promise});await started(h,photo('pending',1,10));
  h.states.push(json({ok:false,code:'PHOTO_AUTH_REQUIRED'},403));decode.resolve();await h.painted();
  assert.equal(h.mount.children.length,0);assert.equal(h.count('/photos/viewer/receipt'),0);assert.notEqual(h.viewer.status().phase,'displayed');h.viewer.stop();
});

test('invalid JSON in fresh prereceipt state is not proof of continued authorization',async()=>{
  const h=await started(harness(),photo('pending',1,10));
  h.states.push({ok:true,status:200,json:async()=>{throw new Error('private JSON '+SECRET);}});await h.painted();
  assert.equal(h.count('/photos/viewer/receipt'),0);assert.equal(h.mount.children.length,0);
  assert.notEqual(h.viewer.status().phase,'displayed');assert.ok(!JSON.stringify(h.viewer.status()).includes(SECRET));h.viewer.stop();
});

for(const lost of ['lost','malformed'])test(lost+' receipt recovers from authoritative latest image without a second POST',async()=>{
  const h=harness();
  h.receipts.push(lost==='lost'?()=>Promise.reject(new Error('lost receipt')):json({ok:true,state:'stored'}));
  await rendered(h,photo('accepted',3,10));
  assert.equal(h.count('/photos/viewer/receipt'),1);assert.notEqual(h.viewer.status().phase,'displayed');assert.equal(h.mount.children.length,0);
  const latest=photo('accepted',3,11);latest.pending=false;h.state(latest);await h.viewer.pollOnce();await h.painted();
  assert.equal(h.count('/photos/viewer/receipt'),1);assert.equal(h.mount.children.length,1);
  assert.equal(h.viewer.status().phase,'displayed');assert.equal(h.viewer.status().photoId,'accepted');
  for(const c of h.calls)assert.ok(!c.url.includes('/captures'));h.viewer.stop();
});

test('uncertain receipt with repeated pending true cannot trigger a second POST',async()=>{
  const h=harness();h.receipts.push(()=>Promise.reject(new Error('lost receipt')));await rendered(h,photo('pending',3,10));
  for(const v of [10,11,12]){h.state(photo('pending',3,v));await h.viewer.pollOnce();await h.painted();}
  assert.equal(h.count('/photos/viewer/receipt'),1);assert.equal(h.count('/photos/images/pending'),1);
  assert.notEqual(h.viewer.status().phase,'displayed');h.viewer.stop();
});
