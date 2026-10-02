import { api } from './api'

// Web Push subscribe flow. Free (VAPID): no third-party push service.
// Returns a human-readable status the caller can surface.

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(b64)
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

export function pushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

export function pushPermission(): NotificationPermission | 'unsupported' {
  if (!pushSupported()) return 'unsupported'
  return Notification.permission
}

export type EnableResult =
  | { ok: true }
  | { ok: false; reason: 'unsupported' | 'denied' | 'disabled' | 'error'; message: string }

/** Request permission + subscribe + register with the backend. */
export async function enablePushAlerts(): Promise<EnableResult> {
  if (!pushSupported()) {
    return { ok: false, reason: 'unsupported', message: 'This browser does not support push notifications.' }
  }
  try {
    const { key, enabled } = await api.getPushPublicKey()
    if (!enabled || !key) {
      return { ok: false, reason: 'disabled', message: 'Alerts are not configured on the server yet.' }
    }
    const permission = await Notification.requestPermission()
    if (permission !== 'granted') {
      return { ok: false, reason: 'denied', message: 'Notifications were blocked. Allow them in your browser to get alerts.' }
    }
    const reg = await navigator.serviceWorker.ready
    let sub = await reg.pushManager.getSubscription()
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      })
    }
    // Registering the subscription is the one thing that still needs somewhere
    // to store it. The rest of the app runs off a static corpus with no
    // database, so this is currently the only feature that cannot complete —
    // say so plainly instead of surfacing a 500.
    try {
      await api.subscribePush(sub.toJSON() as PushSubscriptionJSON)
    } catch {
      return {
        ok: false,
        reason: 'disabled',
        message:
          'Saved-search alerts aren’t available yet — the app no longer runs a '
          + 'server that can store your subscription. Your saved searches still '
          + 'track new matches; open the app to see the counts.',
      }
    }
    return { ok: true }
  } catch (e) {
    return { ok: false, reason: 'error', message: e instanceof Error ? e.message : 'Could not enable alerts.' }
  }
}
