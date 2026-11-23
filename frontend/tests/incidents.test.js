import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { createServer } from 'vite'
import { changeIncident, getIncidentSummary, getIncidents } from '../src/api.js'
import { incidentDuration, incidentTimeline } from '../src/incidentDisplay.js'

const scenario = {
  id: 12, endpoint_id: 4, endpoint_name: 'Payments API', title: 'Payments API availability incident',
  status: 'open', severity: 'critical', failure_reason: 'http_error', failure_http_status: 503,
  started_at: '2026-11-23T09:00:00Z', detected_at: '2026-11-23T09:01:00Z',
}

test('incident duration freezes on resolution and lifecycle distinguishes actual recovery', () => {
  const recovered = { ...scenario, resolution: 'recovered', resolved_at: '2026-11-23T09:17:00Z' }
  assert.equal(incidentDuration(scenario, Date.parse('2026-11-23T09:03:00Z')), '3 min')
  assert.equal(incidentDuration(recovered, Date.parse('2026-11-24')), '17 min')
  assert.deepEqual(incidentTimeline(recovered).map(([label]) => label),
    ['First failed check', 'Incident detected', 'Endpoint recovered'])
})

test('renders incident details and dashboard alerts before and after recovery', async () => {
  const server = await createServer({
    envDir: false, configLoader: 'runner', server: { middlewareMode: true, ws: false, watch: null },
  })
  try {
    const { IncidentItem } = await server.ssrLoadModule('/src/pages/Incidents.jsx')
    const { IncidentOverview } = await server.ssrLoadModule('/src/IncidentUI.jsx')
    const render = (Component, props) => renderToStaticMarkup(createElement(MemoryRouter, null, createElement(Component, props)))
    const open = render(IncidentItem, { incident: scenario, expanded: true, now: Date.parse('2026-11-23T09:03:00Z') })
    assert.match(open, /Payments API availability incident/)
    assert.match(open, /Open/)
    assert.match(open, /HTTP 503/)
    assert.match(open, /3 min/)
    assert.match(open, /Resolve incident/)
    const incident = {
      ...scenario, status: 'resolved', resolution: 'recovered', resolved_at: '2026-11-23T09:17:00Z',
      recovery_http_status: 204, recovery_response_ms: 18.5,
    }
    const recovered = render(IncidentItem, { incident, expanded: true })
    assert.match(recovered, /Endpoint recovered/)
    assert.match(recovered, /HTTP 204/)
    assert.match(recovered, /18.5 ms/)
    assert.doesNotMatch(recovered, /Resolve incident/)
    const dashboard = render(IncidentOverview, {
      summary: { active_count: 1, affected_endpoints: 1, active: [scenario], recently_resolved: [incident] },
    })
    assert.match(dashboard, /Active incidents/)
    assert.match(dashboard, /Affected endpoints/)
    assert.match(dashboard, /Resolved in the last 7 days/)
    assert.match(dashboard, /\/incidents\?incident=12/)
  } finally {
    await server.close()
  }
})

test('incident API encodes date and endpoint filters and uses POST for lifecycle changes', async (t) => {
  const request = t.mock.method(globalThis, 'fetch', async () => ({ ok: true, json: async () => ({}) }))
  await getIncidents('test-session', { status: 'open', from_date: '2026-11-23', endpoint_id: 4, to_date: '' })
  await getIncidentSummary('test-session')
  await changeIncident('test-session', 12, 'acknowledge')
  await changeIncident('test-session', 12, 'resolve')
  const urls = request.mock.calls.map(({ arguments: [url, options] }) => [new URL(url), options.method])
  assert.deepEqual(Object.fromEntries(urls[0][0].searchParams), { status: 'open', from_date: '2026-11-23', endpoint_id: '4' })
  assert.deepEqual(urls.map(([url, method]) => [url.pathname, method]), [
    ['/incidents/', 'GET'], ['/incidents/summary', 'GET'],
    ['/incidents/12/acknowledge', 'POST'], ['/incidents/12/resolve', 'POST'],
  ])
})
