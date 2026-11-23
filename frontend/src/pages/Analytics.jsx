import { memo, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getEndpoints } from '../api'
import { EndpointAnalysis, EndpointComparison, IncidentAnalytics, RangeControl } from '../AnalyticsCharts'
import { analyticsRange } from '../analyticsDisplay'
import { checkedTime } from '../monitoringDisplay'
import { useAnalyticsReport } from '../useAnalyticsReport'

function ReportNotice({ data, error, retry }) {
  if (error) return <div className="notice notice-error" role="alert">
    {error}{data && ' Showing the last successful report for this selection.'}{' '}
    <button className="button small" onClick={retry}>Try again</button>
  </div>
  if (!data) return <p className="notice" role="status">Loading analytics…</p>
  return null
}

function WindowLabel({ window }) {
  return <p className="analytics-window mono">{checkedTime(window.start)} – {checkedTime(window.end)} · Local time · Available records only</p>
}

export const EndpointAnalyticsPanel = memo(function EndpointAnalyticsPanel({ endpointId, range, onRange }) {
  const { data, error, refresh } = useAnalyticsReport({ endpointId, range, compare: false })
  return <div className="endpoint-analytics">
    <div className="analytics-filter-row"><RangeControl range={range} onChange={onRange} /></div>
    <ReportNotice data={data} error={error} retry={refresh} />
    {data && <>
      <WindowLabel window={data.window} />
      <EndpointAnalysis key={`${endpointId}:${range}`} endpoint={data.endpoint} window={data.window} range={range} />
      <IncidentAnalytics report={data.incidents} />
    </>}
  </div>
})

export default function Analytics() {
  const [params, setParams] = useSearchParams()
  const range = analyticsRange(params.get('range'))
  const requested = Number(params.get('endpoint'))
  const endpointId = Number.isSafeInteger(requested) && requested > 0 ? requested : null
  const [endpoints, setEndpoints] = useState([])
  const [endpointError, setEndpointError] = useState('')
  const [metric, setMetric] = useState('uptime')
  const [descending, setDescending] = useState(true)
  const [offset, setOffset] = useState(0)
  const { data, error, refresh } = useAnalyticsReport({ endpointId, range, compare: true, metric, descending, offset })

  useEffect(() => {
    let active = true
    getEndpoints(localStorage.getItem('access_token')).then(
      (items) => { if (active) setEndpoints(items) },
      (err) => { if (active) setEndpointError(err.message) },
    )
    return () => { active = false }
  }, [])

  function select(key, value) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next)
    setOffset(0)
  }

  return <main className="workspace" id="main-content" tabIndex={-1}>
    <header className="page-heading"><div><h1>Analytics</h1><p>Explore latency, availability, and incident activity across monitored APIs.</p></div></header>
    <div className="analytics-filter-row surface">
      <RangeControl range={range} onChange={(value) => select('range', value)} />
      <label>Endpoint<select value={endpointId ?? ''} onChange={(event) => select('endpoint', event.target.value)}>
        <option value="">All endpoints</option>
        {endpointId && !endpoints.some((endpoint) => endpoint.id === endpointId) &&
          <option value={endpointId}>{data?.endpoint?.name ?? 'Selected endpoint'}</option>}
        {endpoints.map((endpoint) => <option key={endpoint.id} value={endpoint.id}>{endpoint.name}</option>)}
      </select></label>
    </div>
    {endpointError && <p className="notice notice-error" role="alert">Endpoint selector unavailable. {endpointError}</p>}
    <ReportNotice data={data} error={error} retry={refresh} />
    <div className="analytics-track">
      {data && <><WindowLabel window={data.window} />
      {data.endpoint && <EndpointAnalysis key={`${endpointId}:${range}`} endpoint={data.endpoint} window={data.window} range={range} />}
      {!data.endpoint && data.comparison.total > 0 && <p className="analytics-caption">Select an endpoint to inspect its latency trend and individual checks.</p>}</>}
      <EndpointComparison comparison={data?.comparison} metric={metric} descending={descending} range={range}
        onMetric={(value) => { setMetric(value); setOffset(0) }} onDirection={(value) => { setDescending(value); setOffset(0) }} onPage={setOffset} />
      {data && <IncidentAnalytics report={data.incidents} />}
    </div>
  </main>
}
