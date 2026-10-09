import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { NotPermitted, ProtectedRoute, RoleRoute } from './components/guards'
import { ROLES } from './lib/roles'
import { AuditLog, DataQuality, PipelineRuns, Users } from './pages/Admin'
import Dashboard from './pages/Dashboard'
import Encounters from './pages/Encounters'
import Login from './pages/Login'
import Patients, { PatientDetail } from './pages/Patients'
import Reports from './pages/Reports'

const STAFF = [ROLES.ADMIN, ROLES.OPS]
const ALL = [ROLES.ADMIN, ROLES.OPS, ROLES.ANALYST]

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route element={<RoleRoute roles={ALL} />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/encounters" element={<Encounters />} />
            <Route path="/reports" element={<Reports />} />
          </Route>
          <Route element={<RoleRoute roles={STAFF} />}>
            <Route path="/patients" element={<Patients />} />
            <Route path="/patients/:id" element={<PatientDetail />} />
            <Route path="/pipeline" element={<PipelineRuns />} />
            <Route path="/data-quality" element={<DataQuality />} />
          </Route>
          <Route element={<RoleRoute roles={[ROLES.ADMIN]} />}>
            <Route path="/audit" element={<AuditLog />} />
            <Route path="/users" element={<Users />} />
          </Route>
          <Route path="*" element={<NotPermitted />} />
        </Route>
      </Route>
    </Routes>
  )
}
