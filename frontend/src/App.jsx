
import './App.css'
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
import Register from './pages/Register'

function ProtectedRoute({ children }) {
  const token = localStorage.getItem('access_token')

  return token ? children : <Navigate to="/login" replace />
}

function MainLayout() {
  const navigate = useNavigate()

  function handleLogout() {
    localStorage.removeItem('access_token')
    navigate('/login')
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">T</span>
          <span>TraceGrid</span>
        </div>

        <div className="nav-section">
          <p className="nav-heading">WORKSPACE</p>

          <NavLink to="/dashboard" className="nav-link">
            Overview
          </NavLink>

          <NavLink to="/endpoints" className="nav-link">
            Endpoints
          </NavLink>

          <a href="#" className="nav-link">Monitoring</a>
          <a href="#" className="nav-link">Analytics</a>
        </div>

        <div className="sidebar-bottom">
          <div className="user-info">
            <div className="user-avatar">U</div>
            <div>
              <strong>My Account</strong>
              <span>Developer</span>
            </div>
          </div>
        </div>
      </aside>

      <div className="main-content">
        <header className="topbar">
          <span>Workspace / TraceGrid</span>
          <button className="logout-button" onClick={handleLogout}>
            Log out
          </button>
        </header>

        <Outlet />
      </div>
    </div>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      <Route
        element={
          <ProtectedRoute>
            <MainLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/endpoints" element={<Endpoints />} />
      </Route>

      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

export default App
