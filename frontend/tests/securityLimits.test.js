import assert from 'node:assert/strict'
import { test } from 'node:test'
import { getMonitoringHistory, loginUser } from '../src/api.js'

test('displays server retry guidance for account and protected requests', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => ({
    status: 429,
    headers: new Headers({ 'Retry-After': '18' }),
  }))
  await assert.rejects(loginUser('fixture', 'fixture-password'), /Try again in 18 seconds/)
  await assert.rejects(getMonitoringHistory('fixture-session', 2), /Try again in 18 seconds/)
})

test('history requests pass a bounded page size and an endpoint-specific cursor', async (context) => {
  const fetch = context.mock.method(globalThis, 'fetch', async () => ({ ok: true, json: async () => [] }))
  await getMonitoringHistory('fixture-session', 2, { limit: 16, before: 42 })
  const url = new URL(fetch.mock.calls[0].arguments[0])
  assert.equal(url.pathname, '/monitor/2/history')
  assert.deepEqual(Object.fromEntries(url.searchParams), { limit: '16', before_id: '42' })
})
