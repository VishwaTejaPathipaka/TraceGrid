export const allowedMethods = ['GET', 'HEAD']

const redirectCodes = [300, 301, 302, 303, 307, 308]
const probeReasons = {
  dns_resolution: 'DNS resolution failed',
  dns_timeout: 'DNS lookup timed out',
  dns_resolver: 'DNS resolver unavailable',
  tls_verification: 'TLS certificate verification failed',
  tls_error: 'TLS handshake failed',
  connection: 'Connection failed',
  timeout: 'Probe timed out',
  http_error: 'Unsuccessful HTTP response',
  http_protocol: 'Invalid HTTP response',
  monitor_error: 'Local probe failed',
}

export function formatUptime(percentage) {
  return percentage == null ? 'No data' : `${percentage}%`
}

export function probeStatusLabel(probe) {
  if (probe.status === 'REDIRECT' || redirectCodes.includes(probe.status_code)) {
    return 'Redirect'
  }
  const reason = probeReasons[probe.reason]
  const status = probe.status === 'ERROR' ? 'Monitoring error' : probe.status
  return reason ? `${status} · ${reason}` : status
}

export function endpointConfigurationError(endpoint) {
  if (endpoint.configuration_error) return endpoint.configuration_error
  return allowedMethods.includes(endpoint.method) ? null : 'Edit this endpoint to use GET or HEAD.'
}

export function scheduleStatus(endpoint, now) {
  if (!endpoint.is_active) return { label: 'Inactive', overdue: false }
  const due = Date.parse(endpoint.next_check_at)
  if (!Number.isFinite(due)) return { label: 'Schedule unavailable', overdue: false }
  const remaining = due - now
  if (remaining < -1000) {
    return { label: `Overdue by ${Math.floor(-remaining / 1000)} s`, overdue: true }
  }
  return { label: remaining <= 0 ? 'Due now' : `Due in ${Math.ceil(remaining / 1000)} s`, overdue: false }
}

const numbers = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' })

export const count = (value) => numbers.format(value)
export const latency = (value) => value == null ? '—' : `${count(value)} ms`
export const checkedTime = (value) => value ? dateTime.format(new Date(value)) : '—'

export function probeTone(probe) {
  if (!probe) return 'neutral'
  if (probe.status === 'ERROR') return 'error'
  const label = probeStatusLabel(probe)
  if (label === 'Redirect') return 'redirect'
  return probe.status === 'UP' ? 'up' : probe.status === 'DOWN' ? 'down' : 'neutral'
}

export function endpointHealth(endpoint) {
  if (!endpoint.is_active) return 'inactive'
  if (endpointConfigurationError(endpoint)) return 'error'
  return probeTone(endpoint.latest_check)
}
