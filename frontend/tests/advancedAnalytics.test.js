import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { createServer } from 'vite'
import { getAnalyticsChecks, getAnalyticsReport } from '../src/api.js'
import { analyticsRange, bucketDescription, bucketTone, comparisonLabel, latencyPlot, sampleDescription, timelineBucket } from '../src/analyticsDisplay.js'

const window = { start: '2026-11-23T08:00:00Z', end: '2026-11-23T09:00:00Z', bucket_seconds: 60, bucket_count: 60 }
const samples = [
  { id: 1, checked_at: '2026-11-23T08:00:30Z', status: 'UP', response_time: 0, status_code: 204, segment: 1 },
  { id: 2, checked_at: '2026-11-23T08:01:00Z', status: 'UP', response_time: 30, status_code: 200, segment: 1 },
  { id: 3, checked_at: '2026-11-23T08:01:15Z', status: 'DOWN', response_time: 350, status_code: 503, reason: 'http_error', segment: null },
  { id: 4, checked_at: '2026-11-23T08:45:00Z', status: 'UP', response_time: 20, status_code: 200, segment: 2 },
]

test('trend positions follow elapsed time, preserve zero and keep discontinuous segments apart', () => {
  const plot = latencyPlot(samples, window)
  assert.equal(plot.samples[1].x, 1 / 60)
  assert.equal(plot.samples[3].x, .75)
  assert.equal(plot.samples[0].y, 1)
  assert.ok(plot.maximum >= 350 && plot.maximum < 700)
  assert.deepEqual(plot.segments.map((part) => part.map((item) => item.id)), [[1, 2], [4]])
  assert.match(sampleDescription(samples[2]), /HTTP 503.*350 ms/)
})

test('availability labels distinguish missing, mixed and monitoring errors without claiming downtime', () => {
  const error = { monitoring_errors: 1, successful: 0, unsuccessful: 0, gaps: 0 }
  assert.equal(bucketDescription(null), 'No checks recorded')
  assert.deepEqual(bucketTone(error), ['error', '?', false])
  assert.deepEqual(bucketTone({ ...error, unsuccessful: 2, gaps: 1 }), ['down', '×', true])
  assert.match(bucketDescription({ ...error, gaps: 1 }), /Includes a recording gap/)
  assert.match(sampleDescription({ ...samples[2], status: 'ERROR', reason: 'dns_timeout', status_code: null }),
    /Monitoring error.*Probe runtime/)
  assert.deepEqual(timelineBucket(window, 1), {
    start: Date.parse('2026-11-23T08:01:00Z'), end: Date.parse('2026-11-23T08:02:00Z'),
  })
  assert.equal(comparisonLabel(0, 'uptime'), '0%')
  assert.equal(comparisonLabel(null, 'uptime'), 'No data')
  assert.equal(analyticsRange('bad'), '24h')
})

test('renders accessible chart controls, no-data states, and the five-sample Overview bar chart', async () => {
  const server = await createServer({
    envDir: false, configLoader: 'runner', server: { middlewareMode: true, ws: false, watch: null },
  })
  try {
    const charts = await server.ssrLoadModule('/src/AnalyticsCharts.jsx')
    const { ResponseTrace } = await server.ssrLoadModule('/src/MonitoringUI.jsx')
    const render = (component, props) => renderToStaticMarkup(createElement(MemoryRouter, null, createElement(component, props)))
    const controls = render(charts.RangeControl, { range: '24h' })
    assert.match(controls, /aria-pressed="true">24 hours/)
    const trend = render(charts.ResponseTrend, {
      points: samples, statistics: { samples: 4, p95: null, maximum: 350 }, window, gap: 75,
    })
    assert.match(trend, /type="range"/)
    assert.equal((trend.match(/<polyline/g) ?? []).length, 1)
    assert.match(render(charts.ResponseTrend, { points: [] }), /No measured response times/)
    const timeline = render(charts.AvailabilityTimeline, {
      window, gap: 75, buckets: [{ index: 0, successful: 0, unsuccessful: 0, monitoring_errors: 1, gaps: 0 }],
    })
    assert.match(timeline, /timeline-error/)
    assert.match(timeline, /timeline-missing/)
    assert.equal((timeline.match(/tabindex="0"/gi) ?? []).length, 1)
    assert.match(render(charts.EndpointComparison, { comparison: { total: 1 }, metric: 'uptime' }), /Only one endpoint/)
    assert.match(render(charts.EndpointComparison, {
      comparison: { total: 2, items: [{ id: 1, name: 'Measured', value: 0, samples: 2 },
        { id: 2, name: 'Missing', value: null, samples: 0 }], offset: 0, limit: 15 },
      metric: 'uptime', range: '1h', descending: true,
    }), /0%.*No data/)
    const records = Array.from({ length: 7 }, (_, index) => ({
      ...samples[0], id: index, checked_at: new Date(Date.parse(window.end) - index * 60_000).toISOString(),
      response_time: index === 1 ? -1 : index,
    }))
    const overview = render(ResponseTrace, { records })
    assert.equal((overview.match(/<li /g) ?? []).length, 5)
    assert.match(overview, /4 of 5 measured/)
    assert.match(overview, /No measured response time/)
    assert.doesNotMatch(overview, /<svg|<polyline/)
  } finally {
    await server.close()
  }
})

test('analytics requests scope endpoint and timeline pagination to one time window', async (context) => {
  const fetch = context.mock.method(globalThis, 'fetch', async () => ({ ok: true, json: async () => ({}) }))
  await getAnalyticsReport('fixture-session', {
    endpointId: 4, range: '6h', compare: false, metric: 'latency', descending: true, offset: 0,
  })
  await getAnalyticsChecks('fixture-session', 4, '6h', window.end, 5, { at: window.start, id: 7 })
  const [report, checks] = fetch.mock.calls.map(({ arguments: [url] }) => new URL(url))
  assert.equal(report.pathname, '/analytics/report')
  assert.deepEqual(Object.fromEntries(report.searchParams), {
    range: '6h', compare: 'false', metric: 'latency', descending: 'true', offset: '0', endpoint_id: '4',
  })
  assert.equal(checks.pathname, '/analytics/endpoints/4/checks')
  assert.deepEqual(Object.fromEntries(checks.searchParams), {
    range: '6h', end: window.end, bucket: '5', after_at: window.start, after_id: '7',
  })
})
