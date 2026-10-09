// Role-to-route table. This only decides what the UI shows: the API enforces every permission (docs/data_contract.md).
export const ROLES = { ADMIN: 'administrator', OPS: 'clinical_ops', ANALYST: 'analyst' }
const ALL = [ROLES.ADMIN, ROLES.OPS, ROLES.ANALYST]
const STAFF = [ROLES.ADMIN, ROLES.OPS]

export const ROUTES = [
  { path: '/dashboard', label: 'Dashboard', roles: ALL },
  { path: '/patients', label: 'Patients', roles: STAFF },
  { path: '/encounters', label: 'Encounters', roles: ALL },
  { path: '/reports', label: 'Reports', roles: ALL },
  { path: '/pipeline', label: 'Pipeline Runs', roles: STAFF },
  { path: '/data-quality', label: 'Data Quality', roles: STAFF },
  { path: '/audit', label: 'Audit Log', roles: [ROLES.ADMIN] },
  { path: '/users', label: 'Users', roles: [ROLES.ADMIN] },
]

export function hasRole(user, ...roles) {
  return Boolean(user && roles.includes(user.role))
}

export function canAccess(user, path) {
  const entry = ROUTES.find((r) => path === r.path || path.startsWith(`${r.path}/`))
  return Boolean(user && entry && entry.roles.includes(user.role))
}

export function navFor(user) {
  return user ? ROUTES.filter((r) => r.roles.includes(user.role)) : []
}

export const roleLabel = (role) => ({ administrator: 'Administrator', clinical_ops: 'Clinical operations', analyst: 'Analyst' }[role] || role)
