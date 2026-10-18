'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const htmlPath = () => process.env.TENANT_DEVICE_HTML || 'web/device.html';
const deferred = () => { let resolve, reject; const promise = new Promise((a,b)=>{resolve=a;reject=b;}); return {promise,resolve,reject}; };
const settle = async () => { for (let i=0;i<10;i++) await new Promise(resolve=>setImmediate(resolve)); };
function fixture(options={}) {
  const html=fs.readFileSync(path.resolve(htmlPath()),'utf8');
  const code=html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const elements=new Map(), sockets=[], draws=[], uploads=[], constraints=[], frameCancels=[], videoEvents={}, windowEvents={}, documentEvents={};
  let permissionQueries=0, permissionRequests=0, now=0, nextTimer=1;
  const timers=new Map();
  let nextFrame=1; const cancelledFrames=new Set();
  function basic(id='') { return {id,value:id==='room'?'ROOM':id==='token'?'secret':'Phone',disabled:false,style:{},dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(type,cb){this[type]=cb;},removeEventListener(){},setAttribute(name,value){this[name]=value;},removeAttribute(name){delete this[name];},remove(){},appendChild(){},append(){}}; }
  const element=id=>elements.get(id)||elements.set(id,basic(id)).get(id);
  const track={readyState:'live',getCapabilities:()=>({torch:options.torch??true}),getSettings:()=>({width:options.width??1920,height:options.height??1080}),addEventListener(type,cb){this[type]=cb;},removeEventListener(){},stop(){this.readyState='ended';},applyConstraints:async value=>{constraints.push(value);if(options.apply)await options.apply();}};
  const stream={getTracks:()=>[track],getVideoTracks:()=>[track],active:true};
  const video=Object.assign(basic(),{currentTime:1,readyState:options.videoReadyState??4,videoWidth:options.width??1920,videoHeight:options.height??1080,srcObject:null,paused:true,play:async()=>{video.paused=false; if(options.play) await options.play();},pause(){this.paused=true;},addEventListener(type,cb){videoEvents[type]=cb;},removeEventListener(type){delete videoEvents[type];}});
  if(options.frameCallbacks!==false){video.requestVideoFrameCallback=cb=>{const id=nextFrame++;const callback=()=>{video.currentTime+=1/30;cb(now,{mediaTime:video.currentTime});};if(options.freshFrame)options.freshFrame(callback);else setImmediate(()=>{if(!cancelledFrames.has(id))callback();});return id;};video.cancelVideoFrameCallback=id=>{cancelledFrames.add(id);frameCancels.push(id);};}
  const canvas=Object.assign(basic(),{width:0,height:0,getContext:()=>({drawImage(...args){draws.push(args);}}),toBlob(cb,type,quality){ if(options.encode) options.encode(cb,type,quality); else cb(new Blob([new Uint8Array(options.blobSize??100)],{type:options.blobType??'image/jpeg'})); }});
  const document={body:Object.assign(basic(),{dataset:{},appendChild(){}}),visibilityState:'visible',getElementById:element,createElement(tag){if(tag==='video')return video;if(tag==='canvas')return canvas;return basic();},addEventListener(type,cb){documentEvents[type]=cb;}};
  class WS {constructor(url){this.url=String(url);this.readyState=1;this.sent=[];sockets.push(this);}send(x){this.sent.push(JSON.parse(x));}close(){if(this.readyState===3)return;this.readyState=3;this.onclose?.({code:1000});}}
  const navigator={mediaDevices:{getUserMedia:async args=>{permissionRequests++;const acquired=options.acquire?await options.acquire({stream,track,call:permissionRequests}):stream;if(options.denied)throw Object.assign(Error('denied'),{name:'NotAllowedError'});return acquired||stream;}},permissions:{query:async()=>{permissionQueries++;return {state:options.permissionState??'granted',addEventListener(){}};}}};
  const context={document,navigator,location:{pathname:'/d/phone',search:'?room=ROOM',href:'https://tenant.test/d/phone',origin:'https://tenant.test',protocol:'https:'},history:{replaceState(){}},URL,URLSearchParams,Blob,Uint8Array,AbortController,WebSocket:WS,window:{isSecureContext:options.secure??true,addEventListener(type,cb){windowEvents[type]=cb;}},performance:{now:()=>now},Date,console,crypto:require('node:crypto').webcrypto,setTimeout(cb,ms){const id=nextTimer++;timers.set(id,{at:now+ms,cb});return id;},clearTimeout(id){timers.delete(id);},fetch:async(url,init)=>{const item={url:String(url),init};uploads.push(item);if(options.fetch)return options.fetch(item);return {ok:true,status:200,json:async()=>({ok:true,capture_id:new URL(String(url),'https://tenant.test').pathname.split('/').pop(),stored:true,state:'stored'})};}};
  vm.runInNewContext(code,context,{filename:htmlPath()});
  const f={html,elements,element,document,sockets,draws,uploads,constraints,frameCancels,track,video,canvas,videoEvents,windowEvents,documentEvents,get permissionRequests(){return permissionRequests;},get permissionQueries(){return permissionQueries;},async join(){element('token').value='secret';element('room').value='ROOM';await element('join').submit({preventDefault(){}});await settle();sockets.at(-1)?.onopen();await settle();},frame(frame,ws=sockets.at(-1)){ws.onmessage?.({data:JSON.stringify(frame)});},async advance(ms){now+=ms;let due;while((due=[...timers].find(([,t])=>t.at<=now))){timers.delete(due[0]);due[1].cb();await settle();}},disconnect(code=1006){const ws=sockets.at(-1);ws.readyState=3;ws.onclose?.({code});},leave(){element('leave').click();},async ready(){await this.join();this.frame({type:'welcome',room:'ROOM'});await settle();this.frame({type:'photo.consent',ok:true,revision:1,enabled:true,ready:true});await settle();}};
  return f;
}
const photo=(req='p1',extra={})=>({type:'do',req,cap:'camera.capture',args:{capture_id:'capture_1',upload_url:'/photos/uploads/capture_1',upload_token:'ticket-secret'},epoch:1,deadline_ms:1000,...extra});
module.exports={fixture,photo,deferred,settle,htmlPath};
