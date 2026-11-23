import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { changeIncident, getEndpoints, getIncidents } from '../api'
import { checkedTime, count, latency } from '../monitoringDisplay'
import { failureDescription, incidentDuration, incidentStatuses, incidentTimeline } from '../incidentDisplay'
import { IncidentStatus } from '../IncidentUI'
import { EmptyState } from '../MonitoringUI'
import { useMonitoringRefresh } from '../useMonitoringRefresh'
import { isEndpointRefresh, isIncidentRefresh } from '../monitoringSocket'

const emptyFilters = { status: '', endpoint_id: '', from_date: '', to_date: '' }
const pageSize = 20

export function IncidentItem({ incident, now, pending, onAction, expanded }) {
  return <details className="incident-item" open={expanded || undefined}>
    <summary>
      <span className="incident-identity"><strong>{incident.title}</strong><small>{incident.endpoint_name}</small></span>
      <span className="incident-state"><IncidentStatus incident={incident} />
        <span className={`incident-severity ${incident.status !== 'resolved' ? 'incident-active' : ''}`}>{incident.severity}</span>
      </span>
      <span className="incident-start"><small>Started</small><span className="mono">{checkedTime(incident.started_at)}</span></span>
      <span className="incident-start"><small>Duration</small><span className="mono">{incidentDuration(incident, now)}</span></span>
      <span className="incident-chevron" aria-hidden="true">⌄</span>
    </summary>
    <div className="incident-details">
      <div>
        <h3>Trigger and recovery</h3>
        <p>{failureDescription(incident)}{incident.failure_http_status != null && <> · <span className="mono">HTTP {incident.failure_http_status}</span></>}</p>
        {incident.resolution === 'recovered' && <p>Recovered · <span className="mono">HTTP {incident.recovery_http_status ?? '—'} · {latency(incident.recovery_response_ms)}</span></p>}
        {incident.resolution === 'manual' && <p>Resolved manually.</p>}
        {incident.endpoint_id && <Link className="incident-endpoint-link" to={`/endpoints?id=${incident.endpoint_id}`}>Inspect endpoint ↗</Link>}
        {incident.status !== 'resolved' && <div className="button-row incident-actions">
          {incident.status === 'open' && <button className="button small" disabled={pending} onClick={() => onAction(incident.id, 'acknowledge')}>Acknowledge</button>}
          <button className="button small primary" disabled={pending} onClick={() => onAction(incident.id, 'resolve')}>{pending ? 'Updating…' : 'Resolve incident'}</button>
        </div>}
      </div>
      <div>
        <h3>Lifecycle</h3>
        <ol className="incident-timeline">{incidentTimeline(incident).map(([label, at]) =>
          <li key={label}><span>{label}</span><time className="mono" dateTime={at}>{checkedTime(at)}</time></li>)}</ol>
      </div>
    </div>
  </details>
}

export default function Incidents() {
  const [params] = useSearchParams()
  const focused = params.get('incident') || ''
  const [draft, setDraft] = useState(emptyFilters)
  const [filters, setFilters] = useState(emptyFilters)
  const [offset, setOffset] = useState(0)
  const [report, setReport] = useState(null)
  const [endpoints, setEndpoints] = useState([])
  const [error, setError] = useState('')
  const [endpointError, setEndpointError] = useState('')
  const [actionError, setActionError] = useState('')
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState(null)
  const [now, setNow] = useState(Date.now)
  const query = { ...filters, incident_id: focused, limit: pageSize, offset }
  const queryKey = JSON.stringify(query)

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(timer)
  }, [])

  function updateDraft(field, value) {
    setDraft((previous) => ({ ...previous, [field]: value }))
  }

  const load = useCallback(async (isActive) => {
    try {
      const data = await getIncidents(localStorage.getItem('access_token'), JSON.parse(queryKey))
      if (isActive()) { setReport({ ...data, queryKey }); setError('') }
    } catch (err) {
      if (isActive()) setError(err.message)
    }
  }, [queryKey, setReport, setError])

  const loadEndpoints = useCallback(async (isActive) => {
    try {
      const data = await getEndpoints(localStorage.getItem('access_token'))
      if (isActive()) { setEndpoints(data); setEndpointError('') }
    } catch (err) {
      if (isActive()) setEndpointError(err.message)
    }
  }, [setEndpoints, setEndpointError])
  const refresh = useMonitoringRefresh(load, isIncidentRefresh)
  useMonitoringRefresh(loadEndpoints, isEndpointRefresh)

  async function handleAction(id, action) {
    const token = localStorage.getItem('access_token')
    setPending(id)
    setActionError('')
    setMessage('')
    try {
      await changeIncident(token, id, action)
      setMessage(action === 'acknowledge' ? 'Incident acknowledged.' : 'Incident resolved.')
      refresh()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setPending(null)
    }
  }

  const data = report?.queryKey === queryKey ? report : null
  return <main className="workspace" id="main-content" tabIndex={-1}>
    <header className="page-heading"><div><h1>Incidents</h1><p>Track availability alerts from first failure through recovery.</p></div></header>
    <section className="surface">
      <header className="section-head">
        <div><h2>Incident history</h2><p>Alerts open after three unsuccessful availability checks.</p></div>
        {focused && <Link className="button small" to="/incidents">View all incidents</Link>}
      </header>
      {!focused && <form className="incident-filters" onSubmit={(event) => {
        event.preventDefault()
        setError('')
        setOffset(0)
        setFilters(draft)
      }}>
        <label>Status<select value={draft.status} onChange={(e) => updateDraft('status', e.target.value)}>
          <option value="">All statuses</option>
          {Object.entries(incidentStatuses).map(([value, title]) => <option key={value} value={value}>{title}</option>)}
        </select></label>
        <label>Endpoint<select value={draft.endpoint_id} onChange={(e) => updateDraft('endpoint_id', e.target.value)}>
          <option value="">All endpoints</option>
          {endpoints.map((endpoint) => <option key={endpoint.id} value={endpoint.id}>{endpoint.name}</option>)}
        </select></label>
        <label>Started from (UTC)<input type="date" value={draft.from_date} max={draft.to_date || undefined} onChange={(e) => updateDraft('from_date', e.target.value)} /></label>
        <label>Started through (UTC)<input type="date" value={draft.to_date} min={draft.from_date || undefined} onChange={(e) => updateDraft('to_date', e.target.value)} /></label>
        <div className="button-row">
          <button className="button primary">Apply filters</button>
          <button className="button" type="button" onClick={() => { setDraft(emptyFilters); setFilters(emptyFilters); setOffset(0) }}>Clear</button>
        </div>
      </form>}
      {endpointError && !focused && <p className="notice notice-error" role="alert">Endpoint filter unavailable. {endpointError}</p>}
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {actionError && <p className="notice notice-error" role="alert">{actionError}</p>}
      {message && <p className="notice" role="status">{message}</p>}
      {!data && !error && <p className="notice" role="status">Loading incidents…</p>}
      {data && (data.items.length ? data.items.map((incident) =>
        <IncidentItem key={incident.id} incident={incident} now={now} onAction={handleAction}
          pending={pending !== null} expanded={Boolean(focused)} />
      ) : <EmptyState title={focused ? 'Incident unavailable' : 'No incidents match this view'} />)}
      {data && (data.total > pageSize || offset > 0) && <div className="pagination">
        <span className="mono">{data.items.length ? `${offset + 1}–${offset + data.items.length} of ${count(data.total)}` : `${count(data.total)} matching incidents`}</span>
        <div className="button-row">
          <button className="button small" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button>
          <button className="button small" disabled={offset + pageSize >= data.total} onClick={() => setOffset(offset + pageSize)}>Next</button>
        </div>
      </div>}
    </section>
  </main>
}
