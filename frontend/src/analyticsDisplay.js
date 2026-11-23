import { checkedTime, count, latency, probeStatusLabel } from './monitoringDisplay.js'

export const ranges = { '1h': '1 hour', '6h': '6 hours', '24h': '24 hours', '7d': '7 days' }
export const metrics = {
  uptime: 'Uptime', latency: 'Average response', successful: 'Successful checks',
  unsuccessful: 'Unsuccessful checks', measured: 'Measured checks',
}

export function analyticsRange(value) {
  return Object.hasOwn(ranges, value) ? value : '24h'
}

export function timeLabel(at, span) {
  return new Date(at).toLocaleString(undefined, span >= 24 * 3600000
    ? { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }
    : { hour: 'numeric', minute: '2-digit' })
}

export function sampleDescription(sample) {
  const measurement = sample.status === 'ERROR'
    ? `Probe runtime ${latency(sample.response_time)}` : latency(sample.response_time)
  return [checkedTime(sample.checked_at), probeStatusLabel(sample), sample.status_code != null && `HTTP ${sample.status_code}`,
    sample.response_time != null && measurement].filter(Boolean).join(' · ')
}

export function chartScale(maximum) {
  if (!(maximum > 0)) return 1
  const magnitude = 10 ** Math.floor(Math.log10(maximum / 4))
  const unit = maximum / (4 * magnitude)
  const step = [1, 2, 2.5, 5, 10].find((candidate) => candidate >= unit) ?? 10
  const top = 4 * step * magnitude
  return Number.isFinite(top) ? top : maximum
}

export function latencyPlot(points, window) {
  const start = Date.parse(window.start), span = Date.parse(window.end) - start
  const maximum = chartScale(points.reduce((max, point) => Math.max(max, point.response_time), 0))
  const samples = points.map((sample) => ({
    ...sample, x: (Date.parse(sample.checked_at) - start) / span, y: 1 - sample.response_time / maximum,
  }))
  const segments = new Map()
  for (const point of samples) {
    if (point.segment == null) continue
    const part = segments.get(point.segment) ?? []
    part.push(point)
    segments.set(point.segment, part)
  }
  return { samples, segments: [...segments.values()], maximum, start, span }
}

export function timelineBucket(window, index) {
  const start = Date.parse(window.start) + index * window.bucket_seconds * 1000
  return { start, end: start + window.bucket_seconds * 1000 }
}

export function bucketDescription(bucket) {
  const { successful = 0, unsuccessful = 0, monitoring_errors: errors = 0, gaps = 0 } = bucket ?? {}
  if (!successful && !unsuccessful && !errors) return 'No checks recorded'
  return [
    `${count(successful)} successful`, `${count(unsuccessful)} unsuccessful`,
    `${count(errors)} monitoring ${errors === 1 ? 'error' : 'errors'}`, gaps > 0 && 'Includes a recording gap',
  ].filter(Boolean).join(' · ')
}

export function bucketTone(bucket) {
  const { successful, unsuccessful, monitoring_errors: errors, gaps } = bucket ?? {}
  const first = unsuccessful ? ['down', '×'] : successful ? ['up', '•'] : errors ? ['error', '?'] : ['missing', '–']
  return [...first, (unsuccessful && (successful || errors)) || (successful && errors) || gaps ? true : false]
}

export function comparisonLabel(value, metric) {
  if (value == null) return 'No data'
  if (metric === 'uptime') return `${count(value)}%`
  return metric === 'latency' ? latency(value) : count(value)
}

export function durationLabel(seconds) {
  if (seconds == null) return 'No data'
  const rounded = Math.round(seconds)
  if (rounded < 60) return `${rounded} s`
  if (rounded < 3600) return `${Math.floor(rounded / 60)} min ${rounded % 60} s`
  const hours = Math.floor(rounded / 3600), minutes = Math.floor(rounded % 3600 / 60)
  return `${hours} h ${minutes} min`
}
