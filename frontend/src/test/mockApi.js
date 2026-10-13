// Tiny route-based fetch + XMLHttpRequest mocks (no network, deterministic).
//
//   const api = mockFetch({
//     'POST /api/auth/login': (req) => [401, { detail: 'Invalid credentials' }],
//     'GET /api/videos/5': seq({ stage: 'detect' }, { stage: 'done' }), // one per call, last repeats
//     'GET /api/videos': [200, []],                           // array bodies need the [status, body] form
//     'GET /api/config': { max_upload_mb: 1 },                // anything else = 200 JSON body
//   });
//   api.calls -> [{ method, path, search, url, body, headers }]
//
// Keys are "METHOD /path" (query string ignored when matching; see req.search).
// Unmatched requests answer 404 {detail: "Not Found"}, like FastAPI.
import { vi } from 'vitest';

export const API = 'http://localhost:8000';

// Successive responses for one route; the last one repeats.
export const seq = (...items) => ({ __seq: items });

function toResponse(result) {
  // [status, body] tuple or a plain body (200).
  const [status, body] = Array.isArray(result) && typeof result[0] === 'number' && result.length === 2 ? result : [200, result];
  // (A bare array body would be ambiguous, so pass it as [200, [...]].)
  const text = body === undefined || body === null ? '' : typeof body === 'string' ? body : JSON.stringify(body);
  return new Response(status === 204 ? null : text, { status, headers: { 'Content-Type': 'application/json' } });
}

export function mockFetch(routes = {}) {
  const calls = [];
  const queues = new Map();
  const fn = vi.fn(async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url);
    const method = (init.method || 'GET').toUpperCase();
    let body = init.body;
    if (typeof body === 'string') {
      try {
        body = JSON.parse(body);
      } catch {
        /* keep raw */
      }
    }
    const req = { method, path: url.pathname, search: url.search, params: url.searchParams, url: url.href, body, headers: init.headers || {} };
    calls.push(req);
    if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const key = `${method} ${url.pathname}`;
    let handler = routes[key];
    if (handler && handler.__seq) {
      const q = queues.get(key) ?? [...handler.__seq];
      queues.set(key, q);
      handler = q.length > 1 ? q.shift() : q[0];
    }
    if (handler === undefined) return toResponse([404, { detail: 'Not Found' }]);
    if (handler === 'network-error') throw new TypeError('Failed to fetch');
    const result = typeof handler === 'function' ? await handler(req) : handler;
    return toResponse(result);
  });
  vi.stubGlobal('fetch', fn);
  return {
    fn,
    calls,
    find: (method, path) => calls.filter((c) => c.method === method && c.path === path),
  };
}

// XMLHttpRequest stand-in for uploadVideo(). `respond(xhr)` returns [status, body];
// upload progress events fire before the response.
export function mockXHR(respond) {
  const sent = [];
  class FakeXHR {
    constructor() {
      this.upload = {};
      this.headers = {};
      this.status = 0;
      this.responseText = '';
    }
    open(method, url) {
      this.method = method;
      this.url = url;
    }
    setRequestHeader(k, v) {
      this.headers[k] = v;
    }
    abort() {
      this.aborted = true;
      this.onabort?.();
    }
    send(form) {
      this.form = form;
      sent.push(this);
      const size = form?.get?.('file')?.size ?? 100;
      queueMicrotask(async () => {
        if (this.aborted) return;
        this.upload.onprogress?.({ lengthComputable: true, loaded: size / 2, total: size });
        this.upload.onprogress?.({ lengthComputable: true, loaded: size, total: size });
        const [status, body] = await respond(this);
        this.status = status;
        this.responseText = typeof body === 'string' ? body : JSON.stringify(body ?? null);
        this.onload?.();
      });
    }
  }
  vi.stubGlobal('XMLHttpRequest', FakeXHR);
  return { sent };
}

// A logged-in session as AuthProvider reads it.
export function signIn(token = 'test-token') {
  localStorage.setItem('sca.token', token);
}

export const ME = { id: 1, user_id: 1, name: 'Faisal Musa', email: 'faisal@example.com', created_at: '2026-09-01T12:00:00Z' };

// v0.4.1 /api/config (avi + mkv allowed).
export const CONFIG = { max_upload_mb: 500, allowed_extensions: ['avi', 'mkv', 'mov', 'mp4'] };
