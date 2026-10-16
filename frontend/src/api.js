// Centralizes every call to the FastAPI backend. Includes cold-start retry
// logic and automatically attaches the user's Bearer token when signed in.

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

let currentAuthToken = ''

export function setAuthToken(token) {
  currentAuthToken = token || ''
}

export function getAuthToken() {
  return currentAuthToken
}

async function fetchWithRetry(path, options = {}, { retries = 4, onRetry } = {}) {
  const url = `${API_BASE}${path}`
  let lastError
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 20000)

      const headers = { ...(options.headers || {}) }
      if (currentAuthToken) {
        headers['Authorization'] = `Bearer ${currentAuthToken}`
      }

      const res = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal,
      })
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
  let userKey = ''
  try {
    userKey = localStorage.getItem('signal_gemini_api_key') || ''
  } catch {
    // localStorage unavailable
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

// ── Authenticated User Endpoints ────────────────────────────────────────────

export function getMe() {
  return fetchWithRetry('/api/me', {}, { retries: 1 })
}

export function updatePreferences(preferredDepts, preferredSources = []) {
  return fetchWithRetry(
    '/api/me/preferences',
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        preferred_depts: preferredDepts,
        preferred_sources: preferredSources,
      }),
    },
    { retries: 1 }
  )
}

export function saveUserItem(item, customNote = '', editedSummary = undefined) {
  return fetchWithRetry(
    '/api/me/saved',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_url: item.url || item.item_url,
        title: item.title,
        source: item.source || '',
        category: item.category || '',
        summary: editedSummary !== undefined ? editedSummary : (item.summary || ''),
        custom_note: customNote,
        dept: item.dept || [],
        stack_tags: item.stack_tags || [],
      }),
    },
    { retries: 1 }
  )
}

export function removeSavedItem(itemUrl) {
  const q = new URLSearchParams({ item_url: itemUrl })
  return fetchWithRetry(
    `/api/me/saved?${q.toString()}`,
    { method: 'DELETE' },
    { retries: 1 }
  )
}

export function updateNewsletterPrefs(dailyNewsletter, weeklyNewsletter) {
  return fetchWithRetry(
    '/api/me/newsletter',
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        daily_newsletter: Boolean(dailyNewsletter),
        weekly_newsletter: Boolean(weeklyNewsletter),
      }),
    },
    { retries: 1 }
  )
}

export function getNewsletterPreview(kind = 'daily', forceRefresh = false) {
  let userKey = ''
  try {
    userKey = localStorage.getItem('signal_gemini_api_key') || ''
  } catch {}
  const q = new URLSearchParams({ kind, force_refresh: String(forceRefresh) })
  const headers = userKey ? { 'X-Gemini-Key': userKey } : {}
  return fetchWithRetry(`/api/newsletter/preview?${q.toString()}`, { headers }, { retries: 1 })
}

export function sendTestNewsletter(kind = 'daily') {
  let userKey = ''
  try {
    userKey = localStorage.getItem('signal_gemini_api_key') || ''
  } catch {}
  return fetchWithRetry(
    '/api/newsletter/send-test',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kind,
        gemini_api_key: userKey || undefined,
      }),
    },
    { retries: 1 }
  )
}
