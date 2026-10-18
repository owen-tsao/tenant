'use strict';
// Fake VM transport only: no browser, camera, HTTP server, or network.
const readline = require('node:readline');
const {fixture, deferred, settle} = require('./device-photo-fixture.cjs');
const emit = value => process.stdout.write(JSON.stringify(value) + '\n');
let phone, uploadNumber = 0;
const pending = new Map();
async function run(message) {
  if (message.op === 'init') {
    const jpeg = Buffer.from(message.jpeg, 'base64');
    phone = fixture({
      width:32, height:24,
      encode: callback => callback(new Blob([jpeg], {type:'image/jpeg'})),
      fetch: async ({url, init}) => {
        const number = ++uploadNumber, gate = deferred();
        pending.set(number, gate);
        emit({event:'upload', number, url, headers:init.headers,
          body:Buffer.from(await init.body.arrayBuffer()).toString('base64')});
        const response = await gate.promise;
        return {ok:response.status >= 200 && response.status < 300,
          status:response.status, json:async()=>response.body};
      }
    });
    await phone.join();
    const ws = phone.sockets[0];
    ws.send = raw => {const frame = JSON.parse(raw);ws.sent.push(frame);emit({event:'socket',frame});};
    for (const frame of ws.sent) emit({event:'socket',frame});
  } else if (message.op === 'frame') phone.frame(message.frame);
  else if (message.op === 'upload_response') {
    const gate = pending.get(message.number);
    if (!gate) throw Error('Unknown fake upload');
    pending.delete(message.number);gate.resolve(message);
  } else if (message.op === 'stats') emit({event:'stats',draws:phone.draws.length,uploads:phone.uploads.length});
  else if (message.op === 'leave') phone.leave();
  else throw Error('Unknown contract operation');
  await settle();
}
(async()=>{
  for await (const line of readline.createInterface({input:process.stdin})) await run(JSON.parse(line));
})().catch(error=>{emit({event:'error',message:error.message});process.exitCode=1;});
