import { useEffect, useMemo, useState } from 'react'
import StatusBar from './components/StatusBar'
import KpiStrip from './components/KpiStrip'
import FeedRow from './components/FeedRow'
import ApiKeySettings from './components/ApiKeySettings'
import UserMenu from './components/UserMenu'
import NewsletterModal from './components/NewsletterModal'
import {
  getStatus,
  getItems,
  triggerRefresh,
  setAuthToken,
  getMe,
  updatePreferences,
  saveUserItem,
  removeSavedItem,
  sendBuilderChatMessage,
  claimAdminOrSwitchTier,
  adminGetUsers,
  adminUpdateUserTier,
  adminDeleteFeedItem,
} from './api'
import { supabase, isSupabaseConfigured } from './supabaseClient'

const PAGE_SIZE = 12
const DEMO_TOKEN_KEY = 'signal_demo_auth_token'
const CHAT_HISTORY_KEY = 'signal_ai_chat_threads_v1'
const LOCAL_NICHES_KEY = 'signal_preferred_depts_backup'
const LOCAL_SAVED_FALLBACK_KEY = 'signal_saved_items_guest'
const LOCAL_TIER_OVERRIDE_KEY = 'signal_local_tier_override'
const CUSTOM_PRO_URLS_KEY = 'signal_admin_custom_pro_urls'

const FREE_MAX_NICHES = 3
const FREE_MAX_SAVED = 15

const DEPT_META = {
  'cybersecurity':   { label: '🔒 Cybersecurity',   color: '#e07070' },
  'ai-ml':           { label: '🤖 AI / ML',          color: '#a78bfa' },
  'gaming-tech':     { label: '🎮 Gaming Tech',       color: '#60b8ff' },
  'cloud':           { label: '☁️ Cloud',             color: '#5fbf7a' },
  'web-dev':         { label: '🌐 Web Dev',           color: '#ff8c1a' },
  'innovator':       { label: '🚀 Innovator',         color: '#f9c04a' },
  'random-dev-idea': { label: '🎲 Random Dev Idea',   color: '#8b8a85' },
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function sanitizeHtmlClient(dirtyHtml) {
  if (!dirtyHtml || typeof window === 'undefined' || !window.DOMParser) return dirtyHtml || ''
  try {
    const parser = new DOMParser()
    const doc = parser.parseFromString(String(dirtyHtml), 'text/html')
    const allowedTags = new Set(['P', 'B', 'STRONG', 'I', 'EM', 'U', 'UL', 'OL', 'LI', 'BR', 'CODE', 'PRE', 'H3', 'H4', 'A', 'DIV', 'SPAN'])
    for (const el of Array.from(doc.body.querySelectorAll('*'))) {
      if (!allowedTags.has(el.tagName)) {
        el.remove()
        continue
      }
      for (const attr of Array.from(el.attributes)) {
        const name = attr.name.toLowerCase()
        const val = (attr.value || '').trim().toLowerCase()
        if (name.startsWith('on') || name === 'srcdoc') {
          el.removeAttribute(attr.name)
        } else if (name === 'href') {
          if (!val.startsWith('https://') && !val.startsWith('http://')) {
            el.removeAttribute('href')
          } else {
            el.setAttribute('target', '_blank')
            el.setAttribute('rel', 'noopener noreferrer')
          }
        }
      }
    }
    return doc.body.innerHTML
  } catch {
    return ''
  }
}

function loadLocalNiches() {
  try {
    const raw = localStorage.getItem(LOCAL_NICHES_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function saveLocalNiches(depts) {
  try {
    localStorage.setItem(LOCAL_NICHES_KEY, JSON.stringify(depts || []))
  } catch {}
}

function decodeJwtProfileFallback(token) {
  if (!token || token.startsWith('demo:')) return null
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')))
    if (!payload.sub) return null
    const meta = payload.user_metadata || {}
    const email = payload.email || ''
    return {
      user_id: String(payload.sub),
      email,
      full_name: meta.full_name || meta.name || email.split('@')[0] || 'User',
      avatar_url: meta.avatar_url || meta.picture || '',
      preferred_depts: loadLocalNiches(),
      preferred_sources: [],
      subscription_tier: 'free',
      daily_newsletter: true,
      weekly_newsletter: false,
    }
  } catch {
    return null
  }
}

function loadStoredChatThreads() {
  try {
    const raw = localStorage.getItem(CHAT_HISTORY_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length > 0) return parsed
    }
  } catch {}
  return [
    {
      id: 'thread-welcome',
      title: 'General Builder Brainstorm',
      createdAt: new Date().toISOString(),
      contextItem: null,
      userProfile: null,
      messages: [
        {
          role: 'assistant',
          content:
            '<p>Welcome to <b>Signal AI Builder Chat</b>! Click <b>💬 Continue in AI Chat →</b> under any article summary to bring that story + its Idea Network here, or ask me anything about what to build next.</p>',
        },
      ],
    },
  ]
}

// Deterministically marks ~1 in 5 high-signal builder/research drops as PRO content
// (plus any URLs explicitly toggled by Admin) so FREE accounts see locked PRO drops.
function isItemProExclusive(item, idx, customProMap) {
  const url = item.url || item.item_url || ''
  if (url && customProMap && url in customProMap) {
    return Boolean(customProMap[url])
  }
  if (item.is_builder_idea && (item.engagement_raw || 0) >= 80 && idx % 4 === 2) {
    return true
  }
  if (item.tier === 1 && idx % 6 === 4) {
    return true
  }
  return false
}

export default function App() {
  const [theme, setTheme] = useState('dark')
  const [status, setStatus] = useState(null)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [retryInfo, setRetryInfo] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  // Auth, Niches & Saved Items state
  const [userProfile, setUserProfile] = useState(null)
  const [localTierOverride, setLocalTierOverride] = useState(() => {
    try {
      return localStorage.getItem(LOCAL_TIER_OVERRIDE_KEY) || ''
    } catch {
      return ''
    }
  })
  const [localNiches, setLocalNiches] = useState(() => loadLocalNiches())
  const [savedItems, setSavedItems] = useState(() => {
    try {
      const raw = localStorage.getItem(LOCAL_SAVED_FALLBACK_KEY)
      return raw ? JSON.parse(raw) : []
    } catch {
      return []
    }
  })

  // PRO Upgrade / Tier Switcher Modal state
  const [upgradeModalOpen, setUpgradeModalOpen] = useState(false)
  const [upgradeReason, setUpgradeReason] = useState('')
  const [adminSecretInput, setAdminSecretInput] = useState('')
  const [tierActionMsg, setTierActionMsg] = useState('')
  const [tierActionErr, setTierActionErr] = useState('')
  const [switchingTier, setSwitchingTier] = useState(false)

  // Admin Console state
  const [adminUsers, setAdminUsers] = useState([])
  const [loadingAdminUsers, setLoadingAdminUsers] = useState(false)
  const [adminUserSearch, setAdminUserSearch] = useState('')
  const [adminGrantEmail, setAdminGrantEmail] = useState('')
  const [adminGrantTier, setAdminGrantTier] = useState('pro')
  const [adminPostSearch, setAdminPostSearch] = useState('')
  const [adminStatusBanner, setAdminStatusBanner] = useState('')
  const [customProMap, setCustomProMap] = useState(() => {
    try {
      const raw = localStorage.getItem(CUSTOM_PRO_URLS_KEY)
      return raw ? JSON.parse(raw) : {}
    } catch {
      return {}
    }
  })

  // Active tab: 'feed' | 'ideas' | 'my-feed' | 'saved' | 'chat' | 'admin'
  const [activeTab, setActiveTab] = useState('feed')
  const [search, setSearch] = useState('')
  const [source, setSource] = useState('')
  const [categoryOrStack, setCategoryOrStack] = useState('')
  const [dept, setDept] = useState('')
  const [sort, setSort] = useState('newest')
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  // AI Builder Chat state
  const [chatThreads, setChatThreads] = useState(() => loadStoredChatThreads())
  const [activeThreadId, setActiveThreadId] = useState(() => loadStoredChatThreads()[0]?.id || 'thread-welcome')
  const [chatInput, setChatInput] = useState('')
  const [sendingChat, setSendingChat] = useState(false)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => {
    try {
      localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(chatThreads))
    } catch {}
  }, [chatThreads])

  // Effective tier: strictly trusts server-verified `userProfile.subscription_tier`.
  // Only a verified Admin can use `localTierOverride` to preview FREE or PRO views.
  const effectiveTier = useMemo(() => {
    const serverTier = (userProfile?.subscription_tier || 'free').toLowerCase()
    if (serverTier === 'suspended') return 'suspended'
    if (serverTier === 'admin' && localTierOverride && ['free', 'pro', 'admin'].includes(localTierOverride)) {
      return localTierOverride
    }
    if (['free', 'pro', 'admin'].includes(serverTier)) {
      return serverTier
    }
    return 'free'
  }, [userProfile, localTierOverride])

  const hasProAccess = effectiveTier === 'pro' || effectiveTier === 'admin'
  const isAdmin = effectiveTier === 'admin'
  const isSuspended = effectiveTier === 'suspended'

  const activeNiches = useMemo(
    () =>
      userProfile?.preferred_depts && userProfile.preferred_depts.length > 0
        ? userProfile.preferred_depts
        : localNiches,
    [userProfile, localNiches]
  )

  const activeThread = useMemo(
    () => chatThreads.find((t) => t.id === activeThreadId) || chatThreads[0],
    [chatThreads, activeThreadId]
  )

  function openUpgradeModal(reason = '') {
    setUpgradeReason(reason)
    setTierActionMsg('')
    setTierActionErr('')
    setUpgradeModalOpen(true)
  }

  async function handleSelectTierMode(targetTier) {
    setTierActionMsg('')
    setTierActionErr('')
    if (!userProfile) {
      setTierActionErr('Please sign in first (top right) so your account tier can be verified.')
      return
    }
    const serverTier = (userProfile?.subscription_tier || 'free').toLowerCase()
    if (serverTier !== 'admin' && !adminSecretInput.trim()) {
      if (targetTier === 'pro') {
        setTierActionMsg('To activate Signal PRO on your account, ask an Administrator to grant PRO to your email (' + userProfile.email + ') or enter the Admin Passcode below.')
      } else {
        setTierActionErr('Enter your server ADMIN_SECRET passcode to unlock Admin mode.')
      }
      return
    }
    setSwitchingTier(true)
    try {
      const res = await claimAdminOrSwitchTier(adminSecretInput.trim(), targetTier)
      if (res?.profile) {
        setUserProfile(res.profile)
      }
      setLocalTierOverride(targetTier)
      try {
        localStorage.setItem(LOCAL_TIER_OVERRIDE_KEY, targetTier)
      } catch {}
      setAdminSecretInput('')
      setTierActionMsg(`Verified & switched account tier to ${targetTier.toUpperCase()}!`)
      if (targetTier === 'admin') {
        loadAdminUsersList()
      }
    } catch (err) {
      setTierActionErr(err.message || 'Could not verify Admin Passcode.')
    } finally {
      setSwitchingTier(false)
    }
  }

  async function loadAdminUsersList() {
    setLoadingAdminUsers(true)
    try {
      const res = await adminGetUsers()
      setAdminUsers(res.users || [])
    } catch (err) {
      console.warn('Could not load admin users list:', err)
    } finally {
      setLoadingAdminUsers(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'admin' && isAdmin) {
      loadAdminUsersList()
    }
  }, [activeTab, isAdmin])

  async function handleAdminSetUserTier(targetUser, nextTier) {
    setAdminStatusBanner('')
    try {
      const res = await adminUpdateUserTier({
        userId: targetUser.user_id,
        email: targetUser.email,
        tier: nextTier,
      })
      const updatedUser = res.user
      setAdminUsers((prev) => {
        const exists = prev.some((u) => u.user_id === updatedUser.user_id || u.email === updatedUser.email)
        if (exists) {
          return prev.map((u) =>
            u.user_id === updatedUser.user_id || u.email === updatedUser.email ? updatedUser : u
          )
        }
        return [updatedUser, ...prev]
      })
      setAdminStatusBanner(`Updated ${updatedUser.email} → ${nextTier.toUpperCase()}`)
    } catch (err) {
      setAdminStatusBanner(`Error: ${err.message || 'Could not update user tier.'}`)
    }
  }

  async function handleAdminGrantByEmail(e) {
    e.preventDefault()
    if (!adminGrantEmail.trim()) return
    await handleAdminSetUserTier({ email: adminGrantEmail.trim() }, adminGrantTier)
    setAdminGrantEmail('')
  }

  async function handleAdminDeleteItem(url, title = '') {
    if (!url) return
    setItems((prev) => prev.filter((i) => (i.url || i.item_url) !== url))
    setAdminStatusBanner(`Removed published post: "${title || url}"`)
    try {
      await adminDeleteFeedItem(url)
    } catch (err) {
      console.warn('Backend delete item warning:', err)
    }
  }

  function handleAdminToggleProItem(url) {
    if (!url) return
    setCustomProMap((prev) => {
      const idx = items.findIndex((i) => (i.url || i.item_url) === url)
      const itemObj = items[idx] || {}
      const currentlyPro = isItemProExclusive(itemObj, idx >= 0 ? idx : 0, prev)
      const next = { ...prev, [url]: !currentlyPro }
      try {
        localStorage.setItem(CUSTOM_PRO_URLS_KEY, JSON.stringify(next))
      } catch {}
      setAdminStatusBanner(
        `${!currentlyPro ? '🔒 Marked post as PRO-only' : '🔓 Marked post as Free for everyone'}`
      )
      return next
    })
  }

  function handleOpenInChat({ item, summary, blueprint, connectedNodes, profileInputs }) {
    if (!hasProAccess) {
      openUpgradeModal('Multi-Turn AI Builder Chat is a Signal PRO feature.')
      return
    }
    const existing = chatThreads.find((t) => t.contextItem?.url === (item.url || item.item_url))
    if (existing) {
      setActiveThreadId(existing.id)
      setActiveTab('chat')
      return
    }
    const newId = `thread-${Date.now()}`
    const connectedSummary =
      connectedNodes?.length > 0
        ? `<p><b>Connected Nearby Drops:</b> ${connectedNodes
            .map((n) => `<a href="${escapeHtml(n.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(n.title)}</a> (${escapeHtml(n.source)})`)
            .join(' · ')}</p>`
        : ''
    const initialAssistantHtml = `
      <p><b>Loaded Story:</b> <a href="${escapeHtml(item.url || item.item_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a> (${escapeHtml(item.source)})</p>
      ${summary ? `<div>${sanitizeHtmlClient(summary)}</div>` : ''}
      ${blueprint ? `<div>${sanitizeHtmlClient(blueprint)}</div>` : ''}
      ${connectedSummary}
      <p>What part of this would you like to explore or build? Ask for architecture steps, starter code, or how to adapt it to your level.</p>
    `.trim()

    const newThread = {
      id: newId,
      title: item.title.slice(0, 48) + (item.title.length > 48 ? '…' : ''),
      createdAt: new Date().toISOString(),
      contextItem: {
        url: item.url || item.item_url,
        title: item.title,
        source: item.source,
        summary,
        blueprint,
      },
      userProfile: profileInputs || null,
      messages: [{ role: 'assistant', content: initialAssistantHtml }],
    }
    setChatThreads((prev) => [newThread, ...prev])
    setActiveThreadId(newId)
    setActiveTab('chat')
  }

  function handleStartBlankChat() {
    const newId = `thread-${Date.now()}`
    const newThread = {
      id: newId,
      title: `Brainstorm #${chatThreads.length + 1}`,
      createdAt: new Date().toISOString(),
      contextItem: null,
      userProfile: null,
      messages: [
        {
          role: 'assistant',
          content:
            '<p>New brainstorm thread started! Tell me your tech stack, education level, and what kind of project or problem you want to tackle.</p>',
        },
      ],
    }
    setChatThreads((prev) => [newThread, ...prev])
    setActiveThreadId(newId)
  }

  function handleDeleteThread(threadId, e) {
    e.stopPropagation()
    setChatThreads((prev) => {
      const remaining = prev.filter((t) => t.id !== threadId)
      if (remaining.length === 0) {
        const fallback = loadStoredChatThreads()
        setActiveThreadId(fallback[0].id)
        return fallback
      }
      if (activeThreadId === threadId) {
        setActiveThreadId(remaining[0].id)
      }
      return remaining
    })
  }

  async function handleSendChat(e, quickPrompt = '') {
    if (e) e.preventDefault()
    if (!hasProAccess) {
      openUpgradeModal('Upgrade to Signal PRO to send unlimited messages in AI Builder Chat.')
      return
    }
    const text = (quickPrompt || chatInput).trim()
    if (!text || !activeThread || sendingChat) return

    const userMsg = { role: 'user', content: text }
    const updatedMessages = [...(activeThread.messages || []), userMsg]

    setChatInput('')
    setSendingChat(true)
    setChatThreads((prev) =>
      prev.map((t) =>
        t.id === activeThread.id
          ? {
              ...t,
              title:
                t.title.startsWith('Brainstorm #') || t.title === 'General Builder Brainstorm'
                  ? text.slice(0, 42)
                  : t.title,
              messages: updatedMessages,
            }
          : t
      )
    )

    try {
      const res = await sendBuilderChatMessage(
        updatedMessages,
        activeThread.contextItem,
        activeThread.userProfile
      )
      const assistantMsg = {
        role: 'assistant',
        content: res.reply_html || '<p>No response generated.</p>',
      }
      setChatThreads((prev) =>
        prev.map((t) =>
          t.id === activeThread.id
            ? { ...t, messages: [...updatedMessages, assistantMsg] }
            : t
        )
      )
    } catch (err) {
      const errMsg = {
        role: 'assistant',
        content: `<p style="color:#e08080;">Error: ${err.message || 'Could not reach AI chat.'}</p>`,
      }
      setChatThreads((prev) =>
        prev.map((t) =>
          t.id === activeThread.id
            ? { ...t, messages: [...updatedMessages, errMsg] }
            : t
        )
      )
    } finally {
      setSendingChat(false)
    }
  }

  function persistLocalSavedBackup(userId, list) {
    try {
      localStorage.setItem(LOCAL_SAVED_FALLBACK_KEY, JSON.stringify(list))
      if (userId) {
        localStorage.setItem(`signal_saved_${userId}`, JSON.stringify(list))
      }
    } catch {}
  }

  function loadLocalSavedBackup(userId) {
    try {
      if (userId) {
        const raw = localStorage.getItem(`signal_saved_${userId}`)
        if (raw) return JSON.parse(raw)
      }
      const fallbackRaw = localStorage.getItem(LOCAL_SAVED_FALLBACK_KEY)
      return fallbackRaw ? JSON.parse(fallbackRaw) : []
    } catch {
      return []
    }
  }

  async function syncUserFromBackend(token) {
    if (!token) {
      setAuthToken('')
      setUserProfile(null)
      return
    }
    setAuthToken(token)

    const instantProfile = decodeJwtProfileFallback(token)
    if (instantProfile) {
      setUserProfile((prev) => prev || instantProfile)
      const cachedSaved = loadLocalSavedBackup(instantProfile.user_id)
      if (cachedSaved.length > 0) setSavedItems(cachedSaved)
    }

    try {
      const res = await getMe()
      if (res?.profile) {
        setUserProfile(res.profile)
        if (res.profile.preferred_depts?.length > 0) {
          setLocalNiches(res.profile.preferred_depts)
          saveLocalNiches(res.profile.preferred_depts)
        }
      }
      const serverSaved = res.saved_items || []
      const localSaved = loadLocalSavedBackup(res.profile?.user_id)
      const mergedMap = new Map()
      ;[...serverSaved, ...localSaved].forEach((row) => {
        if (row?.item_url && !mergedMap.has(row.item_url)) {
          mergedMap.set(row.item_url, row)
        }
      })
      const mergedList = Array.from(mergedMap.values())
      setSavedItems(mergedList)
      persistLocalSavedBackup(res.profile?.user_id, mergedList)
    } catch (err) {
      console.warn('Backend profile sync warning (using local session fallback):', err)
    }
  }

  useEffect(() => {
    if (isSupabaseConfigured && supabase) {
      supabase.auth.getSession().then(({ data: { session } }) => {
        if (session?.access_token) {
          syncUserFromBackend(session.access_token)
        }
      })
      const { data: listener } = supabase.auth.onAuthStateChange((_event, session) => {
        syncUserFromBackend(session?.access_token || '')
      })
      return () => listener?.subscription?.unsubscribe()
    } else {
      try {
        const savedDemo = localStorage.getItem(DEMO_TOKEN_KEY)
        if (savedDemo) syncUserFromBackend(savedDemo)
      } catch {}
    }
  }, [])

  async function handleSignInGoogle() {
    if (!supabase) return
    await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: window.location.origin,
      },
    })
  }

  async function handleSignInEmail(email, password) {
    if (!supabase) return
    const { data, error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) throw error
    if (data?.session?.access_token) {
      await syncUserFromBackend(data.session.access_token)
    }
  }

  async function handleSignUpEmail(email, password, fullName) {
    if (!supabase) return
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { full_name: fullName || email.split('@')[0] } },
    })
    if (error) throw error
    if (data?.session?.access_token) {
      await syncUserFromBackend(data.session.access_token)
      return { needsConfirmation: false }
    }
    return { needsConfirmation: true }
  }

  async function handleSignInDemo(email, name) {
    const token = `demo:${email.trim()}:${name.trim()}`
    try {
      localStorage.setItem(DEMO_TOKEN_KEY, token)
    } catch {}
    await syncUserFromBackend(token)
  }

  async function handleSignOut() {
    if (isSupabaseConfigured && supabase) {
      await supabase.auth.signOut()
    }
    try {
      localStorage.removeItem(DEMO_TOKEN_KEY)
      localStorage.removeItem(LOCAL_TIER_OVERRIDE_KEY)
    } catch {}
    setLocalTierOverride('')
    setAuthToken('')
    setUserProfile(null)
  }

  async function handleSaveNiches(depts) {
    if (!hasProAccess && depts.length > FREE_MAX_NICHES) {
      openUpgradeModal(
        `Free accounts can follow up to ${FREE_MAX_NICHES} niches in ✨ My Feed. Upgrade to Signal PRO for unlimited niches!`
      )
      return
    }
    setLocalNiches(depts)
    saveLocalNiches(depts)
    if (userProfile) {
      setUserProfile((prev) => (prev ? { ...prev, preferred_depts: depts } : prev))
      try {
        const res = await updatePreferences(depts, userProfile?.preferred_sources || [])
        if (res?.profile) setUserProfile(res.profile)
      } catch (err) {
        console.warn('Saved niches locally; backend sync warning:', err)
      }
    }
  }

  function toggleQuickNiche(slug) {
    const next = activeNiches.includes(slug)
      ? activeNiches.filter((d) => d !== slug)
      : [...activeNiches, slug]
    handleSaveNiches(next)
  }

  async function handleSaveOrUpdateItem(item, customNote, editedSummary) {
    const itemUrl = item.url || item.item_url
    const alreadySaved = savedItems.some((x) => x.item_url === itemUrl)
    if (!alreadySaved && !hasProAccess && savedItems.length >= FREE_MAX_SAVED) {
      openUpgradeModal(
        `Free accounts can bookmark up to ${FREE_MAX_SAVED} items in 🔖 Saved & Notes. Upgrade to Signal PRO for unlimited saved items and custom summary overrides!`
      )
      throw new Error(`Free limit (${FREE_MAX_SAVED} saved items) reached — Upgrade to PRO`)
    }

    const nowIso = new Date().toISOString()
    const optimisticRow = {
      user_id: userProfile?.user_id || 'local',
      item_url: itemUrl,
      title: item.title || '',
      source: item.source || '',
      category: item.category || '',
      summary: editedSummary !== undefined ? editedSummary : (item.summary || ''),
      custom_note: customNote || '',
      dept: item.dept || [],
      stack_tags: item.stack_tags || [],
      saved_at: item.saved_at || nowIso,
      updated_at: nowIso,
    }

    setSavedItems((prev) => {
      const next = [optimisticRow, ...prev.filter((x) => x.item_url !== itemUrl)]
      persistLocalSavedBackup(userProfile?.user_id, next)
      return next
    })

    if (!userProfile) return

    try {
      if (isSupabaseConfigured && supabase?.auth?.refreshSession) {
        const refreshed = await supabase.auth.refreshSession()
        if (refreshed?.access_token) setAuthToken(refreshed.access_token)
      }
      const res = await saveUserItem(item, customNote, editedSummary)
      if (res?.saved_item) {
        setSavedItems((prev) => {
          const next = [res.saved_item, ...prev.filter((x) => x.item_url !== itemUrl)]
          persistLocalSavedBackup(userProfile?.user_id, next)
          return next
        })
      }
    } catch (err) {
      console.warn('Backend sync warning (saved locally):', err)
    }
  }

  async function handleRemoveSavedItem(itemUrl) {
    setSavedItems((prev) => {
      const next = prev.filter((x) => x.item_url !== itemUrl)
      persistLocalSavedBackup(userProfile?.user_id, next)
      return next
    })
    if (!userProfile) return
    try {
      await removeSavedItem(itemUrl)
    } catch (err) {
      console.warn('Backend delete warning:', err)
    }
  }

  async function loadAll() {
    setLoading(true)
    setError(null)
    setRetryInfo(null)
    try {
      const onRetry = (attempt, max) =>
        setRetryInfo(`Backend is waking up (attempt ${attempt}/${max})…`)
      const [statusRes, itemsRes] = await Promise.all([
        getStatus(onRetry),
        getItems({}, onRetry),
      ])
      setStatus(statusRes)
      setItems(itemsRes.items || [])
    } catch (err) {
      setError(err.message || 'Could not reach the backend.')
    } finally {
      setLoading(false)
      setRetryInfo(null)
    }
  }

  useEffect(() => {
    loadAll()
    const interval = setInterval(() => {
      getStatus().then(setStatus).catch(() => {})
    }, 60000)
    return () => clearInterval(interval)
  }, [])

  async function handleManualRefresh() {
    setRefreshing(true)
    try {
      await triggerRefresh()
      for (let i = 0; i < 10; i++) {
        await new Promise((r) => setTimeout(r, 4000))
        const s = await getStatus()
        setStatus(s)
        if (!s.fetching) break
      }
      await loadAll()
    } catch (err) {
      setError(err.message || 'Refresh failed.')
    } finally {
      setRefreshing(false)
    }
  }

  const savedByUrl = useMemo(() => {
    const map = {}
    savedItems.forEach((s) => {
      map[s.item_url] = s
    })
    return map
  }, [savedItems])

  const isIdeasTab = activeTab === 'ideas'

  const baseItems = useMemo(() => {
    if (activeTab === 'ideas') {
      return items.filter((i) => i.is_builder_idea)
    }
    if (activeTab === 'my-feed') {
      if (activeNiches.length === 0) return items
      return items.filter((i) => (i.dept || []).some((d) => activeNiches.includes(d)))
    }
    if (activeTab === 'saved') {
      return savedItems.map((s) => ({
        ...s,
        url: s.item_url,
        published_at: s.saved_at,
      }))
    }
    return items
  }, [items, savedItems, activeTab, activeNiches])

  const sourceOptions = useMemo(
    () => Array.from(new Set(baseItems.map((i) => i.source).filter(Boolean))).sort(),
    [baseItems]
  )
  const categoryOptions = useMemo(
    () => Array.from(new Set(baseItems.map((i) => i.category).filter(Boolean))).sort(),
    [baseItems]
  )
  const stackOptions = useMemo(() => {
    const set = new Set()
    baseItems.forEach((i) => (i.stack_tags || []).forEach((t) => set.add(t)))
    return Array.from(set).sort()
  }, [baseItems])

  const deptCounts = useMemo(() => {
    const counts = {}
    baseItems.forEach((i) => {
      ;(i.dept || []).forEach((d) => {
        counts[d] = (counts[d] || 0) + 1
      })
    })
    return counts
  }, [baseItems])

  const filtered = useMemo(() => {
    let result = [...baseItems]
    if (dept) {
      result = result.filter((i) => (i.dept || []).includes(dept))
    }
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(
        (i) =>
          (i.title || '').toLowerCase().includes(q) ||
          (i.summary || '').toLowerCase().includes(q) ||
          (i.custom_note || '').toLowerCase().includes(q) ||
          (i.stack_tags || []).some((t) => t.toLowerCase().includes(q))
      )
    }
    if (source) result = result.filter((i) => i.source === source)
    if (categoryOrStack) {
      result = isIdeasTab
        ? result.filter((i) => (i.stack_tags || []).includes(categoryOrStack))
        : result.filter((i) => i.category === categoryOrStack)
    }
    if (sort === 'newest') {
      result.sort((a, b) => new Date(b.published_at || 0) - new Date(a.published_at || 0))
    } else if (sort === 'oldest') {
      result.sort((a, b) => new Date(a.published_at || 0) - new Date(b.published_at || 0))
    } else if (sort === 'engagement') {
      result.sort((a, b) => (b.engagement_raw || 0) - (a.engagement_raw || 0))
    }
    return result
  }, [baseItems, search, source, categoryOrStack, dept, sort, isIdeasTab])

  const visible = filtered.slice(0, visibleCount)

  const filteredAdminUsers = useMemo(() => {
    if (!adminUserSearch.trim()) return adminUsers
    const q = adminUserSearch.toLowerCase()
    return adminUsers.filter(
      (u) =>
        (u.email || '').toLowerCase().includes(q) ||
        (u.full_name || '').toLowerCase().includes(q) ||
        (u.subscription_tier || '').toLowerCase().includes(q)
    )
  }, [adminUsers, adminUserSearch])

  const filteredAdminPosts = useMemo(() => {
    if (!adminPostSearch.trim()) return items.slice(0, 40)
    const q = adminPostSearch.toLowerCase()
    return items
      .filter(
        (i) =>
          (i.title || '').toLowerCase().includes(q) ||
          (i.source || '').toLowerCase().includes(q) ||
          (i.url || '').toLowerCase().includes(q)
      )
      .slice(0, 40)
  }, [items, adminPostSearch])

  function switchTab(nextTab) {
    setActiveTab(nextTab)
    setSource('')
    setCategoryOrStack('')
    setDept('')
    setVisibleCount(PAGE_SIZE)
  }

  function switchDept(d) {
    setDept(d)
    setVisibleCount(PAGE_SIZE)
  }

  // If an admin has suspended / removed access for this user account
  if (isSuspended) {
    return (
      <div className="app">
        <div className="error-state" style={{ marginTop: '4rem', padding: '2.5rem 1.5rem' }}>
          <h2 style={{ margin: '0 0 0.5rem', color: '#e08080' }}>🚫 Account Access Removed</h2>
          <p style={{ maxWidth: 520, margin: '0 auto 1.2rem' }}>
            Your account ({userProfile?.email}) has been suspended by a Signal administrator and no longer has access to the platform.
          </p>
          <button className="btn" onClick={handleSignOut}>
            Sign out
          </button>
        </div>
      </div>
    )
  }

  const profileWithEffectiveTier = userProfile
    ? { ...userProfile, subscription_tier: effectiveTier }
    : null

  return (
    <div className="app">
      <div className="app-header">
        <div className="app-title" onClick={() => switchTab('feed')} style={{ cursor: 'pointer' }}>
          <span className="mark">▣</span>
          <span className="name">Signal</span>
          <span className="tag">50w tech digest</span>
        </div>
        <div className="header-actions">
          <UserMenu
            userProfile={profileWithEffectiveTier}
            deptMeta={DEPT_META}
            onSignInGoogle={handleSignInGoogle}
            onSignInEmail={handleSignInEmail}
            onSignUpEmail={handleSignUpEmail}
            onSignInDemo={handleSignInDemo}
            onSignOut={handleSignOut}
            onSaveNiches={handleSaveNiches}
            isSupabaseConfigured={isSupabaseConfigured}
          />
          <button
            type="button"
            className={`icon-btn tier-header-btn tier-${effectiveTier}`}
            onClick={() => openUpgradeModal('')}
            title="View FREE vs PRO features or switch to Admin mode"
          >
            {effectiveTier === 'admin'
              ? '🛡️ ADMIN'
              : effectiveTier === 'pro'
              ? '⭐ PRO ACTIVE'
              : '⭐ Upgrade PRO'}
          </button>
          <NewsletterModal userProfile={profileWithEffectiveTier} onProfileUpdate={setUserProfile} />
          <ApiKeySettings />
          <button className="icon-btn" onClick={handleManualRefresh} disabled={refreshing}>
            {refreshing ? 'Refreshing…' : 'Refresh now'}
          </button>
          <button className="icon-btn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
        </div>
      </div>

      <StatusBar status={status} isFetching={refreshing} />

      {loading && (
        <div className="empty-state">
          {retryInfo || 'Loading…'}
          <br />
          <span style={{ fontSize: '0.75rem' }}>
            First load can take 10–30s if the backend was asleep.
          </span>
        </div>
      )}

      {!loading && error && (
        <div className="error-state">
          {error}
          <br />
          <button className="btn" style={{ marginTop: '0.75rem' }} onClick={loadAll}>
            Try again
          </button>
        </div>
      )}

      {!loading && !error && (
        <>
          <KpiStrip items={items} />

          {/* Always-visible tabs across desktop & mobile (+ Admin Console tab when ADMIN) */}
          <div className="tabs">
            <button
              className={`tab ${activeTab === 'feed' ? 'active' : ''}`}
              onClick={() => switchTab('feed')}
            >
              News feed
            </button>
            <button
              className={`tab ${activeTab === 'ideas' ? 'active' : ''}`}
              onClick={() => switchTab('ideas')}
            >
              Builder ideas
            </button>
            <button
              className={`tab ${activeTab === 'my-feed' ? 'active' : ''}`}
              onClick={() => switchTab('my-feed')}
            >
              ✨ My Feed {activeNiches.length > 0 ? `(${activeNiches.length}${!hasProAccess ? `/${FREE_MAX_NICHES}` : ''})` : ''}
            </button>
            <button
              className={`tab ${activeTab === 'saved' ? 'active' : ''}`}
              onClick={() => switchTab('saved')}
            >
              🔖 Saved &amp; Notes ({savedItems.length}{!hasProAccess ? `/${FREE_MAX_SAVED}` : ''})
            </button>
            <button
              className={`tab ${activeTab === 'chat' ? 'active' : ''}`}
              onClick={() => switchTab('chat')}
            >
              {hasProAccess ? `💬 AI Chat (${chatThreads.length})` : '🔒 AI Chat (PRO)'}
            </button>
            {isAdmin && (
              <button
                className={`tab tab-admin ${activeTab === 'admin' ? 'active' : ''}`}
                onClick={() => switchTab('admin')}
              >
                🛡️ Admin Console
              </button>
            )}
          </div>

          {/* ── ADMIN CONSOLE TAB ── */}
          {activeTab === 'admin' && isAdmin ? (
            <div className="admin-console">
              <div className="admin-banner">
                <div>
                  <h3 style={{ margin: 0, fontSize: '1rem' }}>🛡️ Signal Admin Moderation &amp; Access Control</h3>
                  <p style={{ margin: '0.25rem 0 0', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    Take down unwanted published content, lock/unlock PRO posts, grant FREE/PRO/ADMIN access, or suspend accounts.
                  </p>
                </div>
                <button className="btn" onClick={loadAdminUsersList} disabled={loadingAdminUsers}>
                  {loadingAdminUsers ? 'Loading…' : '↻ Sync Users'}
                </button>
              </div>

              {adminStatusBanner && (
                <div className="personal-note-box" style={{ marginBottom: '0.85rem' }}>
                  <b>Admin Action:</b> {adminStatusBanner}
                </div>
              )}

              <div className="admin-grid">
                {/* Panel 1: User Account Access Control */}
                <div className="admin-card">
                  <h4>👥 Account Access &amp; Tier Management</h4>
                  <p className="modal-desc">
                    Grant PRO or ADMIN access to any account (even before they sign up), downgrade to FREE, or suspend access.
                  </p>

                  <form onSubmit={handleAdminGrantByEmail} style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
                    <input
                      type="email"
                      className="modal-input"
                      style={{ flex: 1, minWidth: '180px' }}
                      placeholder="User email (e.g. user@gmail.com)"
                      value={adminGrantEmail}
                      onChange={(e) => setAdminGrantEmail(e.target.value)}
                      required
                    />
                    <select
                      className="modal-input"
                      style={{ width: 'auto' }}
                      value={adminGrantTier}
                      onChange={(e) => setAdminGrantTier(e.target.value)}
                    >
                      <option value="pro">⭐ Grant PRO</option>
                      <option value="free">Set FREE</option>
                      <option value="admin">🛡️ Make ADMIN</option>
                      <option value="suspended">🚫 Remove Access (Suspend)</option>
                    </select>
                    <button type="submit" className="btn btn-primary" style={{ padding: '0.45rem 0.85rem' }}>
                      Apply
                    </button>
                  </form>

                  <input
                    type="text"
                    className="modal-input"
                    placeholder="Filter registered users by email, name, or tier…"
                    value={adminUserSearch}
                    onChange={(e) => setAdminUserSearch(e.target.value)}
                    style={{ marginBottom: '0.6rem' }}
                  />

                  <div className="admin-list-scroll">
                    {filteredAdminUsers.length === 0 ? (
                      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', padding: '0.8rem 0' }}>
                        {loadingAdminUsers
                          ? 'Loading accounts…'
                          : 'No accounts found yet. Use the email box above to pre-grant PRO or suspend any email.'}
                      </div>
                    ) : (
                      filteredAdminUsers.map((u) => {
                        const t = (u.subscription_tier || 'free').toLowerCase()
                        return (
                          <div key={u.user_id || u.email} className="admin-row-item">
                            <div style={{ minWidth: 0, flex: 1 }}>
                              <div style={{ fontWeight: 600, fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                                <span>{u.full_name || u.email}</span>
                                <span className={`tier-badge ${t}`}>{t.toUpperCase()}</span>
                              </div>
                              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--mono)' }}>
                                {u.email}
                              </div>
                            </div>
                            <div style={{ display: 'flex', gap: '0.3rem', flexWrap: 'wrap' }}>
                              <button
                                type="button"
                                className="btn"
                                style={{ padding: '0.22rem 0.5rem', fontSize: '0.7rem' }}
                                onClick={() => handleAdminSetUserTier(u, 'free')}
                              >
                                FREE
                              </button>
                              <button
                                type="button"
                                className="btn"
                                style={{ padding: '0.22rem 0.5rem', fontSize: '0.7rem', borderColor: 'var(--accent)', color: 'var(--accent)' }}
                                onClick={() => handleAdminSetUserTier(u, 'pro')}
                              >
                                ⭐ PRO
                              </button>
                              <button
                                type="button"
                                className="btn"
                                style={{ padding: '0.22rem 0.5rem', fontSize: '0.7rem', borderColor: 'var(--idea)', color: 'var(--idea)' }}
                                onClick={() => handleAdminSetUserTier(u, 'admin')}
                              >
                                🛡️ ADMIN
                              </button>
                              <button
                                type="button"
                                className="btn"
                                style={{
                                  padding: '0.22rem 0.5rem',
                                  fontSize: '0.7rem',
                                  borderColor: t === 'suspended' ? 'var(--good)' : '#e07070',
                                  color: t === 'suspended' ? 'var(--good)' : '#e07070',
                                }}
                                onClick={() => handleAdminSetUserTier(u, t === 'suspended' ? 'free' : 'suspended')}
                              >
                                {t === 'suspended' ? '✅ Restore' : '🚫 Suspend'}
                              </button>
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>
                </div>

                {/* Panel 2: Published Content Moderation */}
                <div className="admin-card">
                  <h4>📰 Published Content Moderation ({items.length} live)</h4>
                  <p className="modal-desc">
                    Search any published article below (or use the <b>🗑️ Take down</b> button directly on any feed card) to remove bad content immediately.
                  </p>

                  <input
                    type="text"
                    className="modal-input"
                    placeholder="Search published posts by title, source, or URL…"
                    value={adminPostSearch}
                    onChange={(e) => setAdminPostSearch(e.target.value)}
                    style={{ marginBottom: '0.6rem' }}
                  />

                  <div className="admin-list-scroll">
                    {filteredAdminPosts.map((post, idx) => {
                      const postUrl = post.url || post.item_url
                      const isProPost = isItemProExclusive(post, idx, customProMap)
                      return (
                        <div key={postUrl} className="admin-row-item">
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ fontWeight: 600, fontSize: '0.8rem', lineHeight: 1.35 }}>
                              {isProPost && <span className="chip chip-pro-lock" style={{ marginRight: 6 }}>🔒 PRO</span>}
                              {post.title}
                            </div>
                            <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', fontFamily: 'var(--mono)' }}>
                              {post.source} · {post.category}
                            </div>
                          </div>
                          <div style={{ display: 'flex', gap: '0.35rem', flexShrink: 0 }}>
                            <button
                              type="button"
                              className="btn"
                              style={{ padding: '0.24rem 0.55rem', fontSize: '0.7rem', borderColor: 'var(--accent)', color: 'var(--accent)' }}
                              onClick={() => handleAdminToggleProItem(postUrl)}
                            >
                              {isProPost ? '🔓 Free' : '🔒 PRO'}
                            </button>
                            <button
                              type="button"
                              className="btn"
                              style={{ padding: '0.24rem 0.55rem', fontSize: '0.7rem', borderColor: '#e07070', color: '#e07070' }}
                              onClick={() => handleAdminDeleteItem(postUrl, post.title)}
                            >
                              🗑️ Take down
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            </div>
          ) : activeTab === 'chat' ? (
            !hasProAccess ? (
              <div className="pro-gate-card">
                <div style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '0.4rem' }}>
                  🔒 Multi-Turn AI Builder Chat is a Signal PRO Feature
                </div>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.86rem', maxWidth: 560, margin: '0 auto 1rem', lineHeight: 1.55 }}>
                  Free accounts include real-time tech feeds, 50-word Inshorts summaries, up to {FREE_MAX_NICHES} personal niches, and {FREE_MAX_SAVED} saved bookmarks. Upgrade to <b>Signal PRO</b> to unlock multi-turn AI Builder Chat with persistent thread history, 4-Point Idea Network Blueprints, and PRO-exclusive drops.
                </p>
                <button className="btn btn-primary" onClick={() => openUpgradeModal('Unlock Multi-Turn AI Builder Chat with Signal PRO.')}>
                  ⭐ View PRO Plan / Unlock Access
                </button>
              </div>
            ) : (
              <div className="chat-workspace">
                <div className="chat-threads-list">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.6rem' }}>
                    <span style={{ fontFamily: 'var(--mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                      CHAT HISTORY ({chatThreads.length})
                    </span>
                    <button
                      type="button"
                      className="btn btn-primary"
                      style={{ padding: '0.25rem 0.6rem', fontSize: '0.74rem' }}
                      onClick={handleStartBlankChat}
                    >
                      + New
                    </button>
                  </div>
                  {chatThreads.map((t) => (
                    <div
                      key={t.id}
                      className={`chat-thread-item ${t.id === activeThread?.id ? 'active' : ''}`}
                      onClick={() => setActiveThreadId(t.id)}
                    >
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.8rem', fontWeight: 500 }}>
                        {t.title}
                      </div>
                      <button
                        type="button"
                        className="thread-del-btn"
                        onClick={(e) => handleDeleteThread(t.id, e)}
                        title="Delete thread"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>

                <div className="chat-main-pane">
                  <div className="chat-pane-header">
                    <div>
                      <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>{activeThread?.title}</div>
                      {activeThread?.contextItem?.title && (
                        <div style={{ fontSize: '0.74rem', color: 'var(--accent)' }}>
                          Linked drop: {activeThread.contextItem.title}
                        </div>
                      )}
                    </div>
                    <button type="button" className="btn" style={{ fontSize: '0.75rem', padding: '0.3rem 0.65rem' }} onClick={() => switchTab('feed')}>
                      ← Back to Feed
                    </button>
                  </div>

                  <div className="chat-messages-scroll">
                    {(activeThread?.messages || []).map((m, idx) => (
                      <div key={idx} className={`chat-bubble ${m.role === 'user' ? 'user' : 'assistant'}`}>
                        <div className="chat-bubble-role">
                          {m.role === 'user' ? 'You' : '▣ Signal AI'}
                        </div>
                        {m.role === 'user' ? (
                          <div>{m.content}</div>
                        ) : (
                          <div dangerouslySetInnerHTML={{ __html: sanitizeHtmlClient(m.content) }} />
                        )}
                      </div>
                    ))}
                    {sendingChat && (
                      <div className="chat-bubble assistant">
                        <div className="chat-bubble-role">▣ Signal AI</div>
                        <div style={{ color: 'var(--text-muted)' }}>Thinking…</div>
                      </div>
                    )}
                  </div>

                  <div className="chat-quick-chips">
                    {[
                      'Give me the step-by-step MVP plan for a weekend',
                      'What folder structure & database schema should I use?',
                      'How can a beginner simplify this project?',
                    ].map((q) => (
                      <button
                        key={q}
                        type="button"
                        className="dept-pill"
                        onClick={(e) => handleSendChat(e, q)}
                        disabled={sendingChat}
                      >
                        {q}
                      </button>
                    ))}
                  </div>

                  <form className="chat-input-row" onSubmit={handleSendChat}>
                    <input
                      type="text"
                      className="modal-input"
                      placeholder="Ask follow-up questions about stack, code, prerequisites, or how to build this…"
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      disabled={sendingChat}
                    />
                    <button type="submit" className="btn btn-primary" disabled={sendingChat || !chatInput.trim()}>
                      {sendingChat ? 'Sending…' : 'Send'}
                    </button>
                  </form>
                </div>
              </div>
            )
          ) : (
            <>
              {activeTab === 'ideas' && (
                <p className="tab-caption">
                  Show HN launches, Product Hunt, r/SideProject &amp; r/startups builds, new GitHub
                  repos, IndieHackers posts, and new model releases — anything where someone shipped
                  something and said what they used.
                </p>
              )}

              {activeTab === 'my-feed' && (
                <div style={{ marginBottom: '0.75rem' }}>
                  <p className="tab-caption" style={{ marginBottom: '0.45rem' }}>
                    Tap the niches below to customize your personal feed ({hasProAccess ? 'Unlimited on PRO' : `Up to ${FREE_MAX_NICHES} niches on Free`}):
                  </p>
                  <div className="dept-bar">
                    {Object.entries(DEPT_META).map(([slug, { label, color }]) => {
                      const selected = activeNiches.includes(slug)
                      return (
                        <button
                          key={slug}
                          type="button"
                          className={`dept-pill ${selected ? 'active' : ''}`}
                          style={selected ? { borderColor: color, color } : {}}
                          onClick={() => toggleQuickNiche(slug)}
                        >
                          {label} {selected ? '✓' : '+'}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}

              {activeTab === 'saved' && (
                <p className="tab-caption">
                  Your personal vault of saved articles, builder ideas, and custom notes ({savedItems.length}{!hasProAccess ? ` / ${FREE_MAX_SAVED} Free slots used` : ' saved'}).
                </p>
              )}

              <div className="dept-bar">
                <button
                  className={`dept-pill ${dept === '' ? 'active' : ''}`}
                  onClick={() => switchDept('')}
                >
                  All
                </button>
                {Object.entries(DEPT_META).map(([slug, { label, color }]) => {
                  const count = deptCounts[slug] || 0
                  if (count === 0) return null
                  return (
                    <button
                      key={slug}
                      className={`dept-pill ${dept === slug ? 'active' : ''}`}
                      style={dept === slug ? { borderColor: color, color } : {}}
                      onClick={() => switchDept(dept === slug ? '' : slug)}
                    >
                      {label}
                      <span className="dept-count">{count}</span>
                    </button>
                  )
                })}
              </div>

              <div className="filter-bar">
                <input
                  type="text"
                  placeholder="Search titles, summaries, notes, stack…"
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value)
                    setVisibleCount(PAGE_SIZE)
                  }}
                />
                <select value={source} onChange={(e) => setSource(e.target.value)}>
                  <option value="">All sources</option>
                  {sourceOptions.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                <select value={categoryOrStack} onChange={(e) => setCategoryOrStack(e.target.value)}>
                  <option value="">{isIdeasTab ? 'All stacks' : 'All categories'}</option>
                  {(isIdeasTab ? stackOptions : categoryOptions).map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
                <select value={sort} onChange={(e) => setSort(e.target.value)}>
                  <option value="newest">Newest first</option>
                  <option value="engagement">Most engagement</option>
                  <option value="oldest">Oldest first</option>
                </select>
              </div>

              <div className="results-caption">
                Showing {visible.length} of {filtered.length} items
                {dept && DEPT_META[dept] && (
                  <span className="dept-active-label"> in {DEPT_META[dept].label}</span>
                )}
              </div>

              {visible.length === 0 ? (
                <div className="empty-state">
                  {activeTab === 'saved'
                    ? 'You have not saved any items yet. Tap "☆ Save to my section" on any card to bookmark it.'
                    : 'No items match these filters. Try clearing search or switching sources.'}
                </div>
              ) : (
                visible.map((item, idx) => (
                  <FeedRow
                    item={item}
                    key={item.url || item.item_url}
                    isAuthenticated={true}
                    userTier={effectiveTier}
                    isProContent={isItemProExclusive(item, idx, customProMap)}
                    savedEntry={savedByUrl[item.url || item.item_url]}
                    onSaveOrUpdate={handleSaveOrUpdateItem}
                    onRemoveSaved={handleRemoveSavedItem}
                    onOpenInChat={handleOpenInChat}
                    onOpenUpgradeModal={openUpgradeModal}
                    onAdminDeleteItem={handleAdminDeleteItem}
                    onAdminToggleProItem={handleAdminToggleProItem}
                  />
                ))
              )}

              {filtered.length > visibleCount && (
                <div className="load-more-row">
                  <button className="btn" onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}>
                    Load more
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* ── FREE vs PRO vs ADMIN Modal ── */}
      {upgradeModalOpen && (
        <div className="modal-overlay" onClick={() => setUpgradeModalOpen(false)}>
          <div
            className="modal-card"
            style={{ maxWidth: '680px', maxHeight: '90vh', overflowY: 'auto' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
              <h3 style={{ margin: 0 }}>⭐ Signal Account Tiers: FREE vs PRO vs ADMIN</h3>
              <button className="btn" onClick={() => setUpgradeModalOpen(false)} style={{ padding: '0.2rem 0.6rem' }}>
                ✕
              </button>
            </div>

            {upgradeReason && (
              <div className="personal-note-box" style={{ borderLeftColor: 'var(--accent)', marginBottom: '0.85rem' }}>
                <b>🔒 Locked Feature:</b> {upgradeReason}
              </div>
            )}

            <div className="tier-compare-grid">
              <div className={`tier-plan-box ${effectiveTier === 'free' ? 'active-plan' : ''}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>Signal FREE</span>
                  <span className="tier-badge">FREE</span>
                </div>
                <div style={{ fontSize: '1.25rem', fontWeight: 800, margin: '0.35rem 0 0.6rem' }}>₹0 / forever</div>
                <ul className="tier-feature-list">
                  <li>✓ Standard News Feed &amp; Builder Ideas</li>
                  <li>✓ 50-word AI summaries on free posts</li>
                  <li>✓ Up to {FREE_MAX_NICHES} niches in <b>✨ My Feed</b></li>
                  <li>✓ Up to {FREE_MAX_SAVED} bookmarks &amp; personal notes</li>
                  <li>✓ Daily Top 10 Traction Newsletter</li>
                  <li style={{ color: 'var(--text-dim)' }}>🔒 PRO-Exclusive Deep-Dive Drops locked</li>
                  <li style={{ color: 'var(--text-dim)' }}>🔒 Idea Network &amp; 4-Point Blueprints locked</li>
                  <li style={{ color: 'var(--text-dim)' }}>🔒 Multi-Turn AI Builder Chat locked</li>
                  <li style={{ color: 'var(--text-dim)' }}>🔒 Weekly AI Playbook &amp; Summary Rewrites locked</li>
                </ul>
                <button
                  type="button"
                  className="btn btn-block"
                  onClick={() => handleSelectTierMode('free')}
                  disabled={switchingTier || effectiveTier === 'free'}
                >
                  {effectiveTier === 'free' ? 'Current Tier (FREE)' : 'Switch to FREE View'}
                </button>
              </div>

              <div className={`tier-plan-box pro-plan ${effectiveTier === 'pro' ? 'active-plan' : ''}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--accent)' }}>Signal PRO</span>
                  <span className="tier-badge pro">PRO</span>
                </div>
                <div style={{ fontSize: '1.25rem', fontWeight: 800, margin: '0.35rem 0 0.6rem' }}>Full Builder Access</div>
                <ul className="tier-feature-list">
                  <li>⭐ <b>Unlocks all 🔒 PRO-Exclusive Drops</b></li>
                  <li>⭐ <b>Unlimited 🕸️ Connect &amp; Brainstorm</b> (4-Point Blueprints)</li>
                  <li>⭐ <b>Unlimited 💬 Multi-Turn AI Builder Chat</b> with history</li>
                  <li>⭐ <b>Unlimited ✨ My Feed niches &amp; 🔖 Saved items</b></li>
                  <li>⭐ <b>Custom Summary Overrides</b> in your vault</li>
                  <li>⭐ <b>🧠 Weekly &ldquo;How to Use It&rdquo; AI Playbook</b> newsletter</li>
                </ul>
                <button
                  type="button"
                  className="btn btn-primary btn-block"
                  onClick={() => handleSelectTierMode('pro')}
                  disabled={switchingTier || effectiveTier === 'pro'}
                >
                  {effectiveTier === 'pro' ? '✓ PRO Active' : '⭐ Activate PRO Access'}
                </button>
              </div>
            </div>

            {/* Site Owner / Admin Elevation Box */}
            <div
              style={{
                marginTop: '1rem',
                paddingTop: '0.85rem',
                borderTop: '1px solid var(--border)',
              }}
            >
              <div style={{ fontWeight: 600, fontSize: '0.84rem', marginBottom: '0.3rem' }}>
                🛡️ Site Owner / Admin Login
              </div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: '0 0 0.55rem' }}>
                Enter your private <code>ADMIN_SECRET</code> (set in Render Environment Variables, or add your email to <code>ADMIN_EMAILS</code>) to unlock the <b>🛡️ Admin Console</b>, remove bad published posts, and grant/suspend user accounts.
              </p>
              <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
                <input
                  type="password"
                  className="modal-input"
                  style={{ flex: 1, minWidth: '190px' }}
                  placeholder="Enter your private ADMIN_SECRET…"
                  value={adminSecretInput}
                  onChange={(e) => setAdminSecretInput(e.target.value)}
                />
                <button
                  type="button"
                  className="btn"
                  style={{ borderColor: 'var(--idea)', color: 'var(--idea)', fontWeight: 600 }}
                  onClick={() => handleSelectTierMode('admin')}
                  disabled={switchingTier}
                >
                  {effectiveTier === 'admin' ? '✓ ADMIN Active' : '🛡️ Unlock ADMIN Mode'}
                </button>
              </div>

              {tierActionMsg && (
                <div style={{ color: 'var(--good)', fontSize: '0.78rem', marginTop: '0.5rem' }}>
                  {tierActionMsg}
                </div>
              )}
              {tierActionErr && (
                <div style={{ color: '#e08080', fontSize: '0.78rem', marginTop: '0.5rem' }}>
                  {tierActionErr}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
