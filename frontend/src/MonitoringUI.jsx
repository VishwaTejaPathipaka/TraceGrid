import { Link } from 'react-router-dom'
import { checkedTime, endpointConfigurationError, endpointHealth, latency, probeStatusLabel, probeTone } from './monitoringDisplay'

export function ProbeStatus({ probe }) {
  const label = probe ? probeStatusLabel(probe) : 'Not checked'
  const [state, detail] = label.split(' · ')
  const tone = probeTone(probe)
  return (
    <span className="probe-result">
      <span className={`probe-state tone-${tone}`}><span className="status-mark" aria-hidden="true" />{state}</span>
      {detail && <span className="probe-reason">{detail}</span>}
    </span>
  )
}

export function EndpointHealth({ endpoint }) {
  const health = endpointHealth(endpoint)
  if (health === 'inactive' || endpointConfigurationError(endpoint)) {
    return <span className={`probe-state tone-${health}`}><span className="status-mark" aria-hidden="true" />
      {health === 'inactive' ? 'Inactive' : 'Configuration error'}
    </span>
  }
  return <ProbeStatus probe={endpoint.latest_check} />
}

export function EmptyState({ title, children }) {
  return <div className="empty-state"><strong>{title}</strong>{children && <div>{children}</div>}</div>
}

export function ProbeTable({ records, showEndpoint = false }) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={showEndpoint ? 'Recent checks' : 'Probe history'}>
      <table className="probe-table">
        <thead><tr>
          {showEndpoint && <th scope="col">Endpoint</th>}
          <th scope="col">Result</th><th scope="col">HTTP</th><th scope="col">Response</th>
          {!showEndpoint && <th scope="col">Source</th>}<th scope="col">Checked at</th>
        </tr></thead>
        <tbody>{records.map((record) => (
          <tr key={record.id}>
            {showEndpoint && <th scope="row"><Link to={`/endpoints?id=${record.endpoint_id}`}>{record.endpoint_name}</Link></th>}
            <td><ProbeStatus probe={record} /></td>
            <td className="mono">{record.status_code ?? '—'}</td>
            <td className="mono">{latency(record.response_time)}</td>
            {!showEndpoint && <td>{record.scheduled_for ? 'Scheduled' : 'Unspecified'}</td>}
            <td className="mono timestamp">{checkedTime(record.checked_at)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  )
}

export function ResponseTrace({ records }) {
  const samples = records.slice(0, 5).sort((a, b) => new Date(a.checked_at) - new Date(b.checked_at) || a.id - b.id)
  const isMeasured = (record) => record.status !== 'ERROR' && Number.isFinite(record.response_time) && record.response_time >= 0
  const measured = samples.filter(isMeasured)
  if (!measured.length) return <EmptyState title="No measured response times in recent checks" />
  const maximum = Math.max(...measured.map((item) => item.response_time))
  return (
    <figure className="response-trace">
      <figcaption><strong>Recorded response times</strong><span>{measured.length} of {samples.length} measured · oldest to newest</span></figcaption>
      <div className="trace-plot">
        <div className="trace-scale mono" aria-hidden="true">{maximum > 0 && <span>{latency(maximum)}</span>}<span>0 ms</span></div>
        <ol className="trace-bars" aria-label="Response times by check, oldest to newest">
          {samples.map((record) => {
            const available = isMeasured(record)
            const label = `${checkedTime(record.checked_at)} · ${available ? latency(record.response_time) : 'No measured response time'} · ${probeStatusLabel(record)}`
            return <li key={record.id} className={`trace-sample tone-${probeTone(record)}`} title={label}>
              <span className="sr-only">{label}</span>
              {available && <span className={`trace-bar ${record.response_time === 0 ? 'trace-zero' : ''}`} aria-hidden="true"
                style={{ '--height': maximum ? `${record.response_time / maximum * 100}%` : '0%' }} />}
            </li>
          })}
        </ol>
      </div>
    </figure>
  )
}
