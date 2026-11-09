import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {resolve} from 'node:path';
import {createServer} from 'vite';
import assert from 'node:assert/strict';

assert.equal(process.env.BIM_UI_TEST,'1');
assert.equal(process.env.BIM_MONGODB_URI,'mongodb://127.0.0.1:27017');
assert.match(process.env.BIM_DATABASE,/^bim_insight_test_accounts011_[0-9]+$/);
const backend=spawn(resolve('.venv/Scripts/python.exe'),['backend/tests/account_ui_server.py','--desktop','--parent-pid',String(process.pid)],{windowsHide:true,stdio:['ignore','pipe','inherit'],env:process.env});
let server,closing=false;
async function close(code=0){
  if(closing)return;closing=true;
  if(backend.exitCode===null){const killer=spawn('taskkill',['/PID',String(backend.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});await new Promise(done=>killer.once('exit',done));}
  await server?.close();process.exit(code);
}
process.on('SIGINT',()=>close());process.on('SIGTERM',()=>close());
backend.on('exit',()=>{if(!closing)close(1);});backend.on('error',()=>close(1));
const lines=createInterface({input:backend.stdout});
const timeout=setTimeout(()=>close(1),15000);
const connection=await new Promise((done,reject)=>{lines.once('line',line=>{try{done(JSON.parse(line));}catch{reject(new Error('Invalid fixture connection'));}});lines.once('close',()=>reject(new Error('Fixture stopped')));});
clearTimeout(timeout);
assert.match(connection.base_url,/^http:\/\/127\.0\.0\.1:[0-9]+$/);assert.ok(connection.token.length>=32);
process.env.BIM_BACKEND_URL=connection.base_url;process.env.BIM_API_TOKEN=connection.token;
server=await createServer({root:resolve('frontend'),configFile:resolve('frontend/vite.config.ts'),server:{host:'127.0.0.1'}});
await server.listen();console.log('Local account fixture ready; email goes only to the synthetic test outbox.');
