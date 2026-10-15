import { useState } from 'react'

export default function UserMenu({
  userProfile,
  deptMeta,
  onSignInGoogle,
  onSignInEmail,
  onSignUpEmail,
  onSignInDemo,
  onSignOut,
  onSaveNiches,
  isSupabaseConfigured,
}) {
  const [nicheModalOpen, setNicheModalOpen] = useState(false)
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [isSignUp, setIsSignUp] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [authError, setAuthError] = useState('')
  const [authMessage, setAuthMessage] = useState('')
  const [loadingAuth, setLoadingAuth] = useState(false)

  const [selectedDepts, setSelectedDepts] = useState([])
  const [saving, setSaving] = useState(false)

  function openNiches() {
    setSelectedDepts(userProfile?.preferred_depts || [])
    setNicheModalOpen(true)
  }

  function toggleDept(slug) {
    setSelectedDepts((prev) =>
      prev.includes(slug) ? prev.filter((d) => d !== slug) : [...prev, slug]
    )
  }

  async function handleSaveNiches() {
    setSaving(true)
    try {
      await onSaveNiches(selectedDepts)
      setNicheModalOpen(false)
    } finally {
      setSaving(false)
    }
  }

  async function handleEmailSubmit(e) {
    e.preventDefault()
    setAuthError('')
    setAuthMessage('')
    if (!email.trim()) {
      setAuthError('Please enter your email address.')
      return
    }
    if (!isSupabaseConfigured) {
      onSignInDemo(email, fullName || email.split('@')[0])
      setAuthModalOpen(false)
      return
    }
    if (!password || password.length < 6) {
      setAuthError('Password must be at least 6 characters.')
      return
    }
    setLoadingAuth(true)
    try {
      if (isSignUp) {
        const res = await onSignUpEmail(email.trim(), password, fullName.trim())
        if (res?.needsConfirmation) {
          setAuthMessage('Check your email inbox to confirm your account, or sign in if confirmation is disabled in Supabase.')
        } else {
          setAuthModalOpen(false)
        }
      } else {
        await onSignInEmail(email.trim(), password)
        setAuthModalOpen(false)
      }
    } catch (err) {
      setAuthError(err.message || 'Authentication failed.')
    } finally {
      setLoadingAuth(false)
    }
  }

  if (!userProfile) {
    return (
      <>
        <button className="icon-btn auth-btn" onClick={() => setAuthModalOpen(true)}>
          <span>👤</span> Sign in / Join
        </button>

        {authModalOpen && (
          <div className="modal-overlay" onClick={() => setAuthModalOpen(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <h3>{isSignUp ? 'Create your Signal account' : 'Sign in to Signal'}</h3>
              <p className="modal-desc">
                Save your favorite tech niches, bookmark builder ideas, and keep personal notes.
              </p>

              {isSupabaseConfigured && (
                <>
                  <button
                    type="button"
                    className="btn btn-block"
                    style={{ marginBottom: '0.75rem', fontWeight: 600, borderColor: 'var(--accent)' }}
                    onClick={onSignInGoogle}
                  >
                    <span style={{ color: 'var(--accent)', fontWeight: 800, marginRight: 6 }}>G</span>
                    Continue with Google
                  </button>
                  <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'var(--text-dim)', marginBottom: '0.75rem' }}>
                    — or use email (no Google Cloud setup needed) —
                  </div>
                </>
              )}

              <form onSubmit={handleEmailSubmit}>
                {isSignUp && (
                  <input
                    type="text"
                    placeholder="Your display name"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    className="modal-input"
                    style={{ marginBottom: '0.5rem' }}
                  />
                )}
                <input
                  type="email"
                  placeholder="Email address (e.g. you@gmail.com)"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="modal-input"
                  style={{ marginBottom: '0.5rem' }}
                  required
                />
                {isSupabaseConfigured && (
                  <input
                    type="password"
                    placeholder="Password (min 6 characters)"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="modal-input"
                    required
                  />
                )}

                {authError && (
                  <p style={{ color: '#e08080', fontSize: '0.78rem', margin: '0.5rem 0 0' }}>
                    {authError}
                  </p>
                )}
                {authMessage && (
                  <p style={{ color: 'var(--good)', fontSize: '0.78rem', margin: '0.5rem 0 0' }}>
                    {authMessage}
                  </p>
                )}

                <div className="modal-actions">
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      setIsSignUp(!isSignUp)
                      setAuthError('')
                      setAuthMessage('')
                    }}
                  >
                    {isSignUp ? 'Have an account? Sign in' : 'New user? Create account'}
                  </button>
                  <button type="button" className="btn" onClick={() => setAuthModalOpen(false)}>
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-primary" disabled={loadingAuth}>
                    {loadingAuth ? 'Please wait…' : isSignUp ? 'Sign up' : 'Sign in'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </>
    )
  }

  const tierLabel = (userProfile.subscription_tier || 'free').toUpperCase()

  return (
    <>
      <div className="user-bar">
        <button className="icon-btn" onClick={openNiches} title="Customize your personal niche feed">
          🎯 My Niches ({(userProfile.preferred_depts || []).length})
        </button>
        <div className="user-pill">
          {userProfile.avatar_url ? (
            <img src={userProfile.avatar_url} alt="" className="user-avatar" />
          ) : (
            <span className="user-avatar-fallback">
              {(userProfile.full_name || userProfile.email || 'U')[0].toUpperCase()}
            </span>
          )}
          <span className="user-name">{userProfile.full_name || userProfile.email}</span>
          <span className={`tier-badge ${tierLabel === 'PRO' ? 'pro' : ''}`}>{tierLabel}</span>
          <button className="signout-link" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </div>

      {nicheModalOpen && (
        <div className="modal-overlay" onClick={() => setNicheModalOpen(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3>Your Personal Niche Sections</h3>
            <p className="modal-desc">
              Pick the tech niches you care about most. Your <b>✨ My Feed</b> tab will automatically
              filter down to drops in these sections (and future niche alerts will use this list).
            </p>
            <div className="niche-grid">
              {Object.entries(deptMeta).map(([slug, { label, color }]) => {
                const active = selectedDepts.includes(slug)
                return (
                  <button
                    key={slug}
                    type="button"
                    className={`dept-pill ${active ? 'active' : ''}`}
                    style={active ? { borderColor: color, color } : {}}
                    onClick={() => toggleDept(slug)}
                  >
                    {label} {active ? '✓' : '+'}
                  </button>
                )
              })}
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setNicheModalOpen(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleSaveNiches} disabled={saving}>
                {saving ? 'Saving…' : 'Save my niches'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
