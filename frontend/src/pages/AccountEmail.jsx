import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { accountRequest } from '../api'
import { accountLinkToken } from '../accountLink'
import AuthFrame from './AuthFrame'

const pages = {
  'forgot-password': ['Forgot password?', 'Send reset link'],
  'resend-verification': ['Resend verification', 'Send verification link'],
  'verify-email': ['Verify your email', 'Verify email'],
  'reset-password': ['Reset your password', 'Reset password'],
}

export default function AccountEmail({ action }) {
  const [title, button] = pages[action]
  const resetting = action === 'reset-password'
  const verifying = action === 'verify-email'
  const usesLink = resetting || verifying
  const recoveryPath = resetting ? '/forgot-password' : '/resend-verification'
  const [token] = useState(() => usesLink ? accountLinkToken(window.location.hash) : null)
  const [value, setValue] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (usesLink && window.location.hash) {
      window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search)
    }
  }, [usesLink])

  async function submit(event) {
    event.preventDefault()
    setError('')
    if (resetting && value !== confirmation) {
      setError('Passwords must match.')
      return
    }
    setLoading(true)
    try {
      const payload = usesLink ? { token, password: value } : { email: value }
      const result = await accountRequest(action, payload)
      setMessage(result.message)
      setValue('')
      setConfirmation('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthFrame title={title} description={verifying ? "Enter your account password to confirm this address." : undefined}>
      {message ? <p className="notice" role="status">{message}</p> : (
        usesLink && !token ? <p className="login-error" role="alert">This link is missing or invalid.</p> : (
          <form onSubmit={submit}>
            {usesLink && (
              <>
                <label htmlFor="account-password">
                  {resetting ? 'New password (12–128 characters)' : 'Account password'}
                </label>
                <input id="account-password" type="password"
                  autoComplete={resetting ? 'new-password' : 'current-password'} required
                  minLength={12} maxLength={128} value={value} onChange={(event) => setValue(event.target.value)} />
              </>
            )}
            {resetting && (
              <>
                <label htmlFor="account-confirmation">Confirm password</label>
                <input id="account-confirmation" type="password" autoComplete="new-password" required
                  minLength={12} maxLength={128} value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)} />
              </>
            )}
            {!usesLink && (
              <>
                <label htmlFor="account-email">Email</label>
                <input id="account-email" type="email" autoComplete="email" required
                  maxLength={100} value={value} onChange={(event) => setValue(event.target.value)} />
              </>
            )}
            {error && <p className="login-error" role="alert">{error}</p>}
            <button type="submit" className="login-submit" disabled={loading}>
              {loading ? 'Please wait…' : button}
            </button>
          </form>
        )
      )}

      <p className="login-footer">
        <Link to="/login">Sign in</Link>
        {usesLink && !message && <> {' · '} <Link to={recoveryPath}>Request a new link</Link></>}
      </p>
    </AuthFrame>
  )
}
