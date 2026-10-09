import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Loading } from './states'

// Guards improve the experience only. A user can call the API directly, so the server checks (docs/data_contract.md) are
// the real protection; these just keep people out of pages they cannot use.
export function ProtectedRoute() {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="page"><Loading label="Checking your session…" /></div>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return <Outlet />
}

export function NotPermitted() {
  return (
    <div className="page">
      <h1>Not permitted</h1>
      <p>Your role does not have access to this page. If you need it, ask an administrator.</p>
    </div>
  )
}

export function RoleRoute({ roles }) {
  const { user } = useAuth()
  return user && roles.includes(user.role) ? <Outlet /> : <NotPermitted />
}
