/*
 * Small fetch wrapper shared by every API module.
 *
 * Requests go to relative paths (/api/..., /ws/...). In development the Vite
 * proxy forwards them to FastAPI; in Docker, nginx does. That way the browser
 * never needs to know the backend's address and there are no CORS issues.
 * VITE_API_BASE can still point somewhere else when needed.
 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const DEFAULT_TIMEOUT_MS = 5000

/** Thrown for network failures, timeouts and non-2xx responses. */
export class ApiError extends Error {
  constructor(message, { status = null, cause } = {}) {
    super(message, { cause })
    this.name = 'ApiError'
    this.status = status // null means the backend could not be reached
  }
}

/**
 * Request JSON from the backend.
 * @param {string} path e.g. '/api/health'
 * @param {RequestInit & { timeoutMs?: number }} options
 */
export async function apiRequest(path, { timeoutMs = DEFAULT_TIMEOUT_MS, signal, ...init } = {}) {
  // Abort on timeout or when the caller aborts (e.g. component unmount)
  const timeout = AbortSignal.timeout(timeoutMs)
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout

  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: combined,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    })
  } catch (err) {
    if (signal?.aborted) throw err // caller cancelled; not an API failure
    throw new ApiError("Can't reach the backend", { cause: err })
  }

  if (!response.ok) {
    throw new ApiError(`Request failed (${response.status})`, { status: response.status })
  }
  return response.json()
}

/** WebSocket URL for a path, matching the page's protocol (ws / wss). */
export function wsUrl(path) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${path}`
}
