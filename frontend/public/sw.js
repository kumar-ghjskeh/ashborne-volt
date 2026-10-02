// Ashborne Volt — minimal service worker.
// Strategy: the job corpus must ALWAYS be revalidated; cache the app shell +
// static assets so the installed PWA opens instantly and works offline.
// Bump CACHE_VERSION to invalidate old caches on deploy.
//
// The /data rule below is load-bearing. This file was written when job data
// came from /api, so only /api was excluded from caching. When the corpus moved
// to a static file at /data/jobs.json it silently fell into the cache-first
// branch — the installed PWA then served the same corpus from disk forever and
// never asked the server for a newer one, no matter how many scrapes published.
// From the outside it looked exactly like the scrapes were not working.
const CACHE_VERSION = 'volt-v1'
const SHELL = ['/', '/index.html', '/volt-logo.png', '/manifest.webmanifest']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(SHELL)).catch(() => {}),
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))),
    ),
  )
  self.clients.claim()
})

// ── Web Push: show a notification when the server pushes a saved-search alert ──
self.addEventListener('push', (event) => {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch { data = {} }
  const title = data.title || 'Ashborne Volt'
  const options = {
    body: data.body || 'New jobs match your saved search.',
    icon: '/volt-logo.png',
    badge: '/volt-logo.png',
    tag: data.tag || 'volt-alert',
    data: { url: data.url || '/' },
  }
  event.waitUntil(self.registration.showNotification(title, options))
})

// Clicking a notification focuses an open tab or opens the app.
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const c of clients) {
        if ('focus' in c) return c.focus()
      }
      if (self.clients.openWindow) return self.clients.openWindow(target)
    }),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  // Never intercept API traffic — always hit the network for live job data.
  if (url.pathname.startsWith('/api') || url.hostname !== self.location.hostname) return

  // The job corpus: network-first, so a freshly published snapshot is picked up
  // on the next open. The cached copy is only a fallback for being offline.
  if (url.pathname.startsWith('/data/')) {
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone()
            caches.open(CACHE_VERSION).then((c) => c.put(request, copy)).catch(() => {})
          }
          return res
        })
        .catch(() => caches.match(request)),
    )
    return
  }

  // Navigations: network-first, fall back to cached shell when offline.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone()
          caches.open(CACHE_VERSION).then((c) => c.put(request, copy)).catch(() => {})
          return res
        })
        .catch(() => caches.match(request).then((r) => r || caches.match('/index.html'))),
    )
    return
  }

  // Static assets: cache-first, then network (and cache the result).
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((res) => {
          if (res && res.status === 200 && res.type === 'basic') {
            const copy = res.clone()
            caches.open(CACHE_VERSION).then((c) => c.put(request, copy)).catch(() => {})
          }
          return res
        }),
    ),
  )
})
