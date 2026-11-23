import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getNotificationPreferences, saveNotificationPreferences } from '../api'

export function EmailNotificationForm({ preferences, pending, onChange, onSubmit }) {
  const verified = Boolean(preferences.verified_email)
  return <form className="notification-preferences" onSubmit={onSubmit} aria-busy={pending}>
    <div className="notification-destination">
      <span>Verified destination</span>
      <strong className="mono">{preferences.verified_email ?? 'No verified email'}</strong>
      {!verified && <p><Link to="/resend-verification">Request a verification link</Link> to enable email alerts.</p>}
    </div>
    <fieldset disabled={!verified || pending}>
      <legend>Email me when</legend>
      <label className="notification-option">
        <input type="checkbox" checked={preferences.incident_opened} onChange={(event) => onChange('incident_opened', event.target.checked)} />
        <span><strong>An incident opens</strong><small>An endpoint fails three consecutive availability checks.</small></span>
      </label>
      <label className="notification-option">
        <input type="checkbox" checked={preferences.incident_recovered} onChange={(event) => onChange('incident_recovered', event.target.checked)} />
        <span><strong>An endpoint recovers</strong><small>A successful check automatically resolves an incident.</small></span>
      </label>
    </fieldset>
    {verified && <button type="submit" className="button primary" disabled={pending}>{pending ? 'Saving…' : 'Save preferences'}</button>}
  </form>
}

export default function Settings() {
  const [preferences, setPreferences] = useState(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState(false)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let active = true
    getNotificationPreferences(localStorage.getItem('access_token')).then(
      (data) => { if (active) setPreferences(data) },
      (err) => { if (active) setError(err.message) },
    )
    return () => { active = false }
  }, [reload])

  function change(field, value) {
    setMessage('')
    setPreferences((current) => ({ ...current, [field]: value }))
  }

  async function save(event) {
    event.preventDefault()
    if (!preferences.verified_email || pending) return
    setPending(true)
    setError('')
    setMessage('')
    try {
      const { incident_opened, incident_recovered } = preferences
      setPreferences(await saveNotificationPreferences(localStorage.getItem('access_token'), { incident_opened, incident_recovered }))
      setMessage('Notification preferences saved.')
    } catch (err) {
      setError(err.message)
    } finally {
      setPending(false)
    }
  }

  return <main className="workspace" id="main-content" tabIndex={-1}>
    <header className="page-heading"><div><h1>Settings</h1><p>Manage email notifications for your account.</p></div></header>
    <section className="surface notification-settings" aria-labelledby="notification-email">
      <header className="section-head">
        <div><h2 id="notification-email">Incident email</h2><p>In-app incident alerts stay available when email is off.</p></div>
      </header>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {message && <p className="notice" role="status">{message}</p>}
      {preferences ? <EmailNotificationForm preferences={preferences} pending={pending} onChange={change} onSubmit={save} /> :
        error ? <button className="button settings-retry" onClick={() => { setError(''); setReload((value) => value + 1) }}>Try again</button> :
          <p className="notice" role="status">Loading notification preferences…</p>}
    </section>
  </main>
}
