/* sw.js — PG Manager Pro Service Worker */
const CACHE = "pg-pro-v2";
const SHELL = ["/"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(k => Promise.all(k.filter(c=>c!==CACHE).map(c=>caches.delete(c)))).then(()=>self.clients.claim()));
});
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET" || e.request.url.includes("/api/")) return;
  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
    if (res.ok) caches.open(CACHE).then(c => c.put(e.request, res.clone()));
    return res;
  })));
});
