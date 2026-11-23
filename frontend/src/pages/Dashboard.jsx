import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { getDashboardSummary, getEndpoints, getIncidentSummary, getRecentActivity } from '../api'
import { checkedTime, count, endpointHealth, formatUptime, latency } from '../monitoringDisplay'
import { EmptyState, EndpointHealth, ProbeTable, ResponseTrace } from '../MonitoringUI'
import { useMonitoringRefresh } from '../useMonitoringRefresh'
import { IncidentOverview } from '../IncidentUI'
import { isIncidentRefresh } from '../monitoringSocket'

const healthGroups = [
  ['up', 'Up'], ['down', 'Down'], ['error', 'Monitoring errors'], ['redirect', 'Redirects'],
  ['neutral', 'Awaiting checks'], ['inactive', 'Inactive'],
]

function Dashboard() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [incidents, setIncidents] = useState(null)
  const [incidentError, setIncidentError] = useState('')

  const load = useCallback(async (isActive) => {
    try {
      const token = localStorage.getItem('access_token')
      const [summary, activity, endpoints] = await Promise.all([
        getDashboardSummary(token), getRecentActivity(token), getEndpoints(token),
      ])
      if (!isActive()) return
      setData({ summary, activity, endpoints, refreshedAt: new Date() })
      setError('')
    } catch (err) {
      if (isActive()) setError(err.message)
    }
  }, [])
  useMonitoringRefresh(load, undefined, 5000)
  const loadIncidents = useCallback(async (isActive) => {
    try {
      const result = await getIncidentSummary(localStorage.getItem('access_token'))
      if (isActive()) { setIncidents(result); setIncidentError('') }
    } catch (err) {
      if (isActive()) setIncidentError(err.message)
    }
  }, [])
  useMonitoringRefresh(loadIncidents, isIncidentRefresh)

  const summary = data?.summary
  const groups = healthGroups.map(([tone, label]) => ({
    tone, label, total: data?.endpoints.filter((endpoint) => endpointHealth(endpoint) === tone).length ?? 0,
  }))

  return (
    <main className="workspace" id="main-content" tabIndex={-1}>
      <header className="page-heading">
        <div><h1>Overview</h1><p>Availability and performance across your monitored APIs.</p></div>
        {data && <p className="refresh-time mono"><span className="refresh-dot" aria-hidden="true" />Refreshed {data.refreshedAt.toLocaleTimeString()}</p>}
      </header>
      {error && <p className="notice notice-error" role="alert">{error}{data && ' Showing the last available results.'}</p>}
      {!data && !error && <p className="notice" role="status">Loading monitoring overview…</p>}
      {data && <>
        <section className="overview-grid" aria-label="Monitoring summary">
          <div className="uptime-panel">
            <div className="metric-label">Overall uptime</div>
            <div className={`hero-metric ${summary.uptime_percentage == null ? 'no-samples' : ''}`}>{formatUptime(summary.uptime_percentage)}</div>
            <p>Available monitoring history</p>
            <div className="uptime-track" aria-hidden="true">
              {summary.total_checks > 0 && <>
                <span style={{ flexGrow: summary.successful_checks }} />
                {summary.failed_checks > 0 && <span className="failed" style={{ flexGrow: summary.failed_checks }} />}
              </>}
            </div>
            <div className="uptime-counts">
              <span><strong>{count(summary.successful_checks)}</strong> successful</span>
              <span className={summary.failed_checks ? 'dark-error' : undefined}><strong>{count(summary.failed_checks)}</strong> unsuccessful</span>
              <span><strong>{count(summary.total_checks)}</strong> measured</span>
            </div>
          </div>
          <div className="overview-side">
            <div className="metric-line"><span className="metric-label">Average response</span>
              <strong>{(summary.latency_samples ?? summary.total_checks) ? latency(summary.average_response_time) : '—'}</strong>
              <span>Across measured availability checks</span>
            </div>
            <div className="metric-line"><span className="metric-label">Scheduled endpoints</span>
              <strong>{count(summary.active_endpoints)} <small>/ {count(summary.total_endpoints)}</small></strong>
              <Link to="/endpoints">Manage endpoints <span aria-hidden="true">↗</span></Link>
            </div>
          </div>
        </section>

        <IncidentOverview summary={incidents} error={incidentError} />
        <div className="overview-detail">
          <section className="surface">
            <header className="section-head"><div><h2>Endpoint health</h2><p>Latest result per endpoint</p></div></header>
            {data.endpoints.length ? <>
              <div className="health-track" aria-hidden="true">{groups.filter(({ total }) => total).map(({ tone, total }) =>
                <span key={tone} className={`tone-${tone}`} style={{ flexGrow: total }} />)}
              </div>
              <ul className="health-legend">{groups.filter(({ total }) => total).map(({ tone, label, total }) =>
                <li key={tone} className={`tone-${tone}`}><span className="status-mark" aria-hidden="true" />{label}<strong>{count(total)}</strong></li>)}</ul>
              <ul className="health-list">{data.endpoints.slice(0, 5).map((endpoint) =>
                <li key={endpoint.id}><Link to={`/endpoints?id=${endpoint.id}`} title={endpoint.name}>{endpoint.name}</Link><EndpointHealth endpoint={endpoint} /></li>)}</ul>
              {data.endpoints.length > 5 && <Link className="surface-link" to="/endpoints">View all endpoints ↗</Link>}
            </> : <EmptyState title="No endpoints yet"><Link to="/endpoints">Add an endpoint</Link></EmptyState>}
          </section>

          <section className="surface">
            <header className="section-head"><div><h2>Recent activity</h2><p>Latest checks across your endpoints</p></div>
              {data.activity.length > 0 && <span key={data.activity[0].id} className="activity-stamp mono" title={checkedTime(data.activity[0].checked_at)}>Latest check · {new Date(data.activity[0].checked_at).toLocaleTimeString()}</span>}
            </header>
            {data.activity.length ? <>
              <ResponseTrace records={data.activity} />
              <ProbeTable records={data.activity} showEndpoint />
            </> : <EmptyState title="No checks recorded">Results will appear here after the first check.</EmptyState>}
          </section>
        </div>
      </>}
    </main>
  )
}

export default Dashboard
