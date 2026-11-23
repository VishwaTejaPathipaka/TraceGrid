export const SESSION_EXPIRED_EVENT = 'tracegrid:session-expired'

export function monitoringSocketUrl(apiBaseUrl, origin = globalThis.location?.origin) {
  const url = new URL(`${apiBaseUrl.replace(/\/$/, '')}/ws/monitoring`, origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

export function tokenExpiresAt(token) {
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    const { exp } = JSON.parse(atob(payload))
    return Number.isFinite(exp) ? exp * 1000 : null
  } catch {
    return null
  }
}

export const isIncidentRefresh = (event) => ['monitoring.ready', 'monitoring.resync', 'incident.updated'].includes(event?.type)
export const isEndpointRefresh = (event) => ['monitoring.ready', 'monitoring.resync', 'endpoint.updated'].includes(event?.type)

export function connectMonitoring({ url, token, onRefresh, onUnauthorized, onStatus = () => {} }, {
  WebSocketImpl = globalThis.WebSocket,
  schedule = globalThis.setTimeout,
  cancel = globalThis.clearTimeout,
} = {}) {
  let socket = null
  let retry = null
  let stopped = false
  let delay = 1000
  let watchdog = null

  function clearWatchdog() {
    if (watchdog !== null) cancel(watchdog)
    watchdog = null
  }

  function stop() {
    stopped = true
    clearWatchdog()
    if (retry !== null) cancel(retry)
    if (socket) socket.close()
    socket = null
  }

  function reconnect() {
    retry = schedule(openSocket, delay)
    delay = Math.min(delay * 2, 30_000)
  }

  function openSocket() {
    retry = null
    if (stopped) return
    let current
    try {
      current = new WebSocketImpl(url)
    } catch {
      reconnect()
      return
    }
    socket = current
    let authenticated = false
    function watch() {
      clearWatchdog()
      watchdog = schedule(() => {
        watchdog = null
        if (stopped || socket !== current) return
        socket = null
        current.close()
        onStatus(false)
        reconnect()
      }, 70_000)
    }
    current.onopen = () => {
      if (!stopped && socket === current) {
        current.send(JSON.stringify({ type: 'authenticate', token }))
      }
    }
    current.onmessage = ({ data }) => {
      if (stopped || socket !== current) return
      let message
      try {
        message = JSON.parse(data)
      } catch {
        return
      }
      if (message?.type === 'monitoring.ready') {
        authenticated = true
        delay = 1000
        watch()
        onStatus(true)
        onRefresh(message)
      } else if (authenticated && message?.type === 'monitoring.heartbeat') {
        watch()
      } else if (authenticated && (message?.type === 'monitoring.resync' ||
        (['monitoring.updated', 'endpoint.updated'].includes(message?.type) && Number.isInteger(message.endpoint_id)) ||
        (message?.type === 'incident.updated' && Number.isInteger(message.incident_id) &&
          ['created', 'acknowledged', 'resolved'].includes(message.action)))) {
        watch()
        onRefresh(message)
      }
    }
    current.onclose = ({ code }) => {
      if (stopped || socket !== current) return
      socket = null
      clearWatchdog()
      onStatus(false)
      if (code === 4401) {
        stop()
        onUnauthorized()
      } else {
        reconnect()
      }
    }
  }

  openSocket()
  return stop
}
