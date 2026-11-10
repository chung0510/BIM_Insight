import assert from 'node:assert/strict';

const original = {window:globalThis.window, isTauri:globalThis.isTauri, fetch:globalThis.fetch, now:Date.now, timeout:globalThis.setTimeout};
globalThis.isTauri=true;
globalThis.window = {__TAURI_INTERNALS__:{invoke:async()=>({base_url:'https://api.example.org',token:''})}};
const {connectProcessor}=await import('../src/inspection-api.ts');
const health={capabilities:{file_inspection:true},processing_limits:{queue_files:200},file_limits:{pdf:20*1024**2},deployment:'web_demo'};
let now=0, calls=0;
Date.now=()=>now;
globalThis.setTimeout=(callback, delay,...args)=>{
  if(delay!==3000)return original.timeout(callback,delay,...args);
  now+=delay;queueMicrotask(callback);return 0;
};
try {
  globalThis.fetch=async()=>{calls++;return calls===1?new Response('waking up',{status:503}):Response.json(health);};
  const connected=await connectProcessor();
  assert.equal(calls,2);
  assert.equal(connected.base_url,'https://api.example.org');
  assert.equal(connected.deployment,'web_demo');

  calls=0;
  globalThis.fetch=async()=>{calls++;return calls===1?new Response('<html>Application loading</html>',{headers:{'Content-Type':'text/html'}}):Response.json(health);};
  await connectProcessor();
  assert.equal(calls,2);

  calls=0;
  globalThis.fetch=async()=>{calls++;return Response.json({detail:'origin_not_allowed'},{status:403});};
  await assert.rejects(connectProcessor());
  assert.equal(calls,1,'permanent errors must not retry');

  calls=0;
  globalThis.fetch=async()=>{calls++;throw new TypeError('Failed to fetch');};
  const before=now;
  await assert.rejects(connectProcessor());
  assert.ok(now-before>=120000 && now-before<=123000,'startup retries must be bounded');
  assert.ok(calls>1);

  const abort=new AbortController();
  abort.abort();
  calls=0;
  globalThis.fetch=async()=>{calls++;return Response.json(health);};
  await assert.rejects(connectProcessor(abort.signal));
  assert.equal(calls,0,'cancelled attempts must not call the API');
  console.log('PASS: remote health, transient/HTML startup retry, permanent errors, bounded wait and cancellation.');
} finally {
  globalThis.window=original.window;globalThis.isTauri=original.isTauri;globalThis.fetch=original.fetch;Date.now=original.now;globalThis.setTimeout=original.timeout;
}
