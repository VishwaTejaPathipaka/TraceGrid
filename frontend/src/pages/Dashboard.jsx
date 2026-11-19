
import { useEffect, useState } from 'react'
import { getDashboardSummary, getRecentActivity } from '../api'

function Dashboard() {
  const [summary, setSummary] = useState(null)
  const [activities, setActivities] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)

  useEffect(() => {
    async function loadDashboard() {
      const token = localStorage.getItem('access_token')

      if (!token) {
        setError('Please log in to continue.')
        setLoading(false)
        return
      }

      try {
        const data = await getDashboardSummary(token)
        setSummary(data)

        const recentData = await getRecentActivity(token)
        setActivities(recentData)
        setLastUpdated(new Date())

        setError('')
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }

    loadDashboard()

    const interval = setInterval(loadDashboard, 30000)

    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return <main className="dashboard">Loading dashboard...</main>
  }

  if (error) {
    return <main className="dashboard error-text">{error}</main>
  }

  const cards = [
    ['Total endpoints', summary.total_endpoints],
    ['Active endpoints', summary.active_endpoints],
    ['Total checks', summary.total_checks],
    ['Successful checks', summary.successful_checks],
    ['Failed checks', summary.failed_checks],
    ['Average response time', `${summary.average_response_time} ms`],
    ['Uptime', `${summary.uptime_percentage}%`],
  ]

  return (
    <main className="dashboard">
      <div className="page-heading">
        <div>
          <h1>Overview</h1>
          <p>Monitor your API performance and availability.</p>

          {lastUpdated && (
            <p className="last-updated">
              Last updated: {lastUpdated.toLocaleTimeString()}
            </p>
          )}
        </div>
      </div>

      <section className="summary-grid">
        {cards.map(([label, value]) => (
          <div className="summary-card" key={label}>
            <p>{label}</p>
            <h2 className={label === 'Failed checks' && value > 0 ? 'error-text' : ''}>
              {value}
            </h2>
          </div>
        ))}
      </section>


            <section className="activity-section">
        <div className="section-heading">
          <div>
            <h2>Recent Monitoring Activity</h2>
            <p>Latest checks across your monitored endpoints.</p>
          </div>
        </div>

        <div className="activity-table-wrapper">
          <table className="activity-table">
            <thead>
              <tr>
                <th>Endpoint</th>
                <th>Status</th>
                <th>HTTP Code</th>
                <th>Response Time</th>
                <th>Last Checked</th>
              </tr>
            </thead>

            <tbody>
              {activities.length > 0 ? (
                activities.map((activity) => (
                  <tr key={activity.id}>
                    <td>{activity.endpoint_name}</td>
                    <td>
                      <span className={activity.status === 'UP' ? 'status-up' : 'status-down'}>
                        {activity.status}
                      </span>
                    </td>
                    <td>{activity.status_code ?? '—'}</td>
                    <td>{activity.response_time} ms</td>
                    <td>{new Date(activity.checked_at).toLocaleString()}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan="5" className="empty-activity">
                    No monitoring activity yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

    </main>
  )
}

export default Dashboard
