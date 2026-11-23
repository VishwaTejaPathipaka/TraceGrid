import { probeStatusLabel } from './monitoringDisplay.js'

export const incidentStatuses = { open: 'Open', acknowledged: 'Acknowledged', resolved: 'Resolved' }

export function incidentDuration(incident, now = Date.now()) {
  const end = incident.resolved_at ? Date.parse(incident.resolved_at) : now
  const elapsed = end - Date.parse(incident.started_at)
  if (!Number.isFinite(elapsed)) return '—'
  const minutes = Math.floor(Math.max(0, elapsed) / 60_000)
  if (!minutes) return '< 1 min'
  if (minutes < 60) return `${minutes} min`
  if (minutes < 1440) return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
  return `${Math.floor(minutes / 1440)} d ${Math.floor(minutes % 1440 / 60)} h`
}

export function failureDescription(incident) {
  if (incident.failure_reason === 'redirect') return 'Unexpected redirect'
  const detail = probeStatusLabel({ status: 'DOWN', reason: incident.failure_reason }).split(' · ')[1]
  return detail || 'Unsuccessful availability check'
}

export function incidentTimeline(incident) {
  const entries = [
    ['First failed check', incident.started_at],
    ['Incident detected', incident.detected_at],
    ['Acknowledged', incident.acknowledged_at],
    [incident.resolution === 'recovered' ? 'Endpoint recovered' : 'Manually resolved', incident.resolved_at],
  ]
  return entries.filter(([, at]) => at)
}
