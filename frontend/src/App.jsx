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
} from './api'
import { supabase, isSupabaseConfigured } from './supabaseClient'

const PAGE_SIZE = 12
const DEMO_TOKEN_KEY = 'signal_demo_auth_token'
const CHAT_HISTORY_KEY = 'signal_ai_chat_threads_v1'

const DEPT_META = {
  'cybersecurity':   { label: '🔒 Cybersecurity',   color: '#e07070' },
  'ai-ml':           { label: '🤖 AI / ML',          color: '#a78bfa' },
  'gaming-tech':     { label: '🎮 Gaming Tech',       color: '#60b8ff' },
  'cloud':           { label: '☁️ Cloud',             color: '#5fbf7a' },
  'web-dev':         { label: '🌐 Web Dev',           color: '#ff8c1a' },
  'innovator':       { label: '🚀 Innovator',         color: '#f9c04a' },
  'random-dev-idea': { label: '🎲 Random Dev Idea',   color: '#8b8a85' },
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

export default function App() {
  const [theme, setTheme] = useState('dark')
  const [status, setStatus] = useState(null)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [retryInfo, setRetryInfo] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  // Auth & User state
  const [userProfile, setUserProfile] = useState(null)
  const [savedItems, setSavedItems] = useState([])

  // Active tab: 'feed' | 'ideas' | 'my-feed' | 'saved' | 'chat'
  const [activeTab, setActiveTab] = useState('feed')
  const [search, setSearch] = useState('')
  const [source, setSource] = useState('')
  const [categoryOrStack, setCategoryOrStack] = useState('')
  const [dept, setDept] = useState('')
  const [sort, setSort] = useState('newest')
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  // AI Builder Chat state with persistent thread history
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

  const activeThread = useMemo(
    () => chatThreads.find((t) => t.id === activeThreadId) || chatThreads[0],
    [chatThreads, activeThreadId]
  )

  function handleOpenInChat({ item, summary, blueprint, connectedNodes, profileInputs }) {
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
            .map((n) => `<a href="${n.url}" target="_blank" rel="noreferrer">${n.title}</a> (${n.source})`)
            .join(' · ')}</p>`
        : ''
    const initialAssistantHtml = `
      <p><b>Loaded Story:</b> <a href="${item.url || item.item_url}" target="_blank" rel="noreferrer">${item.title}</a> (${item.source})</p>
      ${summary ? `<div style="margin:0.4rem 0;color:var(--text-muted);">${summary}</div>` : ''}
      ${blueprint ? `<div style="margin:0.5rem 0;padding:0.5rem 0.7rem;background:var(--bg);border-left:3px solid var(--accent);border-radius:4px;">${blueprint}</div>` : ''}
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
    if (!userId) return
    try {
      localStorage.setItem(`signal_saved_${userId}`, JSON.stringify(list))
    } catch {}
  }

  function loadLocalSavedBackup(userId) {
    if (!userId) return []
    try {
      const raw = localStorage.getItem(`signal_saved_${userId}`)
      return raw ? JSON.parse(raw) : []
    } catch {
      return []
    }
  }

  async function syncUserFromBackend(token) {
    if (!token) {
      setAuthToken('')
      setUserProfile(null)
      setSavedItems([])
      return
    }
    setAuthToken(token)
    try {
      const res = await getMe()
      setUserProfile(res.profile)
      const serverSaved = res.saved_items || []
      const localSaved = loadLocalSavedBackup(res.profile?.user_id)
      const mergedMap = new Map()
      ;[...serverSaved, ...localSaved].forEach((row) => {
        if (row?.item_url && !mergedMap.has(row.item_url)) {
          mergedMap.set(row.item_url, row)
        }
      })
      setSavedItems(Array.from(mergedMap.values()))
    } catch (err) {
      console.warn('Session check failed:', err)
      setAuthToken('')
      setUserProfile(null)
      setSavedItems([])
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
    } catch {}
    setAuthToken('')
    setUserProfile(null)
    setSavedItems([])
    if (activeTab === 'my-feed' || activeTab === 'saved') {
      setActiveTab('feed')
    }
  }

  async function handleSaveNiches(depts) {
    const res = await updatePreferences(depts, userProfile?.preferred_sources || [])
    setUserProfile(res.profile)
  }

  async function handleSaveOrUpdateItem(item, customNote, editedSummary) {
    const itemUrl = item.url || item.item_url
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
      const prefDepts = userProfile?.preferred_depts || []
      if (prefDepts.length === 0) return items
      return items.filter((i) => (i.dept || []).some((d) => prefDepts.includes(d)))
    }
    if (activeTab === 'saved') {
      return savedItems.map((s) => ({
        ...s,
        url: s.item_url,
        published_at: s.saved_at,
      }))
    }
    return items
  }, [items, savedItems, activeTab, userProfile])

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
            userProfile={userProfile}
            deptMeta={DEPT_META}
            onSignInGoogle={handleSignInGoogle}
            onSignInEmail={handleSignInEmail}
            onSignUpEmail={handleSignUpEmail}
            onSignInDemo={handleSignInDemo}
            onSignOut={handleSignOut}
            onSaveNiches={handleSaveNiches}
            isSupabaseConfigured={isSupabaseConfigured}
          />
          <NewsletterModal userProfile={userProfile} onProfileUpdate={setUserProfile} />
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

          <div className="tabs" style={{ flexWrap: 'wrap' }}>
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
            {userProfile && (
              <>
                <button
                  className={`tab ${activeTab === 'my-feed' ? 'active' : ''}`}
                  onClick={() => switchTab('my-feed')}
                >
                  ✨ My Feed
                  {(userProfile.preferred_depts || []).length > 0 &&
                    ` (${userProfile.preferred_depts.length})`}
                </button>
                <button
                  className={`tab ${activeTab === 'saved' ? 'active' : ''}`}
                  onClick={() => switchTab('saved')}
                >
                  🔖 Saved &amp; Notes ({savedItems.length})
                </button>
              </>
            )}
            <button
              className={`tab ${activeTab === 'chat' ? 'active' : ''}`}
              onClick={() => switchTab('chat')}
            >
              💬 AI Chat ({chatThreads.length})
            </button>
          </div>

          {activeTab === 'chat' ? (
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
                        <div dangerouslySetInnerHTML={{ __html: m.content }} />
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
          ) : (
            <>
              {activeTab === 'ideas' && (
                <p className="tab-caption">
                  Show HN launches, Product Hunt, r/SideProject &amp; r/startups builds, new GitHub
                  repos, IndieHackers posts, and new model releases — anything where someone shipped
                  something and said what they used.
                </p>
              )}

              {activeTab === 'my-feed' && userProfile && (
                <p className="tab-caption">
                  {(userProfile.preferred_depts || []).length > 0 ? (
                    <>
                      Showing drops matching your saved niches:{' '}
                      <b>
                        {userProfile.preferred_depts
                          .map((d) => DEPT_META[d]?.label || d)
                          .join(', ')}
                      </b>
                      . Use <b>🎯 My Niches</b> in the top bar anytime to change them.
                    </>
                  ) : (
                    <>
                      You haven&apos;t picked any niche sections yet — click <b>🎯 My Niches</b> in the
                      top bar to choose your favorite tech departments.
                    </>
                  )}
                </p>
              )}

              {activeTab === 'saved' && userProfile && (
                <p className="tab-caption">
                  Your personal vault of saved articles, builder ideas, and custom notes/summaries.
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
                    ? 'You have not saved any items yet. Click "☆ Save to my section" on any card to bookmark it.'
                    : 'No items match these filters. Try clearing search or switching sources.'}
                </div>
              ) : (
                visible.map((item) => (
                  <FeedRow
                    item={item}
                    key={item.url || item.item_url}
                    isAuthenticated={Boolean(userProfile)}
                    savedEntry={savedByUrl[item.url || item.item_url]}
                    onSaveOrUpdate={handleSaveOrUpdateItem}
                    onRemoveSaved={handleRemoveSavedItem}
                    onOpenInChat={handleOpenInChat}
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
    </div>
  )
}
