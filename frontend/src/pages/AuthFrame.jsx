import { Link } from 'react-router-dom'
import './Login.css'

export default function AuthFrame({ title, description, children }) {
  return (
    <main className="login-page">
      <aside className="auth-brand-panel">
        <Link className="brand" to="/login"><span className="brand-mark" aria-hidden="true">T</span>TraceGrid</Link>
        <div className="auth-intro">
          <p>API monitoring<br />and observability</p>
        </div>
      </aside>
      <section className="login-panel" aria-labelledby="auth-title">
        <header className="login-heading">
          <h1 id="auth-title">{title}</h1>
          {description && <p>{description}</p>}
        </header>
        {children}
      </section>
    </main>
  )
}
