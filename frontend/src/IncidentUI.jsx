import { Link } from 'react-router-dom'
import { checkedTime, count } from './monitoringDisplay'
import { incidentStatuses } from './incidentDisplay'
import { EmptyState } from './MonitoringUI'

export function IncidentStatus({ incident }) {
  return <span className={`incident-status ${incident.status !== 'resolved' ? 'incident-active' : ''}`}>
    <span className="status-mark" aria-hidden="true" />{incidentStatuses[incident.status]}
  </span>
}

export function IncidentOverview({ summary, error }) {
  return <section className="surface incident-overview" aria-labelledby="overview-incidents">
    <header className="section-head">
      <div><h2 id="overview-incidents">Incidents</h2><p>Availability alerts and recent recoveries</p></div>
      <Link className="button small" to="/incidents">View incidents <span aria-hidden="true">↗</span></Link>
    </header>
    {error && <p className="notice notice-error" role="alert">{error}</p>}
    {!summary && !error && <p className="notice" role="status">Loading incidents…</p>}
    {summary && <>
      <dl className="incident-overview-stats">
        <div><dt>Active incidents</dt><dd className={summary.active_count ? 'error-text' : undefined}>{count(summary.active_count)}</dd></div>
        <div><dt>Affected endpoints</dt><dd>{count(summary.affected_endpoints)}</dd></div>
      </dl>
      <div className="incident-overview-lists">
        <IncidentLinks title="Active" incidents={summary.active} />
        <IncidentLinks title="Resolved in the last 7 days" incidents={summary.recently_resolved} resolved />
      </div>
    </>}
  </section>
}

function IncidentLinks({ title, incidents, resolved }) {
  return <div>
    <h3>{title}</h3>
    {incidents.length ? <ul>{incidents.map((incident) => <li key={incident.id}>
      <Link to={`/incidents?incident=${incident.id}`}>{incident.endpoint_name}</Link>
      {resolved ? <span className="mono">{checkedTime(incident.resolved_at)}</span> : <IncidentStatus incident={incident} />}
    </li>)}</ul> : <EmptyState title={resolved ? 'No recent resolutions' : 'No active incidents'} />}
  </div>
}
