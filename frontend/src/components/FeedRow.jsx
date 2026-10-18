import { useEffect, useState } from 'react'
import { getSummary } from '../api'

const DEPT_META = {
  'cybersecurity':   { label: '🔒 Cybersecurity', color: '#e07070' },
  'ai-ml':           { label: '🤖 AI / ML',        color: '#a78bfa' },
  'gaming-tech':     { label: '🎮 Gaming Tech',     color: '#60b8ff' },
  'cloud':           { label: '☁️ Cloud',           color: '#5fbf7a' },
  'web-dev':         { label: '🌐 Web Dev',         color: '#ff8c1a' },
  'innovator':       { label: '🚀 Innovator',       color: '#f9c04a' },
  'random-dev-idea': { label: '🎲 Random',          color: '#8b8a85' },
}

export default function FeedRow({
  item,
  isAuthenticated,
  savedEntry,
  onSaveOrUpdate,
  onRemoveSaved,
}) {
  const [expanded, setExpanded] = useState(false)
  const [summary, setSummary] = useState(null)
  const [loadingSummary, setLoadingSummary] = useState(false)
  const [summaryError, setSummaryError] = useState(null)

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
          {summary && <div dangerouslySetInnerHTML={{ __html: summary }} />}
        </div>
      )}
    </div>
  )
}
