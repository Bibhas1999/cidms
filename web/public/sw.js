// Supreme DMS service worker: makes the app installable and quick to open. It keeps only the app itself
// (the page, scripts, styles, fonts, icons). Patient data never goes in its cache: /api, /viewer and
// /dicom-web always go to the network, and so does anything that isn't a plain GET.
const CACHE = "sdms-shell-v1";
const SHELL = ["/", "/manifest.webmanifest", "/icons/favicon.png", "/icons/icon-192.png"];
const NEVER = ["/api/", "/viewer", "/dicom-web", "/healthz"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || NEVER.some((p) => url.pathname.startsWith(p))) return;

  // Pages: always the latest from the server; the saved copy only when offline.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => { if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put("/", copy)); } return res; })
        .catch(() => caches.match("/")),
    );
    return;
  }

  // Built files have their content hash in the name, so a saved copy is always right.
  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
        return res;
      })),
    );
  }
});

// A notification pop-up (shown by the app with registration.showNotification) was clicked: bring an open
// Supreme DMS tab to the front and take it to the notification's page, or open a new tab there. Only addresses
// inside this site are followed.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const raw = (event.notification.data && event.notification.data.link) || "/notifications";
  const target = new URL(raw.startsWith("/") && !raw.startsWith("//") ? raw : "/notifications", self.location.origin);
  event.waitUntil((async () => {
    const tabs = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const tab = tabs.find((c) => new URL(c.url).origin === self.location.origin);
    if (tab) {
      await tab.focus();
      if ("navigate" in tab && !target.pathname.startsWith("/api/")) {
        tab.postMessage({ type: "navigate", to: target.pathname + target.search });
        return;
      }
    }
    await self.clients.openWindow(target.href);
  })());
});
