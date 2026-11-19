
import { useEffect, useState } from 'react'
import { getEndpoints, createEndpoint, updateEndpoint, deleteEndpoint, checkEndpoint, getMonitoringHistory, getMonitoringAnalytics } from '../api'
function Endpoints() {
  const [endpoints, setEndpoints] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [method, setMethod] = useState('GET')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [checkResults, setCheckResults] = useState({})
  const [historyResults, setHistoryResults] = useState({})
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [analyticsResults, setAnalyticsResults] = useState({})
  const [loadingAnalytics, setLoadingAnalytics] = useState(false)


  useEffect(() => {
    async function loadEndpoints() {
      const token = localStorage.getItem('access_token')

      try {
        const data = await getEndpoints(token)
        setEndpoints(data)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }

    loadEndpoints()
  }, [])


  function handleEditClick(endpoint) {
    setEditingId(endpoint.id)
    setName(endpoint.name)
    setUrl(endpoint.url)
    setMethod(endpoint.method)
    setFormError('')
    setShowForm(true)
  }

  async function handleCreateEndpoint(e) {
    e.preventDefault()

    const token = localStorage.getItem('access_token')

    try {
      setSaving(true)
      setFormError('')

      await createEndpoint(token, {
        name,
        url,
        method,
      })

      const updatedEndpoints = await getEndpoints(token)
      setEndpoints(updatedEndpoints)

      setName('')
      setUrl('')
      setMethod('GET')
      setShowForm(false)
    } catch (err) {
      setFormError(err.message)
    } finally {
      setSaving(false)
    }
  }


  async function handleUpdateEndpoint(e) {
    e.preventDefault()

    const token = localStorage.getItem('access_token')

    try {
      setSaving(true)
      setFormError('')

      await updateEndpoint(token, editingId, {
        name,
        url,
        method,
      })

      const updatedEndpoints = await getEndpoints(token)
      setEndpoints(updatedEndpoints)

      setEditingId(null)
      setName('')
      setUrl('')
      setMethod('GET')
      setShowForm(false)
    } catch (err) {
      setFormError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteEndpoint(endpointId) {
    const confirmed = window.confirm(
      'Are you sure you want to delete this endpoint?'
    )

    if (!confirmed) return

    const token = localStorage.getItem('access_token')

    try {
      await deleteEndpoint(token, endpointId)

      const updatedEndpoints = await getEndpoints(token)
      setEndpoints(updatedEndpoints)
    } catch (err) {
      setError(err.message)
    }
  }


  async function handleCheckEndpoint(endpointId) {
    const token = localStorage.getItem('access_token')

    try {
      const result = await checkEndpoint(token, endpointId)

      setCheckResults((prev) => ({
        ...prev,
        [endpointId]: result,
      }))
    } catch (err) {
      alert(err.message)
    }
  }


  async function handleViewHistory(endpointId) {
    const token = localStorage.getItem('access_token')

    try {
      setLoadingHistory(true)

      const history = await getMonitoringHistory(token, endpointId)

      setHistoryResults((prev) => ({
        ...prev,
        [endpointId]: Array.isArray(history) ? history : [],
      }))
    } catch (err) {
      alert(err.message)
    } finally {
      setLoadingHistory(false)
    }
  }


  async function handleViewAnalytics(endpointId) {
    const token = localStorage.getItem('access_token')

    try {
      setLoadingAnalytics(true)

      const analytics = await getMonitoringAnalytics(token, endpointId)

      setAnalyticsResults((prev) => ({
        ...prev,
        [endpointId]: analytics,
      }))
    } catch (err) {
      alert(err.message)
    } finally {
      setLoadingAnalytics(false)
    }
  }


  if (loading) return <main className="dashboard">Loading endpoints...</main>
  if (error) return <main className="dashboard error-text">{error}</main>

  return (
    <main className="dashboard">
      <div className="page-heading">
        <div>
          <h1>Endpoints</h1>
          <p>Manage the APIs you want to monitor.</p>
        </div>
      </div>

      <section className="activity-section">
        <div className="section-heading endpoints-heading">
          <div>
            <h2>Registered Endpoints</h2>
            <p>{endpoints.length} endpoints registered</p>
          </div>

          <button
            className="add-endpoint-button"
            onClick={() => setShowForm(true)}
          >
            + Add Endpoint
          </button>
        </div>


        
        {showForm && (
          <form
            className="endpoint-form"
            onSubmit={editingId ? handleUpdateEndpoint : handleCreateEndpoint}
          >
            <div className="endpoint-form-header">
              <div>
                <h3>{editingId ? 'Edit endpoint' : 'Add a new endpoint'}</h3>
                <p>Enter the API details you want TraceGrid to monitor.</p>
              </div>

              <button
                type="button"
                className="form-close-button"
                onClick={() => {
                  setShowForm(false)
                  setFormError('')
                }}
              >
                ×
              </button>
            </div>

            <div className="endpoint-form-grid">
              <div className="form-field">
                <label>Endpoint name</label>
                <input
                  type="text"
                  placeholder="e.g. User Authentication API"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>

              <div className="form-field">
                <label>HTTP method</label>
                <select
                  value={method}
                  onChange={(e) => setMethod(e.target.value)}
                >
                  <option value="GET">GET</option>
                  <option value="POST">POST</option>
                  <option value="PUT">PUT</option>
                  <option value="DELETE">DELETE</option>
                </select>
              </div>

              <div className="form-field full-width">
                <label>Endpoint URL</label>
                <input
                  type="url"
                  placeholder="https://api.example.com/users"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  required
                />
              </div>
            </div>

            {formError && <p className="error-text">{formError}</p>}

            <div className="form-actions">
              <button
                type="button"
                className="cancel-form-button"
                onClick={() => {
          setShowForm(false)
          setFormError('')
                }}
              >
                Cancel
              </button>

              <button
                type="submit"
                className="save-endpoint-button"
                disabled={saving}
              >
                {saving ? 'Adding...' : 'Add Endpoint'}
              </button>
            </div>
          </form>
        )}



        <div className="activity-table-wrapper">
          <table className="activity-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>URL</th>
                <th>Method</th>
                <th>Status</th>
                <th>Monitoring Result</th>
                <th>Action</th>
              </tr>
            </thead>

            <tbody>
              {endpoints.length > 0 ? (
                endpoints.map((endpoint) => (
                  <tr key={endpoint.id}>
                    <td>{endpoint.name}</td>
                    <td>{endpoint.url}</td>
                    <td>{endpoint.method}</td>
                    <td>
                      {endpoint.is_active ? 'Active' : 'Inactive'}
                    </td>
                    <td>
                      {checkResults[endpoint.id] ? (
                        <>
                          <strong>{checkResults[endpoint.id].status}</strong>
                          <div>
                            HTTP {checkResults[endpoint.id].status_code}
                          </div>
                          <div>
                            {checkResults[endpoint.id].response_time} ms
                          </div>
                        </>
                      ) : (
                        'Not checked'
                      )}
                    </td>
                    <td>
                      <button
                      className="check-endpoint-button"
                      onClick={() => handleCheckEndpoint(endpoint.id)}>
                      Check
                      </button>

                      <button
                      className="history-endpoint-button"
                      onClick={() => handleViewHistory(endpoint.id)}>
                      History
                      </button>

                      <button
                      className="analytics-endpoint-button"
                      onClick={() => handleViewAnalytics(endpoint.id)}>
                      Analytics
                      </button>

                      <button 
                      className="edit-endpoint-button"
                      onClick={() => handleEditClick(endpoint)}>
                      Edit
                      </button>

                      <button 
                      className="delete-endpoint-button"
                      onClick={() => handleDeleteEndpoint(endpoint.id)}>
                      Delete
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan="4" className="empty-activity">
                    No endpoints registered yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {Object.keys(historyResults).map((endpointId) => {
          const endpoint = endpoints.find(
            (item) => item.id === Number(endpointId)
          )

          if (!endpoint) return null

          return (
            <div className="history-section" key={endpointId}>
              <h3>Monitoring History - {endpoint.name}</h3>

              {loadingHistory ? (
                <p>Loading history...</p>
              ) : (
                <div className="activity-table-wrapper">
                  <table className="activity-table">
                    <thead>
                      <tr>
                        <th>Status</th>
                        <th>HTTP Code</th>
                        <th>Response Time</th>
                        <th>Checked At</th>
                      </tr>
                    </thead>

                    <tbody>
                      {historyResults[endpointId].length > 0 ? (
                        historyResults[endpointId].map((record) => (
                          <tr key={record.id}>
                            <td>{record.status}</td>
                            <td>{record.status_code}</td>
                            <td>{record.response_time} ms</td>
                            <td>
                              {new Date(record.checked_at).toLocaleString()}
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan="4">No monitoring history available.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )
        })}


        {Object.keys(analyticsResults).map((endpointId) => {
          const endpoint = endpoints.find(
            (item) => item.id === Number(endpointId)
          )

          if (!endpoint) return null

          const analytics = analyticsResults[endpointId]

          return (
            <div className="history-section" key={endpointId}>
              <h3>Analytics - {endpoint.name}</h3>

              {loadingAnalytics ? (
                <p>Loading analytics...</p>
              ) : (
                <div className="analytics-grid">
                  <div className="analytics-card">
                    <h4>Total Checks</h4>
                    <p>{analytics.total_checks}</p>
                  </div>

                  <div className="analytics-card">
                    <h4>Successful Checks</h4>
                    <p>{analytics.successful_checks}</p>
                  </div>

                  <div className="analytics-card">
                    <h4>Failed Checks</h4>
                    <p>{analytics.failed_checks}</p>
                  </div>

                  <div className="analytics-card">
                    <h4>Average Response Time</h4>
                    <p>{analytics.average_response_time} ms</p>
                  </div>

                  <div className="analytics-card">
                    <h4>Uptime</h4>
                    <p>{analytics.uptime_percentage}%</p>
                  </div>
                </div>
              )}
            </div>
          )
        })}


      </section>
    </main>
  )
}

export default Endpoints
