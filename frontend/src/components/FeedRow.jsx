import { useState } from 'react'
import { getSummary } from '../api'

export default function FeedRow({ item }) {
  const [expanded, setExpanded] = useState(false)
  const [summary, setSummary] = useState(null)
  const [loadingSummary, setLoadingSummary] = useState(false)
  const [summaryError, setSummaryError] = useState(null)

  const pubDate = item.published_at
    ? new Date(item.published_at).toLocaleDateString(undefined, {
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
        const res = await getSummary(item)
        setSummary(res.summary)
      } catch (err) {
        setSummaryError(err.message || 'Failed to load summary')
      } finally {
        setLoadingSummary(false)
      }
    }
  }

  return (
    <div className={`row ${item.is_builder_idea ? 'is-idea' : ''}`}>
      <div className="row-top">
        <div className="row-badges">
          <span className="chip chip-tier">T{item.tier}</span>
          <span className="chip chip-source">{item.source}</span>
          <span className="chip chip-cat">{item.category}</span>
          {item.is_builder_idea && <span className="chip chip-idea">builder idea</span>}
        </div>
        <div className="row-date">{pubDate}</div>
      </div>

      <a className="row-title" href={item.url} target="_blank" rel="noreferrer">
        {item.title}
      </a>
      <div className="row-summary">{item.summary || 'No summary available.'}</div>

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
        <span className="row-url">{item.url}</span>
      </div>

      <button className="summary-toggle" onClick={handleExpand}>
        {expanded ? '▾' : '▸'} {expanded ? 'Hide AI summary' : 'View AI summary'}
      </button>

      {expanded && (
        <div className="summary-box">
          {loadingSummary && 'Generating summary…'}
          {summaryError && <span style={{ color: '#e08080' }}>{summaryError}</span>}
          {summary && <div dangerouslySetInnerHTML={{ __html: summary }} />}
        </div>
      )}
    </div>
  )
}
