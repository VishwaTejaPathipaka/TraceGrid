
const API_BASE_URL = "http://127.0.0.1:8000";

export async function loginUser(username, password) {
  const response = await fetch(`${API_BASE_URL}/users/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ username, password }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Login failed");
  }

  return data;
}


export async function registerUser(username, email, password) {
  const response = await fetch(`${API_BASE_URL}/users/register`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ username, email, password }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Registration failed");
  }

  return data;
}


export async function getDashboardSummary(token) {
  const response = await fetch(
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
  const endpointsResponse = await fetch(`${API_BASE_URL}/endpoints/`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!endpointsResponse.ok) {
    throw new Error("Unable to load endpoints");
  }

  const endpoints = await endpointsResponse.json();

  const historyResults = await Promise.all(
    endpoints.map(async (endpoint) => {
      const response = await fetch(
        `${API_BASE_URL}/monitor/${endpoint.id}/history`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (!response.ok) {
        throw new Error(`Unable to load history for ${endpoint.name}`);
      }

      const history = await response.json();

      return history.map((item) => ({
        ...item,
        endpoint_name: endpoint.name,
      }));
    })
  );

  return historyResults
    .flat()
    .sort(
      (a, b) =>
        new Date(b.checked_at) - new Date(a.checked_at)
    )
    .slice(0, 5);
}


export async function getEndpoints(token) {
  const response = await fetch(`${API_BASE_URL}/endpoints/`, {
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
  const response = await fetch(
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


export async function getMonitoringHistory(token, endpointId) {
  const response = await fetch(
    `${API_BASE_URL}/monitor/${endpointId}/history`,
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


export async function createEndpoint(token, endpoint) {
  const response = await fetch(`${API_BASE_URL}/endpoints/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(endpoint),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Unable to create endpoint");
  }

  return data;
}



export async function updateEndpoint(token, endpointId, endpoint) {
  const response = await fetch(
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
    throw new Error(data.detail || 'Unable to update endpoint')
  }

  return data
}


export async function deleteEndpoint(token, endpointId) {
  const response = await fetch(
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
  const response = await fetch(
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