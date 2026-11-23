
import { SESSION_EXPIRED_EVENT } from './monitoringSocket.js'

export const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

function checkRequestLimit(response) {
  if (response.status !== 429) return
  const retry = response.headers.get('Retry-After')
  if (retry && /^\d+$/.test(retry)) {
    throw new Error(`Too many requests. Try again in ${retry} seconds.`)
  }
  throw new Error('Too many requests. Try again shortly.')
}

async function authenticatedFetch(url, options) {
  const response = await fetch(url, options)
  checkRequestLimit(response)
  if (response.status === 401) {
    const currentToken = localStorage.getItem('access_token')
    if (currentToken && options.headers.Authorization === `Bearer ${currentToken}`) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
    }
  }
  return response
}

export async function logoutUser(token) {
  const response = await fetch(`${API_BASE_URL}/users/logout`, {
    method: 'POST', headers: { Authorization: `Bearer ${token}` }, keepalive: true,
  })
  if (!response.ok && response.status !== 401) throw new Error('Unable to revoke session')
}

export async function loginUser(username, password) {
  return accountRequest('login', { username, password })
}


export async function registerUser(username, email, password) {
  return accountRequest('register', { username, email, password })
}

export async function accountRequest(action, payload) {
  const response = await fetch(`${API_BASE_URL}/users/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  checkRequestLimit(response)
  const data = await response.json()
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail
    throw new Error(detail || 'Unable to complete the request. Try again.')
  }
  return data
}


export async function getDashboardSummary(token) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/monitor/dashboard/summary`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Unable to load dashboard");
  }

  return data;
}


export async function getRecentActivity(token) {
  const response = await authenticatedFetch(`${API_BASE_URL}/monitor/dashboard/recent`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) throw new Error('Unable to load recent monitoring activity')
  return response.json()
}


export async function getEndpoints(token) {
  const response = await authenticatedFetch(`${API_BASE_URL}/endpoints/`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Unable to load endpoints");
  }

  return data;
}

export async function checkEndpoint(token, endpointId) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/monitor/${endpointId}/check`,
    {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  )

  const data = await response.json()

  if (!response.ok) {
    throw new Error(data.detail || 'Unable to check endpoint')
  }

  return data
}


export async function getMonitoringHistory(token, endpointId, { limit = 100, before } = {}) {
  const query = new URLSearchParams({ limit, ...(before ? { before_id: before } : {}) })
  const response = await authenticatedFetch(
    `${API_BASE_URL}/monitor/${endpointId}/history?${query}`,
    {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  )

  const data = await response.json()

  if (!response.ok) {
    throw new Error(data.detail || 'Unable to fetch monitoring history')
  }

  return data
}

function endpointSaveError(data, fallback) {
  if (Array.isArray(data.detail)) {
    return data.detail.map(({ msg }) => msg).join(' ')
  }
  return data.detail || fallback
}


export async function createEndpoint(token, endpoint) {
  const response = await authenticatedFetch(`${API_BASE_URL}/endpoints/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(endpoint),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(endpointSaveError(data, "Unable to create endpoint"));
  }

  return data;
}



export async function updateEndpoint(token, endpointId, endpoint) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/endpoints/${endpointId}`,
    {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(endpoint),
    }
  )

  const data = await response.json()

  if (!response.ok) {
    throw new Error(endpointSaveError(data, 'Unable to update endpoint'))
  }

  return data
}


export async function deleteEndpoint(token, endpointId) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/endpoints/${endpointId}`,
    {
      method: 'DELETE',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  )

  if (!response.ok) {
    const data = await response.json()
    throw new Error(data.detail || 'Unable to delete endpoint')
  }

  return true
}


export async function getMonitoringAnalytics(token, endpointId) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/monitor/${endpointId}/analytics`,
    {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  )

  const data = await response.json()

  if (!response.ok) {
    throw new Error(data.detail || 'Unable to fetch analytics')
  }

  return data
}

async function incidentRequest(token, path, method = 'GET') {
  const response = await authenticatedFetch(`${API_BASE_URL}/incidents/${path}`, {
    method, headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'Unable to complete the incident request.')
  }
  return response.json()
}

export function getIncidents(token, filters) {
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== ''))
  return incidentRequest(token, `?${query}`)
}

export function getIncidentSummary(token) {
  return incidentRequest(token, 'summary')
}

export function changeIncident(token, incidentId, action) {
  return incidentRequest(token, `${incidentId}/${action}`, 'POST')
}

async function notificationPreferencesRequest(token, preferences) {
  const updating = preferences !== undefined
  const response = await authenticatedFetch(`${API_BASE_URL}/users/notification-preferences`, {
    method: updating ? 'PUT' : 'GET',
    headers: { Authorization: `Bearer ${token}`, ...(updating && { 'Content-Type': 'application/json' }) },
    body: updating ? JSON.stringify(preferences) : undefined,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'Unable to load or save notification preferences.')
  }
  return response.json()
}

export function getNotificationPreferences(token) {
  return notificationPreferencesRequest(token)
}

export function saveNotificationPreferences(token, preferences) {
  return notificationPreferencesRequest(token, preferences)
}

async function analyticsRequest(token, path, params) {
  const response = await authenticatedFetch(`${API_BASE_URL}/analytics/${path}?${new URLSearchParams(params)}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const failure = await response.json().catch(() => null)
    throw new Error(typeof failure?.detail === 'string' ? failure.detail : 'Unable to load analytics.')
  }
  return response.json()
}

export function getAnalyticsReport(token, { endpointId, range, compare, metric, descending, offset }) {
  return analyticsRequest(token, 'report', {
    range, compare, metric, descending, offset, ...(endpointId ? { endpoint_id: endpointId } : {}),
  })
}

export function getAnalyticsChecks(token, endpointId, range, end, bucket, cursor) {
  return analyticsRequest(token, `endpoints/${endpointId}/checks`, {
    range, end, bucket, ...(cursor ? { after_at: cursor.at, after_id: cursor.id } : {}),
  })
}
