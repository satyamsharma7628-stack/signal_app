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
} from './api'
import { supabase, isSupabaseConfigured } from './supabaseClient'

const PAGE_SIZE = 12
const DEMO_TOKEN_KEY = 'signal_demo_auth_token'

const DEPT_META = {
  'cybersecurity':   { label: '🔒 Cybersecurity',   color: '#e07070' },
  'ai-ml':           { label: '🤖 AI / ML',          color: '#a78bfa' },
  'gaming-tech':     { label: '🎮 Gaming Tech',       color: '#60b8ff' },
  'cloud':           { label: '☁️ Cloud',             color: '#5fbf7a' },
  'web-dev':         { label: '🌐 Web Dev',           color: '#ff8c1a' },
  'innovator':       { label: '🚀 Innovator',         color: '#f9c04a' },
  'random-dev-idea': { label: '🎲 Random Dev Idea',   color: '#8b8a85' },
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

  // Active tab: 'feed' | 'ideas' | 'my-feed' | 'saved'
  const [activeTab, setActiveTab] = useState('feed')
  const [search, setSearch] = useState('')
  const [source, setSource] = useState('')
  const [categoryOrStack, setCategoryOrStack] = useState('')
  const [dept, setDept] = useState('')
  const [sort, setSort] = useState('newest')
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

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
      setSavedItems(res.saved_items || [])
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
    const res = await saveUserItem(item, customNote, editedSummary)
    const updated = res.saved_item
    setSavedItems((prev) => {
      const filtered = prev.filter((x) => x.item_url !== updated.item_url)
      return [updated, ...filtered]
    })
  }

  async function handleRemoveSavedItem(itemUrl) {
    await removeSavedItem(itemUrl)
    setSavedItems((prev) => prev.filter((x) => x.item_url !== itemUrl))
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
        <div className="app-title">
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
          </div>

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
    </div>
  )
}
