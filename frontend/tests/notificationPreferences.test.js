import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { createServer } from 'vite'
import { getNotificationPreferences, saveNotificationPreferences } from '../src/api.js'

test('requests account-scoped preferences and submits only the two opt-in flags', async (context) => {
  const fetch = context.mock.method(globalThis, 'fetch', async () => ({
    ok: true, json: async () => ({ verified_email: 'owner@example.com', incident_opened: false, incident_recovered: true }),
  }))
  const current = await getNotificationPreferences('test-session')
  const preferences = { incident_opened: true, incident_recovered: current.incident_recovered }
  await saveNotificationPreferences('test-session', preferences)
  const [loading, update] = fetch.mock.calls.map(({ arguments: [url, params] }) => [new URL(url).pathname, params])
  assert.equal(loading[0], '/users/notification-preferences')
  assert.equal(loading[1].method, 'GET')
  assert.equal(update[0], loading[0])
  assert.equal(update[1].method, 'PUT')
  assert.deepEqual(JSON.parse(update[1].body), preferences)
})

test('provides accessible opt-ins only after mailbox verification', async () => {
  const server = await createServer({
    envDir: false, configLoader: 'runner', server: { middlewareMode: true, ws: false, watch: null },
  })
  try {
    const { EmailNotificationForm } = await server.ssrLoadModule('/src/pages/Settings.jsx')
    const render = (preferences, pending = false) => renderToStaticMarkup(
      createElement(MemoryRouter, null, createElement(EmailNotificationForm, { preferences, pending })),
    )
    const off = { incident_opened: false, incident_recovered: false }
    const unverified = render({ ...off, verified_email: null })
    assert.match(unverified, /No verified email/)
    assert.match(unverified, /href="\/resend-verification"/)
    assert.match(unverified, /<fieldset disabled/)
    assert.doesNotMatch(unverified, /Save preferences/)
    const verified = render({ ...off, verified_email: 'owner@example.com', incident_opened: true })
    assert.match(verified, /Verified destination/)
    assert.match(verified, /An incident opens/)
    assert.match(verified, /An endpoint recovers/)
    assert.match(verified, /checked/)
    assert.match(verified, /Save preferences/)
    assert.doesNotMatch(verified, /<fieldset disabled/)
    assert.match(render({ ...off, verified_email: 'owner@example.com' }, true), /aria-busy="true"/)
  } finally {
    await server.close()
  }
})
