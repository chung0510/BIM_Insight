import assert from 'node:assert/strict';
import {readClashStream} from '../src/clash-stream.ts';

const report={id:'a'.repeat(32),status:'partial',verdict:'incomplete',issues:[],diagnostics:[{code:'clash_missing_geometry'}]};
function stream(events, chunkSize=3){
  const bytes=new TextEncoder().encode(events.map(event=>JSON.stringify(event)+'\n').join(''));
  let offset=0;
  return new Response(new ReadableStream({pull(controller){
    if(offset===bytes.length){controller.close();return;}
    controller.enqueue(bytes.slice(offset,offset+chunkSize));offset=Math.min(bytes.length,offset+chunkSize);
  }}),{headers:{'Content-Type':'application/x-ndjson'}});
}
const events=[];
assert.deepEqual(await readClashStream(stream([{type:'progress',phase:'building_geometry',source_name:'Kiến trúc – nhà ở',done:2,total:10,elapsed_seconds:3},{type:'result',report}]),event=>events.push(event)),report);
assert.equal(events[0].source_name,'Kiến trúc – nhà ở');
assert.equal(events[0].done,2);
await assert.rejects(readClashStream(stream([{type:'progress',phase:'checking_pairs'}]),()=>{}),error=>error.code==='clash_connection_lost');
await assert.rejects(readClashStream(stream([{type:'error',code:'processing_memory_limit'}]),()=>{}),error=>error.code==='processing_memory_limit');
assert.deepEqual(await readClashStream(Response.json(report),()=>{}),report);
const large={...report,issues:Array.from({length:2000},(_,index)=>({id:String(index),recommendation:'Giữ nguyên bằng chứng '+index}))};
assert.deepEqual(await readClashStream(stream([{type:'result',report:large}],127),()=>{}),large);
let cancelled=false,producer;
const completing=new Response(new ReadableStream({start(controller){producer=controller;controller.enqueue(new TextEncoder().encode(JSON.stringify({type:'result',report})+'\n'));},cancel(){cancelled=true;}}),{headers:{'Content-Type':'application/x-ndjson'}});
assert.deepEqual(await readClashStream(completing,()=>{}),report);
assert.equal(cancelled,false,'Receiving a complete report must allow the HTTP response to finish normally');
producer.close();
console.log('PASS: UTF-8 fragmented progress, complete result, interrupted stream, structured failure, JSON compatibility and large result.');
