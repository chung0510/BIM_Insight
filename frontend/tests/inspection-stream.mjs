import assert from 'node:assert/strict';
import {inspectFile, errorMessage} from '../src/inspection-api.ts';

let contentType = 'application/x-ndjson', body = '', request;
class XHR {
  status = 200;
  responseText = '';
  upload = {};
  headers = {};
  open() {}
  setRequestHeader(key, value) { this.headers[key] = value; }
  getResponseHeader() { return contentType; }
  send() {
    queueMicrotask(() => {
      this.upload.onprogress?.({lengthComputable: true, loaded: 1, total: 1});
      for (let offset = 0; offset < body.length; offset += 3) {
        this.responseText += body.slice(offset, offset + 3);
        this.onprogress?.({});
      }
      this.onload?.({});
      this.onloadend?.({});
    });
  }
  abort() { this.onabort?.({}); this.onloadend?.({}); }
}
globalThis.XMLHttpRequest = XHR;
const connection = {base_url: 'http://127.0.0.1', token: 'test', processing_limits: {timeout_seconds: 60}};
const file = new File(['ISO-10303-21;'], 'Snowdon.ifc');
const context = {project_id: 'test', logical_source: 'Snowdon'};
const report = {id: 'a'.repeat(32), kind: 'ifc', status: 'failed', result: null,
  processing: {peak_memory_bytes: 900000000, memory_limit_bytes: 800000000}};
const progress = {type: 'progress', phase: 'building_geometry', done: 2, total: 10,
  memory_bytes: 400000000, memory_limit_bytes: 800000000, source_name: 'Kiến trúc – nhà ở'};
const read = (events) => inspectFile(connection, file, () => {}, value => {request = value;}, context, events);
body = [progress, {type: 'result', report}].map(value => JSON.stringify(value) + '\n').join('');
const events = [];
assert.deepEqual(await read(value => events.push(value)), report);
assert.equal(events.length, 1);
assert.equal(events[0].memory_bytes, 400000000);
assert.equal(events[0].source_name, 'Kiến trúc – nhà ở');
assert.equal(request.headers.Accept, 'application/x-ndjson');
body = JSON.stringify({type: 'error', code: 'processing_memory_limit'}) + '\n';
await assert.rejects(read(() => {}), error => error.message === errorMessage('processing_memory_limit'));
body = JSON.stringify(progress) + '\n';
await assert.rejects(read(() => {}), /kết nối|kết quả/i);
body = 'not-json\n';
await assert.rejects(read(() => {}));
contentType = 'application/json'; body = JSON.stringify(report);
assert.deepEqual(await read(() => {}), report);
const originalInterval=globalThis.setInterval, originalClear=globalThis.clearInterval, originalNow=performance.now;
let tick, cleared=false, now=1000;
try {
  globalThis.setInterval=callback=>{tick=callback;return 123;};
  globalThis.clearInterval=()=>{cleared=true;};
  performance.now=()=>now;
  class HoldingXHR extends XHR {
    send() { queueMicrotask(()=>{this.responseText=JSON.stringify(progress)+'\n';this.onprogress?.({});}); }
  }
  globalThis.XMLHttpRequest=HoldingXHR;contentType='application/x-ndjson';
  const pending=read(()=>{});
  await Promise.resolve();
  assert.equal(typeof tick,'function','A streamed upload needs an idle watchdog');
  now+=31000; tick();
  await assert.rejects(pending,error=>error.message===errorMessage('inspection_connection_lost'));
  assert.equal(cleared,true);
} finally {globalThis.setInterval=originalInterval;globalThis.clearInterval=originalClear;performance.now=originalNow;}
console.log('PASS: fragmented IFC progress, RAM telemetry, complete result, streamed error, missing result, malformed stream and legacy JSON.');
