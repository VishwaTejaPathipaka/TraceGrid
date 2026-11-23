
import './App.css'
import { useCallback, useEffect, useEffectEvent, useRef } from 'react'
import {
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useNavigate,
} from 'react-router-dom'

import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Endpoints from './pages/Endpoints'
import Incidents from './pages/Incidents'
import Settings from './pages/Settings'
import Analytics from './pages/Analytics'
import Register from './pages/Register'
import AccountEmail from './pages/AccountEmail'
import { API_BASE_URL, logoutUser } from './api'
import { connectMonitoring, monitoringSocketUrl, SESSION_EXPIRED_EVENT, tokenExpiresAt } from './monitoringSocket'

function ProtectedRoute({ children }) {
  const token = localStorage.getItem('access_token')

  return token ? children : <Navigate to="/login" replace />
}

function MainLayout() {
  const navigate = useNavigate()
  const token = localStorage.getItem('access_token')
  const listeners = useRef(new Set())
  const socketHealthy = useRef(false)
  const subscribe = useCallback((listener) => {
    const subscriptions = listeners.current
    subscriptions.add(listener)
    listener({ type: 'monitoring.connection', healthy: socketHealthy.current })
    return () => subscriptions.delete(listener)
  }, [])

  function endSession(sessionToken) {
    if (localStorage.getItem('access_token') === sessionToken) localStorage.removeItem('access_token')
    navigate('/login', { replace: true })
  }
  const onSessionEnded = useEffectEvent(endSession)

  useEffect(() => {
    const expiry = tokenExpiresAt(token)
    const closeSession = () => onSessionEnded(token)
    const expireTimer = expiry === null ? null : setTimeout(closeSession, Math.max(0, expiry - Date.now()))
    const stop = connectMonitoring({
      url: monitoringSocketUrl(API_BASE_URL), token,
      onRefresh: (event) => listeners.current.forEach((listener) => listener(event)),
      onStatus: (healthy) => {
        socketHealthy.current = healthy
        listeners.current.forEach((listener) => listener({ type: 'monitoring.connection', healthy }))
      },
      onUnauthorized: closeSession,
    })
    function sessionChanged(event) {
      if ((event.key === 'access_token' || event.key === null) && localStorage.getItem('access_token') !== token) {
        closeSession()
      }
    }
    window.addEventListener('storage', sessionChanged)
    window.addEventListener(SESSION_EXPIRED_EVENT, closeSession)
    return () => {
      stop()
      socketHealthy.current = false
      clearTimeout(expireTimer)
      window.removeEventListener('storage', sessionChanged)
      window.removeEventListener(SESSION_EXPIRED_EVENT, closeSession)
    }
  }, [token])

  function handleLogout() {
    logoutUser(token).catch(() => {})
    endSession(token)
  }

  return (
    <>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="app-header">
        <div className="app-header-inner">
          <NavLink to="/dashboard" className="brand" aria-label="TraceGrid overview">
            <span className="brand-mark" aria-hidden="true">T</span>TraceGrid
          </NavLink>
          <nav className="app-nav" aria-label="Main navigation">
            <NavLink to="/dashboard">Overview</NavLink>
            <NavLink to="/endpoints">Endpoints</NavLink>
            <NavLink to="/incidents">Incidents</NavLink>
            <NavLink to="/analytics">Analytics</NavLink>
          </nav>
          <div className="header-actions">
            <NavLink to="/settings" className="button header-button">Settings</NavLink>
            <button className="button header-button" onClick={handleLogout}>Log out</button>
          </div>
        </div>
      </header>
      <Outlet context={subscribe} />
    </>
  )
}

function TitledPage({ title, children }) {
  useEffect(() => {
    document.title = `TraceGrid — ${title}`
  }, [title])
  return children
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<TitledPage title="Login"><Login /></TitledPage>} />
      <Route path="/register" element={<TitledPage title="Register"><Register /></TitledPage>} />
      <Route path="/forgot-password" element={<TitledPage title="Forgot password"><AccountEmail key="forgot" action="forgot-password" /></TitledPage>} />
      <Route path="/reset-password" element={<TitledPage title="Reset password"><AccountEmail key="reset" action="reset-password" /></TitledPage>} />
      <Route path="/verify-email" element={<TitledPage title="Verify email"><AccountEmail key="verify" action="verify-email" /></TitledPage>} />
      <Route path="/resend-verification" element={<TitledPage title="Resend verification"><AccountEmail key="resend" action="resend-verification" /></TitledPage>} />

      <Route
        element={
          <ProtectedRoute>
            <MainLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<TitledPage title="Overview"><Dashboard /></TitledPage>} />
        <Route path="/endpoints" element={<TitledPage title="Endpoints"><Endpoints /></TitledPage>} />
        <Route path="/incidents" element={<TitledPage title="Incidents"><Incidents /></TitledPage>} />
        <Route path="/analytics" element={<TitledPage title="Analytics"><Analytics /></TitledPage>} />
        <Route path="/settings" element={<TitledPage title="Settings"><Settings /></TitledPage>} />
      </Route>

      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

export default App
