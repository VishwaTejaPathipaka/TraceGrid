import assert from 'node:assert/strict'
import { test } from 'node:test'
import { getDashboardSummary, getEndpoints, getRecentActivity } from '../src/api.js'
import { connectMonitoring, isEndpointRefresh, isIncidentRefresh, monitoringSocketUrl, tokenExpiresAt } from '../src/monitoringSocket.js'

function setup(refresh = () => {}) {
  const sockets = []
  const status = []
  const timers = new Map()
  let refreshes = 0
  let unauthorized = 0
  let timerId = 0

  class Socket {
    constructor(url) {
      this.url = url
      this.sent = []
      sockets.push(this)
    }
    send(payload) { this.sent.push(JSON.parse(payload)) }
    message(payload) { this.onmessage({ data: JSON.stringify(payload) }) }
    close() { this.closed = true; this.onclose({ code: 1000 }) }
  }

  const stop = connectMonitoring({
    url: 'wss://api.example.com/ws/monitoring', token: 'test-session',
    onRefresh: () => { refreshes += 1; refresh() },
    onUnauthorized: () => { unauthorized += 1 },
    onStatus: (healthy) => status.push(healthy),
  }, {
    WebSocketImpl: Socket,
    schedule: (callback, delay) => {
      timers.set(++timerId, { callback, delay })
      return timerId
    },
    cancel: (id) => timers.delete(id),
  })
  return {
    sockets, timers, stop, status,
    refreshes: () => refreshes,
    unauthorized: () => unauthorized,
    retry(delay) {
      const [id, timer] = timers.entries().next().value
      assert.equal(timer.delay, delay)
      timers.delete(id)
      timer.callback()
    },
  }
}

test('authenticated heartbeats renew liveness without triggering data reads and a dead socket reconnects', () => {
  const app = setup()
  const [socket] = app.sockets
  socket.message({ type: 'monitoring.heartbeat' })
  assert.equal(app.timers.size, 0)
  socket.message({ type: 'monitoring.ready' })
  const firstWatchdog = [...app.timers.keys()][0]
  socket.message({ type: 'monitoring.heartbeat' })
  assert.equal(app.refreshes(), 1)
  assert.equal(app.timers.has(firstWatchdog), false)
  app.retry(70_000)
  assert.deepEqual(app.status, [true, false])
  assert.equal(socket.closed, true)
  app.retry(1000)
  assert.equal(app.sockets.length, 2)
  app.stop()
})

test('ordinary monitoring traffic does not invalidate incident data or endpoint filters', () => {
  const ordinary = { type: 'monitoring.updated' }
  assert.equal(isIncidentRefresh(ordinary), false)
  assert.equal(isEndpointRefresh(ordinary), false)
  assert.equal(isIncidentRefresh({ type: 'incident.updated' }), true)
  assert.equal(isEndpointRefresh({ type: 'endpoint.updated' }), true)
  assert.equal(isIncidentRefresh({ type: 'monitoring.resync' }), true)
  assert.equal(isEndpointRefresh({ type: 'monitoring.resync' }), true)
})

test('authenticates after opening and refreshes only for authenticated monitoring events', () => {
  const app = setup()
  const [socket] = app.sockets
  socket.onopen()
  assert.equal(socket.url, 'wss://api.example.com/ws/monitoring')
  assert.deepEqual(socket.sent, [{ type: 'authenticate', token: 'test-session' }])
  socket.message({ type: 'monitoring.updated', endpoint_id: 5 })
  assert.equal(app.refreshes(), 0)
  socket.message({ type: 'monitoring.ready' })
  socket.message({ type: 'monitoring.updated', endpoint_id: 5 })
  socket.message({ type: 'monitoring.resync' })
  socket.message({ type: 'monitoring.updated', endpoint_id: '5' })
  assert.equal(app.refreshes(), 3)
  app.stop()
  assert.equal(socket.closed, true)
  assert.equal(app.timers.size, 0)
})

test('backs off on failures, reauthenticates, and refreshes on reconnect', () => {
  const app = setup()
  app.sockets[0].onclose({ code: 1006 })
  app.retry(1000)
  app.sockets[1].onclose({ code: 1006 })
  app.retry(2000)
  const current = app.sockets[2]
  current.onopen()
  assert.deepEqual(current.sent, [{ type: 'authenticate', token: 'test-session' }])
  current.message({ type: 'monitoring.ready' })
  assert.equal(app.refreshes(), 1)
  current.onclose({ code: 1006 })
  app.retry(1000)
  app.stop()
})

test('only authenticated and well-formed lifecycle events refresh incident views', () => {
  const app = setup()
  const [socket] = app.sockets
  socket.message({ type: 'incident.updated', incident_id: 12, action: 'created' })
  assert.equal(app.refreshes(), 0)
  socket.message({ type: 'monitoring.ready' })
  for (const action of ['created', 'acknowledged', 'resolved']) {
    socket.message({ type: 'incident.updated', incident_id: 12, action })
  }
  socket.message({ type: 'incident.updated', incident_id: 12, action: 'unknown' })
  socket.message({ type: 'incident.updated', incident_id: '12', action: 'created' })
  assert.equal(app.refreshes(), 4)
  app.stop()
})

test('an expired or revoked session ends the connection without retrying', () => {
  const app = setup()
  app.sockets[0].onclose({ code: 4401 })
  assert.equal(app.unauthorized(), 1)
  assert.equal(app.timers.size, 0)
})

test('logout cancels an already scheduled reconnect', () => {
  const app = setup()
  app.sockets[0].onclose({ code: 1006 })
  assert.equal(app.timers.size, 1)
  app.stop()
  assert.equal(app.timers.size, 0)
  assert.equal(app.unauthorized(), 0)
})

test('derives the secure socket URL and reads the JWT expiry for the session timer', () => {
  assert.equal(monitoringSocketUrl('https://api.example.com/'), 'wss://api.example.com/ws/monitoring')
  assert.equal(monitoringSocketUrl('/api', 'https://tracegrid.example'), 'wss://tracegrid.example/api/ws/monitoring')
  assert.equal(tokenExpiresAt(`test.${btoa('{"exp":1234}')}.signature`), 1_234_000)
  assert.equal(tokenExpiresAt('invalid'), null)
})

test('refresh callbacks retrieve the committed dashboard and endpoint data with bearer auth', async (context) => {
  let totalChecks = 0
  const requests = context.mock.method(globalThis, 'fetch', async (url, { headers }) => {
    assert.equal(headers.Authorization, 'Bearer test-session')
    if (url.endsWith('/summary')) return Response.json({ total_checks: totalChecks })
    if (url.endsWith('/recent')) return Response.json(totalChecks ? [{ endpoint_id: 5 }] : [])
    return Response.json([{ id: 5, latest_check: totalChecks ? { status: 'UP' } : null }])
  })
  let refresh
  const app = setup(() => {
    refresh = Promise.all([
      getDashboardSummary('test-session'), getRecentActivity('test-session'), getEndpoints('test-session'),
    ])
  })
  const [socket] = app.sockets
  socket.onopen()
  socket.message({ type: 'monitoring.ready' })
  assert.deepEqual(await refresh, [{ total_checks: 0 }, [], [{ id: 5, latest_check: null }]])

  totalChecks = 1
  socket.message({ type: 'monitoring.updated', endpoint_id: 5 })
  assert.deepEqual(await refresh, [
    { total_checks: 1 }, [{ endpoint_id: 5 }], [{ id: 5, latest_check: { status: 'UP' } }],
  ])
  assert.equal(requests.mock.callCount(), 6)
  app.stop()
})
