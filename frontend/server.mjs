import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('./public/', import.meta.url));
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8' };
export function createServer(backend = process.env.API_BASE_URL || 'http://localhost:8000') {
  const base = new URL(backend);
  if (base.protocol !== 'http:') throw new Error('API_BASE_URL must use http://');
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname.startsWith('/api/v1/')) {
      // Fix the upstream origin; never accept an arbitrary proxy destination.
      const upstream = http.request(new URL(url.pathname + url.search, base), {
        method: req.method,
        headers: { ...(req.headers['content-type'] ? {'content-type': req.headers['content-type']} : {}), accept: 'application/json' },
      }, response => {
        res.writeHead(response.statusCode || 502, { 'content-type': response.headers['content-type'] || 'application/json', 'cache-control': 'no-store' });
        response.on('error', () => res.destroy());
        response.pipe(res);
      });
      upstream.setTimeout(15000, () => upstream.destroy(new Error('Backend timed out')));
      upstream.on('error', () => {
        if (!res.headersSent) { res.writeHead(502, {'content-type':'application/json'}); res.end(JSON.stringify({detail:'Cannot reach the backend. Check API_BASE_URL and that the API is running.'})); }
        else res.destroy();
      });
      req.on('aborted', () => upstream.destroy());
      req.pipe(upstream);
      return;
    }
    if (url.pathname === '/healthz') { res.writeHead(200); res.end('ok'); return; }
    const files = {'/':'index.html','/index.html':'index.html','/app.js':'app.js','/crypto.js':'crypto.js','/key-store.js':'key-store.js','/styles.css':'styles.css'};
    const file = files[url.pathname];
    if (!file || !['GET','HEAD'].includes(req.method)) { res.writeHead(404); res.end('Not found'); return; }
    try {
      const body = await readFile(path.join(root, file));
      res.writeHead(200, {'content-type': types[path.extname(file)], 'x-content-type-options':'nosniff', 'cache-control':'no-cache'});
      res.end(req.method === 'HEAD' ? undefined : body);
    } catch { res.writeHead(500); res.end('Build the frontend with npm run build first.'); }
  });
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  createServer().listen(Number(process.env.PORT || 3000), process.env.HOST || '0.0.0.0', () => console.log('Frontend listening on port ' + (process.env.PORT || 3000)));
}
