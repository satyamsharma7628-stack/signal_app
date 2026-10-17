import { useEffect, useState } from 'react'
import {
  getNewsletterPreview,
  updateNewsletterPrefs,
  sendTestNewsletter,
} from '../api'

export default function NewsletterModal({ userProfile, onProfileUpdate }) {
  const [open, setOpen] = useState(false)
  const [activeKind, setActiveKind] = useState('daily')
  const [issue, setIssue] = useState(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [previewError, setPreviewError] = useState('')

  const [dailySub, setDailySub] = useState(false)
  const [weeklySub, setWeeklySub] = useState(false)
  const [savingPrefs, setSavingPrefs] = useState(false)
  const [sendingTest, setSendingTest] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')

  useEffect(() => {
    setDailySub(Boolean(userProfile?.daily_newsletter))
    setWeeklySub(Boolean(userProfile?.weekly_newsletter))
  }, [userProfile])

  useEffect(() => {
    if (open) {
      loadPreview(activeKind, false)
    }
  }, [open, activeKind])

  async function loadPreview(kind, force = false) {
    setLoadingPreview(true)
    setPreviewError('')
    try {
      const res = await getNewsletterPreview(kind, force)
      setIssue(res.issue)
    } catch (err) {
      setPreviewError(err.message || 'Could not load newsletter preview.')
    } finally {
      setLoadingPreview(false)
    }
  }

  async function handleTogglePrefs(nextDaily, nextWeekly) {
    if (!userProfile) return
    setDailySub(nextDaily)
    setWeeklySub(nextWeekly)
    setSavingPrefs(true)
    setStatusMsg('')
    try {
      const res = await updateNewsletterPrefs(nextDaily, nextWeekly)
      onProfileUpdate?.(res.profile)
      setStatusMsg('Newsletter preferences saved!')
    } catch (err) {
      setStatusMsg(err.message || 'Failed to save preferences.')
    } finally {
      setSavingPrefs(false)
    }
  }

  async function handleSendTest() {
    setSendingTest(true)
    setStatusMsg('')
    try {
      const res = await sendTestNewsletter(activeKind)
      if (res.delivery?.sent) {
        setStatusMsg(`Sent ${activeKind} issue to ${res.delivery.to} via ${res.delivery.provider}!`)
      } else {
        setStatusMsg(res.delivery?.message || 'Preview ready (configure SMTP/Brevo on Render to email).')
      }
    } catch (err) {
      setStatusMsg(err.message || 'Could not send test email.')
    } finally {
      setSendingTest(false)
    }
  }

  const subCount = (dailySub ? 1 : 0) + (weeklySub ? 1 : 0)

  return (
    <>
      <button className="icon-btn" onClick={() => setOpen(true)}>
        📬 Newsletter {subCount > 0 ? `(${subCount} active)` : ''}
      </button>

      {open && (
        <div className="modal-overlay" onClick={() => setOpen(false)}>
          <div
            className="modal-card"
            style={{ maxWidth: '680px', maxHeight: '88vh', overflowY: 'auto' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
              <h3 style={{ margin: 0 }}>📬 Signal AI Newsletters</h3>
              <button className="btn" onClick={() => setOpen(false)} style={{ padding: '0.25rem 0.6rem' }}>
                ✕
              </button>
            </div>
            <p className="modal-desc">
              Pre-generated once per issue and cached in Supabase so AI costs stay at ₹0 regardless of subscriber count.
            </p>

            {/* Subscription toggles */}
            <div className="newsletter-toggles-box">
              <div className="newsletter-option">
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.88rem' }}>
                    ⚡ Daily Top 10 External Traction Digest <span className="tier-badge">FREE</span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Every morning: the 10 highest-engaged posts from HN, GitHub, Reddit, Product Hunt &amp; arXiv in 50 words each.
                  </div>
                </div>
                <input
                  type="checkbox"
                  checked={dailySub}
                  disabled={!userProfile || savingPrefs}
                  onChange={(e) => handleTogglePrefs(e.target.checked, weeklySub)}
                  style={{ width: 18, height: 18, accentColor: 'var(--accent)' }}
                />
              </div>

              <div className="newsletter-option" style={{ marginTop: '0.6rem', paddingTop: '0.6rem', borderTop: '1px solid var(--border)' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.88rem' }}>
                    🧠 Weekly &ldquo;How to Use It&rdquo; AI Playbook <span className="tier-badge pro">PRO</span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Every Sunday: AI-synthesized tools to adopt, engineering lessons to steal, and a weekend builder idea from the week&apos;s top drops.
                  </div>
                </div>
                <input
                  type="checkbox"
                  checked={weeklySub}
                  disabled={!userProfile || savingPrefs}
                  onChange={(e) => handleTogglePrefs(dailySub, e.target.checked)}
                  style={{ width: 18, height: 18, accentColor: 'var(--accent)' }}
                />
              </div>

              {!userProfile && (
                <div style={{ fontSize: '0.75rem', color: 'var(--accent)', marginTop: '0.5rem' }}>
                  Sign in with Google or Email in the top bar to save your subscription preferences.
                </div>
              )}
              {statusMsg && (
                <div style={{ fontSize: '0.76rem', color: 'var(--good)', marginTop: '0.5rem' }}>
                  {statusMsg}
                </div>
              )}
            </div>

            {/* Live issue preview switcher */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '0.9rem 0 0.6rem', flexWrap: 'wrap', gap: '0.5rem' }}>
              <div className="tabs" style={{ margin: 0 }}>
                <button
                  className={`tab ${activeKind === 'daily' ? 'active' : ''}`}
                  onClick={() => setActiveKind('daily')}
                >
                  Preview Daily Top 10
                </button>
                <button
                  className={`tab ${activeKind === 'weekly' ? 'active' : ''}`}
                  onClick={() => setActiveKind('weekly')}
                >
                  Preview Weekly Playbook
                </button>
              </div>

              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <button
                  className="btn"
                  style={{ fontSize: '0.75rem', padding: '0.35rem 0.65rem' }}
                  onClick={() => loadPreview(activeKind, true)}
                  disabled={loadingPreview}
                >
                  ↻ Regenerate
                </button>
                {userProfile && (
                  <button
                    className="btn btn-primary"
                    style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }}
                    onClick={handleSendTest}
                    disabled={sendingTest}
                  >
                    {sendingTest ? 'Sending…' : '✉ Send test to my email'}
                  </button>
                )}
              </div>
            </div>

            <div className="newsletter-preview-frame">
              {loadingPreview && (
                <div className="empty-state" style={{ padding: '2rem 1rem' }}>
                  Generating {activeKind === 'daily' ? 'Daily Top 10' : 'Weekly AI Playbook'} issue…
                </div>
              )}
              {!loadingPreview && previewError && (
                <div className="error-state">{previewError}</div>
              )}
              {!loadingPreview && !previewError && issue && (
                <div dangerouslySetInnerHTML={{ __html: issue.html_body }} />
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
