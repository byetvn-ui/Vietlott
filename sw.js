const C = "vietlott-v1", KEY = u => u.origin + u.pathname;
self.addEventListener("install", e => e.waitUntil(caches.open(C).then(c => c.addAll(["./", "index.html", "data.js", "icon.svg"])).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => clients.claim())));
// network-first: luôn lấy bản mới nhất, mất mạng thì dùng bản đã lưu
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/")) return;
  e.respondWith(fetch(e.request).then(r => { const cp = r.clone(); caches.open(C).then(c => c.put(KEY(u), cp)); return r; })
    .catch(() => caches.match(KEY(u)).then(r => r || caches.match("index.html"))));
});
