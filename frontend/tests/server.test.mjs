import {test} from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {createServer} from '../server.mjs';
const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${server.address().port}`)));
const close = server => new Promise(resolve => server.close(resolve));
test('serves frontend, proxies JSON/query/status and handles 204', async () => {
  const backend = http.createServer(async (req,res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    if (req.method === 'DELETE') {res.writeHead(204);res.end();return;}
    res.writeHead(req.method === 'POST' ? 201 : 409, {'content-type':'application/json'});
    res.end(JSON.stringify({url:req.url, method:req.method, body:body ? JSON.parse(body):null}));
  });
  const backendUrl = await listen(backend); const frontend = createServer(backendUrl); const url = await listen(frontend);
  try {
    assert.match(await (await fetch(url)).text(), /common/);
    assert.equal((await fetch(url + '/app.js')).status,200);
    assert.equal((await fetch(url + '/crypto.js')).status,200);
    assert.equal((await fetch(url + '/key-store.js')).status,200);
    const response = await fetch(url + '/api/v1/groups?limit=100&offset=100', {method:'POST',headers:{'content-type':'application/json'}, body:JSON.stringify({name:'Test'})});
    assert.equal(response.status,201); assert.deepEqual(await response.json(),{url:'/api/v1/groups?limit=100&offset=100',method:'POST',body:{name:'Test'}});
    assert.equal((await fetch(url + '/api/v1/groups')).status,409);
    const deleted = await fetch(url + '/api/v1/groups/one', {method:'DELETE'}); assert.equal(deleted.status,204); assert.equal(await deleted.text(),'');
    assert.equal((await fetch(url + '/server.mjs')).status,404);
  } finally {await close(frontend);await close(backend);}
});
test('unavailable backend returns actionable 502',async () => {
  const unavailable = http.createServer(); const destination = await listen(unavailable); await close(unavailable);
  const frontend = createServer(destination); const url = await listen(frontend);
  try {const result = await fetch(url + '/api/v1/users');assert.equal(result.status,502);assert.match((await result.json()).detail,/Cannot reach/);}
  finally {await close(frontend);}
});
