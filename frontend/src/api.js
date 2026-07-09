// Centralizes every call to the FastAPI backend. Kept separate from
// components so the cold-start-aware retry logic (see fetchWithRetry)
// lives in exactly one place.

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

// Render's free tier cold-starts after ~15 min idle, taking up to 30-50s
// to respond to the first request. A naive fetch would just throw/timeout
// and look broken. This retries with backoff so a slow cold start reads as
// "loading" rather than "error" -- the single biggest UX gap of choosing
// the free-tier-backend path over a static site.
async function fetchWithRetry(path, options = {}, { retries = 4, onRetry } = {}) {
  const url = `${API_BASE}${path}`
  let lastError
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 20000)
      const res = await fetch(url, { ...options, signal: controller.signal })
      clearTimeout(timeout)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Request failed (${res.status})`)
      }
      return await res.json()
    } catch (err) {
      lastError = err
      if (attempt < retries) {
        onRetry?.(attempt + 1, retries)
        // Backoff: 2s, 4s, 8s, 16s -- gives a sleeping Render instance
        // time to wake up without hammering it with rapid retries.
        await new Promise((r) => setTimeout(r, 2000 * Math.pow(2, attempt)))
      }
    }
  }
  throw lastError
}

export function getStatus(onRetry) {
  return fetchWithRetry('/api/status', {}, { onRetry })
}

export function getItems(params = {}, onRetry) {
  const query = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v != null))
  )
  return fetchWithRetry(`/api/items?${query.toString()}`, {}, { onRetry })
}

export function triggerRefresh() {
  return fetchWithRetry('/api/refresh', { method: 'POST' }, { retries: 1 })
}

export function getSummary(item) {
  // If the person has added their own Gemini key (Settings -> "Add Gemini
  // key"), send it along so the backend uses it instead of the shared
  // server-side key. Read straight from localStorage here rather than
  // threading it through every component that calls getSummary.
  let userKey = ''
  try {
    userKey = localStorage.getItem('signal_gemini_api_key') || ''
  } catch {
    // localStorage unavailable -- fall back to the server's shared key
  }

  return fetchWithRetry(
    '/api/summary',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: item.url,
        title: item.title,
        category: item.category,
        existing_summary: item.summary || '',
        gemini_api_key: userKey || undefined,
      }),
    },
    { retries: 1 }
  )
}
