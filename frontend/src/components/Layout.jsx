import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { navFor, roleLabel } from '../lib/roles'

export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const signOut = () => { logout(); navigate('/login', { replace: true }) }
  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">Healthcare<br /><span>Patient Management</span></div>
        <nav>
          {navFor(user).map((item) => (
            <NavLink key={item.path} to={item.path} className={({ isActive }) => (isActive ? 'active' : undefined)}>{item.label}</NavLink>
          ))}
        </nav>
        <p className="edu">Educational use only. De-identified research data, 1999–2008.</p>
      </aside>
      <div className="content">
        <header className="topbar">
          <span className="who" data-testid="who">{user.username}</span>
          <span className={`role-badge role-${user.role}`} data-testid="role">{roleLabel(user.role)}</span>
          <button type="button" className="btn" onClick={signOut}>Log out</button>
        </header>
        <main id="main" className="page" tabIndex={-1}><Outlet /></main>
      </div>
    </div>
  )
}
