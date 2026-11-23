import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getEndpoints, createEndpoint, updateEndpoint, deleteEndpoint, checkEndpoint, getMonitoringHistory } from '../api'
import { allowedMethods, checkedTime, count, endpointConfigurationError, latency, scheduleStatus } from '../monitoringDisplay'
import { EmptyState, EndpointHealth, ProbeStatus, ProbeTable } from '../MonitoringUI'
import { useMonitoringRefresh } from '../useMonitoringRefresh'
import { analyticsRange } from '../analyticsDisplay'
import { EndpointAnalyticsPanel } from './Analytics'

const blankEndpoint = { name: '', url: '', method: 'GET' }
const pageSize = 15

function endpointLink(id, view, range) {
  return `/endpoints?id=${id}${view === 'analytics' ? '&view=analytics' : ''}${range ? `&range=${range}` : ''}`
}

function EndpointEditor({ editor, onChange, onSave, onCancel, saving, error }) {
  const title = useRef(null)
  useEffect(() => title.current?.focus(), [])
  return (
    <section className="surface endpoint-editor" aria-labelledby="editor-title">
      <header className="section-head">
        <div><h2 id="editor-title" ref={title} tabIndex={-1}>{editor.id ? 'Edit endpoint' : 'Add endpoint'}</h2>
          <p>TraceGrid checks active endpoints every 30 seconds.</p></div>
      </header>
      <form className="editor-form" onSubmit={onSave}>
        <label htmlFor="endpoint-name">Endpoint name
          <input id="endpoint-name" required value={editor.name} onChange={(e) => onChange('name', e.target.value)} placeholder="Payments API" />
        </label>
        <label htmlFor="endpoint-method">HTTP method
          <select id="endpoint-method" required value={editor.method} onChange={(e) => onChange('method', e.target.value)}>
            <option value="" disabled>Select a method</option>
            {allowedMethods.map((method) => <option key={method}>{method}</option>)}
          </select>
        </label>
        <label htmlFor="endpoint-url" className="full-width">Endpoint URL
          <input id="endpoint-url" type="url" required value={editor.url} onChange={(e) => onChange('url', e.target.value)} placeholder="https://api.example.com/health" />
        </label>
        {error && <p className="notice notice-error full-width" role="alert">{error}</p>}
        <div className="button-row full-width">
          <button type="submit" className="button primary" disabled={saving}>{saving ? 'Saving…' : editor.id ? 'Save changes' : 'Add endpoint'}</button>
          <button type="button" className="button" onClick={onCancel} disabled={saving}>Cancel</button>
        </div>
      </form>
    </section>
  )
}

function History({ endpointId, records }) {
  const [pages, setPages] = useState(() => [records])
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [endPage, setEndPage] = useState(null)
  const [firstAnchor, setFirstAnchor] = useState(null)
  const rows = page === 0 ? records : pages[page]
  if (!rows.length) return <EmptyState title="No checks recorded">Scheduled and manual checks will appear here.</EmptyState>

  async function nextPage() {
    const anchor = rows[pageSize - 1].id
    const rebase = page === 0 && firstAnchor !== anchor
    if (!rebase && pages[page + 1]) {
      setPage(page + 1)
      return
    }
    setLoading(true)
    setError('')
    try {
      const older = await getMonitoringHistory(localStorage.getItem('access_token'), endpointId, {
        limit: pageSize + 1, before: anchor,
      })
      if (older.length) {
        setPages((previous) => rebase ? [records, older] : [...previous, older])
        if (rebase) {
          setFirstAnchor(anchor)
          setEndPage(null)
        }
        setPage(page + 1)
      } else {
        setEndPage(page)
      }
    } catch (error) {
      setError(error.message)
    } finally {
      setLoading(false)
    }
  }

  return <>
    <ProbeTable records={rows.slice(0, pageSize)} />
    {error && <p className="notice notice-error" role="alert">{error}</p>}
    <div className="pagination">
      <span className="mono">Page {page + 1}</span>
      <div className="button-row">
        <button className="button small" disabled={page === 0 || loading} onClick={() => setPage(page - 1)}>Previous</button>
        <button className="button small" disabled={rows.length <= pageSize || loading || endPage === page}
          onClick={nextPage}>{loading ? 'Loading?' : 'Next'}</button>
      </div>
    </div>
  </>
}

function EndpointInspector({ endpoint, view, report, now, manualError, range, onRange }) {
  const schedule = scheduleStatus(endpoint, now)
  const configurationError = endpointConfigurationError(endpoint)
  const heading = useRef(null)
  useEffect(() => {
    heading.current?.focus()
  }, [])
  const latest = endpoint.latest_check
  return (
    <section className="surface endpoint-inspector" aria-labelledby="inspector-title">
      <header className="section-head">
        <div><h2 id="inspector-title" ref={heading} tabIndex={-1}>{endpoint.name}</h2>
          <p className="inspector-url mono"><span className="method-tag">{endpoint.method}</span>{endpoint.url}</p></div>
        <Link className="button small" to="/endpoints">Close details</Link>
      </header>
      {configurationError && <p className="notice notice-error" role="alert">{configurationError}</p>}
      {manualError && manualError !== configurationError && <p className="notice notice-error" role="alert">Manual check failed · {manualError}</p>}
      <div className="inspector-meta">
        <div><span>Latest probe</span><ProbeStatus probe={latest} />
          {latest && <small className="mono">{checkedTime(latest.checked_at)}</small>}</div>
        <div><span>Next scheduled check</span><strong className={schedule.overdue ? 'error-text mono' : 'mono'}>{schedule.label}</strong>
          {endpoint.is_active && <small>30-second interval</small>}</div>
        <div><span>Last scheduled run</span>
          <strong className="mono">{endpoint.last_schedule_duration_ms == null ? '—' : latency(endpoint.last_schedule_duration_ms)}</strong>
          {endpoint.last_schedule_lateness_ms != null && <small>Start delay {latency(endpoint.last_schedule_lateness_ms)}</small>}
          {endpoint.last_schedule_missed_intervals > 0 && <small className="error-text">{endpoint.last_schedule_missed_intervals} missed intervals</small>}
        </div>
      </div>
      <nav className="detail-nav" aria-label="Endpoint details">
        <Link to={endpointLink(endpoint.id, 'history', range)} aria-current={view === 'history' ? 'page' : undefined}>History</Link>
        <Link to={endpointLink(endpoint.id, 'analytics', range)} aria-current={view === 'analytics' ? 'page' : undefined}>Analytics</Link>
      </nav>
      {view === 'analytics' ? <>
        <Link className="surface-link" to={`/analytics?endpoint=${endpoint.id}&range=${range}`}>Open workspace analytics ?</Link>
        <EndpointAnalyticsPanel endpointId={endpoint.id} range={range} onRange={onRange} />
      </> : <>
        {report?.error && <p className="notice notice-error" role="alert">{report.error}</p>}
        {!report && <p className="notice" role="status">Loading history?</p>}
        {report?.history && <History endpointId={endpoint.id} records={report.history} />}
      </>}
    </section>
  )
}

function Endpoints() {
  const [params, setParams] = useSearchParams()
  const selectedId = Number(params.get('id'))
  const view = params.get('view') === 'analytics' ? 'analytics' : 'history'
  const range = analyticsRange(params.get('range'))
  const changeRange = useCallback((value) => {
    setParams((previous) => {
      const next = new URLSearchParams(previous)
      next.set('range', value)
      return next
    })
  }, [setParams])
  const [endpoints, setEndpoints] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [editor, setEditor] = useState(null)
  const [saving, setSaving] = useState(false)
  const [editorError, setEditorError] = useState('')
  const [actionError, setActionError] = useState('')
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState(null)
  const [manualErrors, setManualErrors] = useState({})
  const [reports, setReports] = useState({})
  const [now, setNow] = useState(Date.now)
  const reportKey = `${selectedId}-${view}`

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  const load = useCallback(async (isActive) => {
    const token = localStorage.getItem('access_token')
    try {
      const items = await getEndpoints(token)
      if (!isActive()) return
      setEndpoints(items)
      setLoadError('')
      if (view !== 'history' || !items.some((item) => item.id === selectedId)) return
      try {
        const history = await getMonitoringHistory(token, selectedId, { limit: pageSize + 1 })
        if (isActive()) setReports((previous) => ({ ...previous, [reportKey]: { history } }))
      } catch (err) {
        if (isActive()) setReports((previous) => ({ ...previous, [reportKey]: { ...previous[reportKey], error: err.message } }))
      }
    } catch (err) {
      if (isActive()) setLoadError(err.message)
    }
  }, [selectedId, view, reportKey])
  useMonitoringRefresh(load, undefined, 5000)

  function changeEditor(endpoint) {
    setEditor(endpoint ? { id: endpoint.id, name: endpoint.name, url: endpoint.url,
      method: allowedMethods.includes(endpoint.method) ? endpoint.method : '' } : blankEndpoint)
    setEditorError('')
    setMessage('')
  }

  async function saveEndpoint(event) {
    event.preventDefault()
    const token = localStorage.getItem('access_token')
    const { id, name, url, method } = editor
    setSaving(true)
    setEditorError('')
    try {
      if (id) await updateEndpoint(token, id, { name, url, method })
      else await createEndpoint(token, { name, url, method })
      if (id) setManualErrors((previous) => ({ ...previous, [id]: null }))
      setEditor(null)
      setMessage(id ? 'Endpoint updated.' : 'Endpoint added.')
      await load(() => localStorage.getItem('access_token') === token)
    } catch (err) {
      setEditorError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function runAction(endpoint, action) {
    if (action === 'delete' && !window.confirm(`Delete “${endpoint.name}” and its monitoring history?`)) return
    const token = localStorage.getItem('access_token')
    setPending({ id: endpoint.id, action })
    setActionError('')
    setMessage('')
    try {
      if (action === 'delete') await deleteEndpoint(token, endpoint.id)
      else await checkEndpoint(token, endpoint.id)
      setManualErrors((previous) => ({ ...previous, [endpoint.id]: null }))
      if (action === 'delete' && editor?.id === endpoint.id) setEditor(null)
      setMessage(action === 'delete' ? 'Endpoint deleted.' : 'Manual check recorded.')
      await load(() => localStorage.getItem('access_token') === token)
    } catch (err) {
      if (action === 'delete') {
        setActionError(err.message)
      } else {
        setManualErrors((previous) => ({ ...previous, [endpoint.id]: err.message }))
      }
    } finally {
      setPending(null)
    }
  }

  const selected = endpoints?.find((endpoint) => endpoint.id === selectedId)
  return (
    <main className="workspace" id="main-content" tabIndex={-1}>
      <header className="page-heading">
        <div><h1>Endpoints</h1><p>Manage targets, inspect probe results, and track the next check.</p></div>
        <button className="button primary" disabled={saving} onClick={() => changeEditor(null)}>Add endpoint <span aria-hidden="true">+</span></button>
      </header>
      {(loadError || actionError) && <p className="notice notice-error" role="alert">{loadError || actionError}</p>}
      {message && <p className="notice" role="status">{message}</p>}
      {editor && <EndpointEditor key={editor.id ?? 'new'} editor={editor} saving={saving} error={editorError}
        onChange={(field, value) => setEditor((previous) => ({ ...previous, [field]: value }))}
        onCancel={() => setEditor(null)} onSave={saveEndpoint} />}
      {!endpoints && !loadError && <p className="notice" role="status">Loading endpoints…</p>}
      {selected && <EndpointInspector key={selected.id} endpoint={selected} now={now} view={view}
        report={reports[reportKey]} manualError={manualErrors[selected.id]} range={range} onRange={changeRange} />}
      {endpoints && <section className="surface endpoint-directory">
        <header className="section-head"><div><h2>Endpoint directory</h2><p>{count(endpoints.length)} registered · Active endpoints checked every 30 seconds</p></div></header>
        {endpoints.length ? (
          <div className="endpoint-list">
            <div className="directory-labels" aria-hidden="true"><span>Endpoint</span><span>Health</span><span>Next check</span><span>Response</span><span>Actions</span></div>
            <ul>{endpoints.map((endpoint) => {
              const schedule = scheduleStatus(endpoint, now)
              const active = endpoint.id === selectedId
              return (
                <li className={`endpoint-entry ${active ? 'is-selected' : ''}`} key={endpoint.id}>
                  <div className="endpoint-row">
                    <div className="endpoint-identity">
                      <Link to={endpointLink(endpoint.id, 'history')} aria-current={active ? 'true' : undefined}>{endpoint.name}<span aria-hidden="true"> ↗</span></Link>
                      <span className="endpoint-address mono"><span className="method-tag">{endpoint.method}</span><span>{endpoint.url}</span></span>
                    </div>
                    <div><span className="mobile-label">Health</span><EndpointHealth endpoint={endpoint} /></div>
                    <div><span className="mobile-label">Next check</span><strong className={`mono ${schedule.overdue ? 'error-text' : ''}`}>{schedule.label}</strong></div>
                    <div><span className="mobile-label">Response</span><span className="mono">{latency(endpoint.latest_check?.response_time)}</span></div>
                    <div className="button-row endpoint-actions">
                      <button className="button small" disabled={!!pending || !allowedMethods.includes(endpoint.method)} onClick={() => runAction(endpoint, 'check')}>
                        {pending?.id === endpoint.id && pending.action === 'check' ? 'Checking…' : 'Check now'}
                      </button>
                      <details className="action-menu">
                        <summary className="button small" aria-label={`Actions for ${endpoint.name}`}>More <span aria-hidden="true">⌄</span></summary>
                        <div className="action-popover">
                          <Link to={endpointLink(endpoint.id, 'history')} onClick={(e) => e.currentTarget.closest('details').open = false}>View history</Link>
                          <Link to={endpointLink(endpoint.id, 'analytics')} onClick={(e) => e.currentTarget.closest('details').open = false}>View analytics</Link>
                          <button disabled={saving} onClick={(e) => { e.currentTarget.closest('details').open = false; changeEditor(endpoint) }}>Edit endpoint</button>
                          <button className="error-text" disabled={!!pending} onClick={(e) => { e.currentTarget.closest('details').open = false; runAction(endpoint, 'delete') }}>Delete endpoint</button>
                        </div>
                      </details>
                    </div>
                  </div>
                  {manualErrors[endpoint.id] && !active && <p className="entry-error error-text" role="alert">{manualErrors[endpoint.id]}</p>}
                </li>
              )
            })}</ul>
          </div>
        ) : <EmptyState title="No endpoints registered"><button className="button" onClick={() => changeEditor(null)}>Add your first endpoint</button></EmptyState>}
      </section>}
      {endpoints && selectedId > 0 && !selected && <EmptyState title="Endpoint unavailable"><Link to="/endpoints">Return to endpoint directory</Link></EmptyState>}
    </main>
  )
}

export default Endpoints
