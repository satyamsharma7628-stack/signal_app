// Zero-dependency Supabase Auth (GoTrue) client using native browser fetch().
// Automatically refreshes expired 1-hour access_tokens using refresh_token so
// "Save to my section" and "Add note / edit" never fail after an hour.

const rawUrl = (import.meta.env.VITE_SUPABASE_URL || '').trim().replace(/\/+$/, '')
const supabaseAnonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY || '').trim()

export const isSupabaseConfigured = Boolean(rawUrl && supabaseAnonKey)

function getStorageKey() {
  try {
    const host = new URL(rawUrl).hostname
    const ref = host.split('.')[0]
    return `sb-${ref}-auth-token`
  } catch {
    return 'signal_supabase_session'
  }
}

const listeners = new Set()

function notifyListeners(event, session) {
  listeners.forEach((cb) => {
    try {
      cb(event, session)
    } catch (e) {
      console.error(e)
    }
  })
}

function saveSession(session) {
  const key = getStorageKey()
  try {
    if (session) {
      localStorage.setItem(key, JSON.stringify(session))
    } else {
      localStorage.removeItem(key)
    }
  } catch {}
}

function readStoredSession() {
  const key = getStorageKey()
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function isSessionExpired(session) {
  if (!session || !session.access_token) return true
  if (session.expires_at) {
    const nowSec = Math.floor(Date.now() / 1000)
    // Refresh if within 120 seconds of expiry
    if (nowSec >= Number(session.expires_at) - 120) {
      return true
    }
  }
  // Also check JWT exp claim directly
  try {
    const parts = session.access_token.split('.')
    if (parts.length === 3) {
      const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')))
      if (payload.exp && Math.floor(Date.now() / 1000) >= payload.exp - 120) {
        return true
      }
    }
  } catch {}
  return false
}

function consumeHashSession() {
  if (typeof window === 'undefined' || !window.location.hash) return null
  const hash = window.location.hash.substring(1)
  if (!hash.includes('access_token=')) return null

  const params = new URLSearchParams(hash)
  const access_token = params.get('access_token')
  const refresh_token = params.get('refresh_token') || ''
  const expires_in = parseInt(params.get('expires_in') || '3600', 10)
  if (!access_token) return null

  const session = {
    access_token,
    refresh_token,
    expires_at: Math.floor(Date.now() / 1000) + expires_in,
  }
  saveSession(session)

  try {
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
  } catch {}

  return session
}

async function authFetch(path, options = {}) {
  const res = await fetch(`${rawUrl}/auth/v1${path}`, {
    ...options,
    headers: {
      apikey: supabaseAnonKey,
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const msg = data.msg || data.error_description || data.message || `Auth error (${res.status})`
    throw new Error(msg)
  }
  return data
}

async function refreshStoredSession(stored) {
  if (!stored?.refresh_token) return stored
  try {
    const data = await authFetch('/token?grant_type=refresh_token', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: stored.refresh_token }),
    })
    const refreshed = {
      ...stored,
      ...data,
      expires_at:
        data.expires_at ||
        Math.floor(Date.now() / 1000) + parseInt(data.expires_in || '3600', 10),
    }
    saveSession(refreshed)
    notifyListeners('TOKEN_REFRESHED', refreshed)
    return refreshed
  } catch (err) {
    console.warn('Could not refresh Supabase token:', err)
    return stored
  }
}

export const supabase = isSupabaseConfigured
  ? {
      auth: {
        async getSession() {
          const fromHash = consumeHashSession()
          if (fromHash) {
            setTimeout(() => notifyListeners('SIGNED_IN', fromHash), 0)
            return { data: { session: fromHash }, error: null }
          }
          let stored = readStoredSession()
          if (stored && isSessionExpired(stored) && stored.refresh_token) {
            stored = await refreshStoredSession(stored)
          }
          return { data: { session: stored }, error: null }
        },

        async refreshSession() {
          const stored = readStoredSession()
          if (!stored) return null
          return await refreshStoredSession(stored)
        },

        onAuthStateChange(callback) {
          listeners.add(callback)
          return {
            data: {
              subscription: {
                unsubscribe: () => listeners.delete(callback),
              },
            },
          }
        },

        async signInWithOAuth({ provider, options } = {}) {
          const redirectTo = options?.redirectTo || window.location.origin
          const url = `${rawUrl}/auth/v1/authorize?provider=${encodeURIComponent(
            provider || 'google'
          )}&redirect_to=${encodeURIComponent(redirectTo)}`
          window.location.assign(url)
          return { data: { url }, error: null }
        },

        async signInWithPassword({ email, password }) {
          try {
            const data = await authFetch('/token?grant_type=password', {
              method: 'POST',
              body: JSON.stringify({ email, password }),
            })
            const session = {
              ...data,
              expires_at:
                data.expires_at ||
                Math.floor(Date.now() / 1000) + parseInt(data.expires_in || '3600', 10),
            }
            saveSession(session)
            notifyListeners('SIGNED_IN', session)
            return { data: { session, user: data.user }, error: null }
          } catch (error) {
            return { data: null, error }
          }
        },

        async signUp({ email, password, options }) {
          try {
            const data = await authFetch('/signup', {
              method: 'POST',
              body: JSON.stringify({
                email,
                password,
                data: options?.data || {},
              }),
            })
            const session = data.access_token ? data : data.session || null
            if (session?.access_token) {
              saveSession(session)
              notifyListeners('SIGNED_IN', session)
            }
            return { data: { session, user: data.user || data }, error: null }
          } catch (error) {
            return { data: null, error }
          }
        },

        async signOut() {
          const stored = readStoredSession()
          saveSession(null)
          notifyListeners('SIGNED_OUT', null)
          if (stored?.access_token) {
            try {
              await authFetch('/logout', {
                method: 'POST',
                headers: { Authorization: `Bearer ${stored.access_token}` },
              })
            } catch {}
          }
          return { error: null }
        },
      },
    }
  : null
