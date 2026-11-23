import assert from 'node:assert/strict'
import { test } from 'node:test'
import { accountLinkToken } from '../src/accountLink.js'
import { accountRequest, registerUser } from '../src/api.js'

const token = 'a'.repeat(43)

test('accepts a single valid link token and rejects missing, malformed, and duplicate tokens', () => {
  assert.equal(accountLinkToken(`#token=${token}`), token)
  for (const fragment of ['', '?token=' + token, '#token=short', `#token=${token}&token=${token}`]) {
    assert.equal(accountLinkToken(fragment), null)
  }
})

test('posts account requests with tokens in the body and forwards generic success messages', async (t) => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => ({
    ok: true, json: async () => ({ message: 'Check your inbox.' }),
  }))
  assert.deepEqual(await registerUser('name', 'name@example.com', 'test-password'), { message: 'Check your inbox.' })
  await accountRequest('forgot-password', { email: 'name@example.com' })
  await accountRequest('reset-password', { token, password: 'new-password' })
  await accountRequest('verify-email', { token, password: 'test-password' })

  const calls = fetch.mock.calls.map(({ arguments: [url, request] }) => ({
    path: new URL(url).pathname, method: request.method, body: JSON.parse(request.body), url,
  }))
  assert.deepEqual(calls.map(({ path }) => path), [
    '/users/register', '/users/forgot-password', '/users/reset-password', '/users/verify-email',
  ])
  assert.ok(calls.every(({ method, url }) => method === 'POST' && !url.includes(token)))
  assert.deepEqual(calls[2].body, { token, password: 'new-password' })
})

test('surfaces expired or reused link errors and structured input errors', async (t) => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => ({
    ok: false, json: async () => ({ detail: 'This link is invalid or expired. Request a new link.' }),
  }))
  await assert.rejects(accountRequest('reset-password', { token }), /invalid or expired/)
  fetch.mock.mockImplementation(async () => ({
    ok: false, json: async () => ({ detail: [{ msg: 'Enter a valid email address.' }] }),
  }))
  await assert.rejects(accountRequest('forgot-password', { email: 'invalid' }), /valid email address/)
})
