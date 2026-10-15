export default function StatusBar({ status, isFetching }) {
  if (!status) return null

  const sourceCounts = status.source_counts || {}
  const lastFetchLabel = status.last_fetch_at
    ? timeAgo(new Date(status.last_fetch_at))
    : 'never'

  const dotClass = isFetching || status.fetching ? 'busy' : isStale(status.last_fetch_at) ? 'stale' : ''

  return (
    <div className="status-bar">
      <div className="seg">
        <span className={`dot ${dotClass}`}></span>
        <b>{lastFetchLabel}</b>
      </div>
      {Object.entries(sourceCounts).map(([source, count]) => (
        <div className="seg" key={source}>
          {source} <b>{count}</b>
        </div>
      ))}
    </div>
  )
}

function isStale(lastFetchAt) {
  if (!lastFetchAt) return true
  const elapsedMs = Date.now() - new Date(lastFetchAt).getTime()
  return elapsedMs > 15 * 60 * 1000
}

function timeAgo(date) {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ago`
}
