import { useEffect, useState } from 'react'
import { getSummary, generateIdeaNetwork } from '../api'

const DEPT_META = {
  'cybersecurity':   { label: '🔒 Cybersecurity', color: '#e07070' },
  'ai-ml':           { label: '🤖 AI / ML',        color: '#a78bfa' },
  'gaming-tech':     { label: '🎮 Gaming Tech',     color: '#60b8ff' },
  'cloud':           { label: '☁️ Cloud',           color: '#5fbf7a' },
  'web-dev':         { label: '🌐 Web Dev',         color: '#ff8c1a' },
  'innovator':       { label: '🚀 Innovator',       color: '#f9c04a' },
  'random-dev-idea': { label: '🎲 Random',          color: '#8b8a85' },
}

const CREATIVITY_PROFILE_KEY = 'signal_user_creativity_profile'

const EDUCATION_OPTIONS = [
  'High School / First-Year Beginner',
  'CS / Engineering Undergrad (2nd–4th Year)',
  'Self-Taught / Indie Hacker',
  'Postgrad / Masters / Researcher',
  'Working Software Engineer / Pro',
]

const GOAL_OPTIONS = [
  'Weekend Hackathon / Resume Project',
  'College Capstone / Research Project',
  'Micro-SaaS / Side-Income Product',
  'Open-Source Tool / Developer Library',
]

const CREATIVITY_MODES = [
  { id: 'mashup',     label: '🔗 Cross-Pollinate (Mash up with nearby drops)' },
  { id: 'practical',  label: '🛠️ Practical Use (Where can I use this today?)' },
  { id: 'contrarian', label: '🚀 Twist / Niche Spin-Off (Find the gap)' },
  { id: 'learn',      label: '🎓 Learn-by-Building Roadmap (For my level)' },
]

function loadSavedCreativityProfile() {
  try {
    const raw = localStorage.getItem(CREATIVITY_PROFILE_KEY)
    if (raw) return JSON.parse(raw)
  } catch {}
  return {
    educationLevel: EDUCATION_OPTIONS[1],
    builderGoal: GOAL_OPTIONS[0],
    userBackground: '',
    creativityMode: 'mashup',
  }
}

export default function FeedRow({
  item,
  isAuthenticated,
  savedEntry,
  onSaveOrUpdate,
  onRemoveSaved,
  onOpenInChat,
}) {
  const [expanded, setExpanded] = useState(false)
  const [summary, setSummary] = useState(null)
  const [loadingSummary, setLoadingSummary] = useState(false)
  const [summaryError, setSummaryError] = useState(null)

  // Idea Network & Creativity section state (lives inside the summary box)
  const [ideateOpen, setIdeateOpen] = useState(false)
  const [educationLevel, setEducationLevel] = useState(() => loadSavedCreativityProfile().educationLevel)
  const [builderGoal, setBuilderGoal] = useState(() => loadSavedCreativityProfile().builderGoal)
  const [userBackground, setUserBackground] = useState(() => loadSavedCreativityProfile().userBackground)
  const [creativityMode, setCreativityMode] = useState(() => loadSavedCreativityProfile().creativityMode)
  const [loadingIdeate, setLoadingIdeate] = useState(false)
  const [ideateResult, setIdeateResult] = useState(null)
  const [ideateError, setIdeateError] = useState('')

  const [editingNote, setEditingNote] = useState(false)
  const [noteDraft, setNoteDraft] = useState(savedEntry?.custom_note || '')
  const [summaryDraft, setSummaryDraft] = useState(savedEntry?.summary || item.summary || '')
  const [savingItem, setSavingItem] = useState(false)
  const [actionFeedback, setActionFeedback] = useState('')

  const itemUrl = item.url || item.item_url
  const isSaved = Boolean(savedEntry)

  useEffect(() => {
    if (savedEntry) {
      setNoteDraft(savedEntry.custom_note || '')
      setSummaryDraft(savedEntry.summary || item.summary || '')
    }
  }, [savedEntry, item.summary])

  const pubDate = (item.published_at || item.saved_at)
    ? new Date(item.published_at || item.saved_at).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : 'n/a'

  async function handleExpand() {
    const next = !expanded
    setExpanded(next)
    if (next && summary === null && !loadingSummary) {
      setLoadingSummary(true)
      setSummaryError(null)
      try {
        const res = await getSummary({ ...item, url: itemUrl })
        setSummary(res.summary)
      } catch (err) {
        setSummaryError(err.message || 'Failed to load summary')
      } finally {
        setLoadingSummary(false)
      }
    }
  }

  async function handleGenerateIdeaNetwork(e) {
    e.preventDefault()
    const profileToSave = {
      educationLevel,
      builderGoal,
      userBackground,
      creativityMode,
    }
    try {
      localStorage.setItem(CREATIVITY_PROFILE_KEY, JSON.stringify(profileToSave))
    } catch {}

    setLoadingIdeate(true)
    setIdeateError('')
    try {
      const res = await generateIdeaNetwork(item, {
        ...profileToSave,
        currentSummary: summary || item.summary || '',
      })
      setIdeateResult(res)
    } catch (err) {
      setIdeateError(err.message || 'Could not generate Idea Network connections.')
    } finally {
      setLoadingIdeate(false)
    }
  }

  async function handleToggleBookmark(e) {
    e.preventDefault()
    e.stopPropagation()
    if (!isAuthenticated) return
    setSavingItem(true)
    setActionFeedback('')
    try {
      if (isSaved) {
        await onRemoveSaved(itemUrl)
        setActionFeedback('Removed from your saved section.')
      } else {
        await onSaveOrUpdate(item, noteDraft, summaryDraft || item.summary || '')
        setActionFeedback('Saved to 🔖 Saved & Notes!')
      }
      setTimeout(() => setActionFeedback(''), 3000)
    } catch (err) {
      setActionFeedback(err.message || 'Could not save item.')
    } finally {
      setSavingItem(false)
    }
  }

  async function handleSaveEdits(e) {
    e.preventDefault()
    e.stopPropagation()
    setSavingItem(true)
    setActionFeedback('')
    try {
      await onSaveOrUpdate(item, noteDraft, summaryDraft)
      setEditingNote(false)
      setActionFeedback('Note & custom summary saved!')
      setTimeout(() => setActionFeedback(''), 3000)
    } catch (err) {
      setActionFeedback(err.message || 'Could not save note.')
    } finally {
      setSavingItem(false)
    }
  }

  const depts = item.dept || []
  const displayedSummary = savedEntry?.summary || item.summary || 'No summary available.'

  return (
    <div className={`row ${item.is_builder_idea ? 'is-idea' : ''}`}>
      <div className="row-top">
        <div className="row-badges">
          {item.tier && <span className="chip chip-tier">T{item.tier}</span>}
          <span className="chip chip-source">{item.source}</span>
          <span className="chip chip-cat">{item.category}</span>
          {item.is_builder_idea && <span className="chip chip-idea">builder idea</span>}
          {isSaved && <span className="chip chip-saved">★ saved</span>}
        </div>
        <div className="row-date">{pubDate}</div>
      </div>

      <a className="row-title" href={itemUrl} target="_blank" rel="noreferrer">
        {item.title}
      </a>
      <div className="row-summary">{displayedSummary}</div>

      {savedEntry?.custom_note && !editingNote && (
        <div className="personal-note-box">
          <b>Your note:</b> {savedEntry.custom_note}
        </div>
      )}

      {depts.length > 0 && (
        <div className="dept-chips-row">
          {depts.map((d) => {
            const meta = DEPT_META[d]
            if (!meta) return null
            return (
              <span
                key={d}
                className="chip chip-dept"
                style={{ borderColor: meta.color, color: meta.color }}
              >
                {meta.label}
              </span>
            )
          })}
        </div>
      )}

      {item.stack_tags?.length > 0 && (
        <div className="stack-row">
          {item.stack_tags.map((tag) => (
            <span className="chip chip-stack" key={tag}>
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="row-meta">
        {item.engagement_raw > 0 && (
          <span className="engagement">▲ {Math.round(item.engagement_raw)}</span>
        )}
        <span className="row-url">{itemUrl}</span>
      </div>

      <div className="row-actions-bar">
        <button type="button" className="summary-toggle" onClick={handleExpand}>
          {expanded ? '▾' : '▸'} {expanded ? 'Hide 50w AI summary' : 'View 50w AI summary'}
        </button>

        {isAuthenticated && (
          <div className="user-item-actions">
            {actionFeedback && (
              <span style={{ fontSize: '0.72rem', color: 'var(--good)', fontFamily: 'var(--mono)' }}>
                {actionFeedback}
              </span>
            )}
            <button
              type="button"
              className={`summary-toggle ${isSaved ? 'active-bookmark' : ''}`}
              onClick={handleToggleBookmark}
              disabled={savingItem}
            >
              {savingItem ? 'Saving…' : isSaved ? '★ Saved' : '☆ Save to my section'}
            </button>
            <button
              type="button"
              className="summary-toggle"
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                setNoteDraft(savedEntry?.custom_note || '')
                setSummaryDraft(savedEntry?.summary || item.summary || '')
                setEditingNote(!editingNote)
              }}
            >
              ✎ {savedEntry?.custom_note ? 'Edit note / summary' : 'Add note / edit'}
            </button>
          </div>
        )}
      </div>

      {editingNote && isAuthenticated && (
        <div className="edit-note-panel" onClick={(e) => e.stopPropagation()}>
          <label className="edit-label">Personal note / builder takeaway:</label>
          <textarea
            className="modal-input"
            rows={2}
            placeholder="Add your own note, idea twist, or action item…"
            value={noteDraft}
            onChange={(e) => setNoteDraft(e.target.value)}
            autoFocus
          />
          <label className="edit-label" style={{ marginTop: '0.5rem' }}>
            Custom summary override (saved to your section):
          </label>
          <textarea
            className="modal-input"
            rows={2}
            placeholder="Customize the short summary for your saved list…"
            value={summaryDraft}
            onChange={(e) => setSummaryDraft(e.target.value)}
          />
          <div className="edit-actions">
            <button type="button" className="btn" onClick={() => setEditingNote(false)}>
              Cancel
            </button>
            <button type="button" className="btn btn-primary" onClick={handleSaveEdits} disabled={savingItem}>
              {savingItem ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </div>
      )}

      {expanded && (
        <div className="summary-box">
          {loadingSummary && 'Generating 50-word summary…'}
          {summaryError && <span style={{ color: '#e08080' }}>{summaryError}</span>}
          {summary && (
            <>
              <div dangerouslySetInnerHTML={{ __html: summary }} />

              {/* Subtle Idea Network teaser line below the 50w summary */}
              <div
                style={{
                  marginTop: '0.75rem',
                  paddingTop: '0.6rem',
                  borderTop: '1px dashed var(--border)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  gap: '0.5rem',
                  fontSize: '0.78rem',
                  color: 'var(--text-muted)',
                }}
              >
                <span>
                  🕸️ <b>Find this idea interesting?</b> Want to see where you can use this &amp; how it connects to nearby drops?
                </span>
                <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    className="btn"
                    style={{
                      padding: '0.28rem 0.65rem',
                      fontSize: '0.74rem',
                      borderColor: 'var(--accent)',
                      color: 'var(--accent)',
                    }}
                    onClick={() => setIdeateOpen(!ideateOpen)}
                  >
                    {ideateOpen ? '▾ Hide Idea Network' : '✨ Connect & Brainstorm →'}
                  </button>
                  {onOpenInChat && (
                    <button
                      type="button"
                      className="btn"
                      style={{
                        padding: '0.28rem 0.65rem',
                        fontSize: '0.74rem',
                        borderColor: 'var(--idea)',
                        color: 'var(--idea)',
                      }}
                      onClick={() =>
                        onOpenInChat({
                          item,
                          summary: summary || item.summary || '',
                          blueprint: ideateResult?.blueprint_html || '',
                          connectedNodes: ideateResult?.connected_nodes || [],
                          profileInputs: {
                            educationLevel,
                            builderGoal,
                            userBackground,
                            creativityMode,
                          },
                        })
                      }
                    >
                      💬 Continue in AI Chat →
                    </button>
                  )}
                </div>
              </div>

              {ideateOpen && (
                <div
                  style={{
                    marginTop: '0.65rem',
                    padding: '0.85rem',
                    background: 'var(--panel)',
                    border: '1px solid var(--border)',
                    borderRadius: '6px',
                  }}
                >
                  <form onSubmit={handleGenerateIdeaNetwork}>
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
                        gap: '0.55rem',
                        marginBottom: '0.55rem',
                      }}
                    >
                      <div>
                        <label className="edit-label">Your Education / Level:</label>
                        <select
                          className="modal-input"
                          value={educationLevel}
                          onChange={(e) => setEducationLevel(e.target.value)}
                        >
                          {EDUCATION_OPTIONS.map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="edit-label">What You Want to Build / Goal:</label>
                        <select
                          className="modal-input"
                          value={builderGoal}
                          onChange={(e) => setBuilderGoal(e.target.value)}
                        >
                          {GOAL_OPTIONS.map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="edit-label">Creativity Mode:</label>
                        <select
                          className="modal-input"
                          value={creativityMode}
                          onChange={(e) => setCreativityMode(e.target.value)}
                        >
                          {CREATIVITY_MODES.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
                      <div style={{ flex: 1, minWidth: '200px' }}>
                        <label className="edit-label">
                          About You (known languages, college major, or domains you like):
                        </label>
                        <input
                          type="text"
                          className="modal-input"
                          placeholder="e.g., 2nd year B.Tech, know Python & basic React, interested in cybersecurity / gaming…"
                          value={userBackground}
                          onChange={(e) => setUserBackground(e.target.value)}
                        />
                      </div>
                      <button
                        type="submit"
                        className="btn btn-primary"
                        disabled={loadingIdeate}
                        style={{ whiteSpace: 'nowrap' }}
                      >
                        {loadingIdeate ? 'Connecting drops…' : '⚡ Generate Connected Ideas'}
                      </button>
                    </div>
                  </form>

                  {ideateError && (
                    <div style={{ color: '#e08080', fontSize: '0.78rem', marginTop: '0.5rem' }}>
                      {ideateError}
                    </div>
                  )}

                  {ideateResult && (
                    <div style={{ marginTop: '0.85rem', paddingTop: '0.75rem', borderTop: '1px solid var(--border)' }}>
                      {ideateResult.connected_nodes?.length > 0 && (
                        <div style={{ marginBottom: '0.75rem' }}>
                          <div className="edit-label" style={{ marginBottom: '0.4rem' }}>
                            🕸️ CONNECTED DROPS FROM NEARBY DAYS IN SIGNAL&apos;S DATABASE:
                          </div>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.45rem' }}>
                            {ideateResult.connected_nodes.map((node) => (
                              <a
                                key={node.url}
                                href={node.url}
                                target="_blank"
                                rel="noreferrer"
                                style={{
                                  display: 'block',
                                  padding: '0.45rem 0.6rem',
                                  background: 'var(--bg-subtle)',
                                  border: '1px solid var(--border)',
                                  borderLeft: node.connection_type === 'Direct Synergy' ? '3px solid var(--accent)' : '3px solid var(--idea)',
                                  borderRadius: '4px',
                                  textDecoration: 'none',
                                  fontSize: '0.76rem',
                                }}
                              >
                                <div style={{ fontFamily: 'var(--mono)', fontSize: '0.64rem', color: 'var(--text-muted)' }}>
                                  {node.connection_type} · {node.source}
                                </div>
                                <div style={{ fontWeight: 600, color: 'var(--text)', margin: '2px 0' }}>
                                  {node.title}
                                </div>
                                <div style={{ fontSize: '0.68rem', color: 'var(--accent)' }}>
                                  ↳ {node.connection_reason}
                                </div>
                              </a>
                            ))}
                          </div>
                        </div>
                      )}

                      <div
                        style={{ fontSize: '0.84rem', lineHeight: 1.6 }}
                        dangerouslySetInnerHTML={{ __html: ideateResult.blueprint_html }}
                      />
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
