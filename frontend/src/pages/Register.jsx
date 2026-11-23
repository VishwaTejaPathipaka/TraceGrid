
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { registerUser } from '../api'
import AuthFrame from './AuthFrame'

function Register() {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const [message, setMessage] = useState('')

  async function handleRegister(event) {
    event.preventDefault()
    setError('')
    setLoading(true)

    try {
      const result = await registerUser(username, email, password)
      setPassword('')
      setMessage(result.message)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthFrame title="Create account" description="Set up your TraceGrid workspace.">
      {message ? <p className="notice" role="status">{message}</p> : <form onSubmit={handleRegister}>
        <label htmlFor="register-username">Username</label>
        <input
          id="register-username"
          type="text"
          autoComplete="username"
          maxLength={50}
          placeholder="Enter username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />

        <label htmlFor="register-email">Email</label>
        <input
          id="register-email"
          type="email"
          autoComplete="email"
          maxLength={100}
          placeholder="Enter email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />

        <label htmlFor="register-password">Password (12–128 characters)</label>
        <input
          id="register-password"
          type="password"
          autoComplete="new-password"
          minLength={12}
          maxLength={128}
          placeholder="Create password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        {error && <p role="alert" className="login-error">{error}</p>}

        <button className="login-submit" type="submit" disabled={loading}>
          {loading ? 'Creating account...' : 'Create account'}
        </button>
      </form>}

      <p className="login-footer">
        <Link to="/login">Sign in</Link>
        {message && <> {' · '} <Link to="/resend-verification">Resend verification</Link></>}
      </p>
    </AuthFrame>
  )
}

export default Register
