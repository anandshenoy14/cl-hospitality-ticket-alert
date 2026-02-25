// Service Worker — enables offline support and installability
const CACHE = 'cl-tickets-v1';
const STATIC = ['/', '/index.html', '/manifest.json'];

// Cache static assets on install
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting())
  );
});

// Clean up old caches on activate
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Network first for prices.json (always want fresh data),
// cache fallback for everything else
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  if (url.pathname.includes('prices.json')) {
    // Always try network first for price data
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request))
    );
  } else {
    // Cache first for static assets
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request))
    );
  }
});