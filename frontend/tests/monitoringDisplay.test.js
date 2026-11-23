import assert from 'node:assert/strict'
import { test } from 'node:test'
import { endpointConfigurationError, endpointHealth, formatUptime, latency, probeStatusLabel, probeTone, scheduleStatus } from '../src/monitoringDisplay.js'

test('distinguishes missing samples from measured zero uptime', () => {
  assert.equal(formatUptime(null), 'No data')
  assert.equal(formatUptime(0), '0%')
  assert.equal(formatUptime(62.5), '62.5%')
})

test('labels redirects including history created before redirect statuses were stored', () => {
  assert.equal(probeStatusLabel({ status: 'REDIRECT', status_code: 302 }), 'Redirect')
  assert.equal(probeStatusLabel({ status: 'DOWN', status_code: 307 }), 'Redirect')
  assert.equal(probeStatusLabel({ status: 'DOWN', status_code: 304, reason: 'http_error' }),
    'DOWN · Unsuccessful HTTP response')
})

test('displays infrastructure and target errors with distinct reasons', () => {
  assert.equal(probeStatusLabel({ status: 'ERROR', reason: 'dns_timeout' }), 'Monitoring error · DNS lookup timed out')
  assert.equal(probeStatusLabel({ status: 'DOWN', reason: 'dns_resolution' }), 'DOWN · DNS resolution failed')
  assert.equal(probeStatusLabel({ status: 'DOWN', reason: 'tls_verification' }), 'DOWN · TLS certificate verification failed')
  assert.equal(probeStatusLabel({ status: 'DOWN', reason: 'connection' }), 'DOWN · Connection failed')
  assert.equal(probeStatusLabel({ status: 'DOWN', reason: 'timeout' }), 'DOWN · Probe timed out')
})

test('shows scheduled configuration errors and hides them when cleared', () => {
  assert.equal(endpointConfigurationError({ method: 'HEAD', configuration_error: 'Use a public URL.' }),
    'Use a public URL.')
  assert.equal(endpointConfigurationError({ method: 'HEAD', configuration_error: null }), null)
  assert.equal(endpointConfigurationError({ method: 'POST' }), 'Edit this endpoint to use GET or HEAD.')
})

test('indicates upcoming, due and overdue checks independently of availability', () => {
  const next_check_at = '2026-11-23T00:00:30Z'
  const due = Date.parse(next_check_at)
  const active = { is_active: true, next_check_at, latest_check: { status: 'UP' } }
  assert.deepEqual(scheduleStatus(active, due - 3000), { label: 'Due in 3 s', overdue: false })
  assert.deepEqual(scheduleStatus(active, due), { label: 'Due now', overdue: false })
  assert.deepEqual(scheduleStatus(active, due + 12_000), { label: 'Overdue by 12 s', overdue: true })
  assert.deepEqual(scheduleStatus({ ...active, is_active: false }, due), { label: 'Inactive', overdue: false })
})

test('groups endpoint health by the latest real result, schedule and configuration', () => {
  const active = { method: 'GET', is_active: true }
  const up = { status: 'UP', status_code: 200 }
  assert.equal(endpointHealth({ ...active, latest_check: up }), 'up')
  assert.equal(endpointHealth({ ...active, latest_check: up, configuration_error: 'Blocked target' }), 'error')
  assert.equal(endpointHealth({ ...active, latest_check: up, is_active: false }), 'inactive')
  assert.equal(endpointHealth(active), 'neutral')
  assert.equal(probeTone({ status: 'DOWN', status_code: 302 }), 'redirect')
  assert.equal(probeTone({ status: 'DOWN', status_code: 500 }), 'down')
  assert.equal(probeTone({ status: 'ERROR' }), 'error')
})

test('preserves measured zero response time and distinguishes missing values', () => {
  assert.equal(latency(0), '0 ms')
  assert.equal(latency(null), '—')
  assert.equal(latency(undefined), '—')
})
