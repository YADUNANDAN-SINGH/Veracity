/*
 * GET /api/call/state: is the USB-connected phone idle, ringing or in a call?
 * Polled by Step 2 so an incoming cellular call fills in the caller's number.
 *
 * Response:
 * {
 *   "connected": true,                  // false: no phone over adb
 *   "state": "ringing",                 // "idle" | "ringing" | "in_call"
 *   "number": "+919876543210"           // null when idle or the phone hides it
 * }
 */
import { apiRequest } from './client'

export function fetchCallState({ signal } = {}) {
  return apiRequest('/api/call/state', { signal, timeoutMs: 4000 })
}
