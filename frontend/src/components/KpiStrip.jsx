export default function KpiStrip({ items }) {
  const total = items.length
  const ideaCount = items.filter((i) => i.is_builder_idea).length
  const researchCount = items.filter((i) => i.category === 'research').length
  const launchCount = items.filter((i) => i.category === 'launch').length
  const avgEngagement = total
    ? (items.reduce((sum, i) => sum + (i.engagement_raw || 0), 0) / total).toFixed(1)
    : 0

  const kpis = [
    { label: 'Total items', value: total, cls: '' },
    { label: 'Builder ideas', value: ideaCount, cls: 'idea' },
    { label: 'Research papers', value: researchCount, cls: '' },
    { label: 'Launches', value: launchCount, cls: '' },
    { label: 'Avg engagement', value: avgEngagement, cls: 'accent' },
  ]

  return (
    <div className="kpi-strip">
      {kpis.map((k) => (
        <div className="kpi" key={k.label}>
          <div className="label">{k.label}</div>
          <div className={`value ${k.cls}`}>{k.value}</div>
        </div>
      ))}
    </div>
  )
}
