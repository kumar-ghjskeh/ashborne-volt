import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Register the PWA service worker (production only — avoids dev caching headaches).
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then((reg) => {
      // Pull a new worker as soon as one is published and activate it without
      // waiting for every tab to close. An installed PWA can otherwise sit on an
      // old worker for days — which is how a stale cached corpus survived
      // repeated publishes and looked like the scraper had stopped.
      reg.update().catch(() => {})
      reg.addEventListener('updatefound', () => {
        const fresh = reg.installing
        if (!fresh) return
        fresh.addEventListener('statechange', () => {
          if (fresh.state === 'installed' && navigator.serviceWorker.controller) {
            window.location.reload()
          }
        })
      })
    }).catch(() => {
      /* offline or unsupported — the app works without it */
    })
  })
}
