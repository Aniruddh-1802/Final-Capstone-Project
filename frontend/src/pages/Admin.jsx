import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, toErrorMessage, toFieldErrors } from '../api/client'
import { DataTable, Pagination } from '../components/DataTable'
import { FilterForm } from '../components/FilterForm'
import { Modal } from '../components/Modal'
import { Badge } from '../components/states'
import { useToast } from '../components/Toast'
import { useListPage } from '../hooks/useListPage'
import { formatDate, formatInt, formatPercent, rejectRatio, statusClass } from '../lib/format'

// Fields that differ between the before and after snapshots of an audit row (display only).
function changedKeys(before, after) {
  const a = before || {}
  const b = after || {}
  return [...new Set([...Object.keys(a), ...Object.keys(b)])].filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]))
}

function AuditDetail({ row }) {
  const keys = changedKeys(row.before_json, row.after_json)
  return (
    <div className="audit-detail">
      <p><strong>Request</strong> {row.request_id || '-'} · <strong>IP</strong> {row.ip_address || '-'}</p>
      <table className="data compact">
        <thead><tr><th scope="col">Field</th><th scope="col">Before</th><th scope="col">After</th></tr></thead>
        <tbody>{keys.map((k) => (
          <tr key={k}><td>{k}</td><td><code>{JSON.stringify(row.before_json?.[k]) ?? '-'}</code></td><td><code>{JSON.stringify(row.after_json?.[k]) ?? '-'}</code></td></tr>))}</tbody>
      </table>
      {!keys.length && <p className="muted-text">No field changed.</p>}
    </div>
  )
}

export function AuditLog() {
  const list = useListPage('/admin/audit-logs', { defaultSort: 'created_at', defaultDir: 'desc' })
  const [open, setOpen] = useState(null)
  const fields = [
    { name: 'user', label: 'User', type: 'text' },
    { name: 'action', label: 'Action', type: 'select', options: ['CREATE', 'UPDATE', 'DELETE', 'EXPORT'].map((a) => ({ value: a, label: a })) },
    { name: 'entity_type', label: 'Entity', type: 'text', placeholder: 'patient, encounter…' }, { name: 'entity_id', label: 'Entity ID', type: 'text' },
    { name: 'date_from', label: 'From', type: 'date' }, { name: 'date_to', label: 'To', type: 'date' },
  ]
  const page = list.data
  const columns = [
    { key: 'created_at', label: 'When', sortKey: 'created_at', render: (r) => formatDate(r.created_at) },
    { key: 'username', label: 'User', render: (r) => `${r.username} (${r.role})` },
    { key: 'action', label: 'Action', render: (r) => <Badge className={`badge ${r.action === 'DELETE' ? 'bad' : r.action === 'CREATE' ? 'ok' : 'warn'}`}>{r.action}</Badge> },
    { key: 'entity_type', label: 'Entity' }, { key: 'entity_id', label: 'ID' },
    { key: 'diff', label: 'Details', render: (r) => <button type="button" className="link" aria-expanded={open === r.id} onClick={(e) => { e.stopPropagation(); setOpen(open === r.id ? null : r.id) }}>{open === r.id ? 'Hide' : 'Show before/after'}</button> },
  ]
  return (
    <div>
      <h1>Audit log</h1>
      <p className="muted-text">Every create, update, delete and encounter-level export, with the values before and after. Passwords and tokens are never recorded.</p>
      <FilterForm fields={fields} values={list.filters} onApply={list.setFilters} label="Audit filters" />
      <DataTable columns={columns} rows={page?.items} loading={list.loading} error={list.error} onRetry={list.reload}
                 sortBy={list.sortBy} sortDir={list.sortDir} onSort={list.onSort} rowKey={(r) => r.id} />
      {page?.items?.filter((r) => r.id === open).map((r) => <AuditDetail key={r.id} row={r} />)}
      {page && <Pagination page={page.page} pages={page.pages} total={page.total} pageSize={page.page_size} onPage={list.setPage} />}
    </div>
  )
}

export function PipelineRuns() {
  const list = useListPage('/admin/pipeline-runs', { defaultSort: 'started_at', defaultDir: 'desc' })
  const fields = [
    { name: 'status', label: 'Status', type: 'select', options: ['SUCCESS', 'FAILED', 'RUNNING', 'SKIPPED_DUPLICATE_FILE'].map((s) => ({ value: s, label: s })) },
    { name: 'date_from', label: 'From', type: 'date' }, { name: 'date_to', label: 'To', type: 'date' },
  ]
  const page = list.data
  const columns = [
    { key: 'run_id', label: 'Run', sortKey: 'run_id' }, { key: 'source_file', label: 'File' },
    { key: 'status', label: 'Status', render: (r) => <Badge className={statusClass(r.status)}>{r.status}</Badge> },
    { key: 'started_at', label: 'Started', sortKey: 'started_at', render: (r) => formatDate(r.started_at) },
    { key: 'rows_read', label: 'Read', className: 'num', render: (r) => formatInt(r.rows_read) },
    { key: 'rows_loaded', label: 'Loaded', className: 'num', render: (r) => formatInt(r.rows_loaded) },
    { key: 'rows_rejected', label: 'Rejected', className: 'num', render: (r) => formatInt(r.rows_rejected) },
    { key: 'rows_skipped_existing', label: 'Skipped', className: 'num', render: (r) => formatInt(r.rows_skipped_existing) },
    { key: 'ratio', label: 'Reject ratio', className: 'num', render: (r) => formatPercent(rejectRatio(r), 2) },
    { key: 'dq', label: 'Quality', render: (r) => <Link to={`/data-quality?run_id=${r.run_id}`} onClick={(e) => e.stopPropagation()}>Issues</Link> },
  ]
  return (
    <div>
      <h1>Pipeline runs</h1>
      <p className="muted-text">Each row is one file processed by the ETL. Read = loaded + rejected + skipped, always.</p>
      <FilterForm fields={fields} values={list.filters} onApply={list.setFilters} label="Pipeline filters" />
      <DataTable columns={columns} rows={page?.items} loading={list.loading} error={list.error} onRetry={list.reload}
                 sortBy={list.sortBy} sortDir={list.sortDir} onSort={list.onSort} rowKey={(r) => r.run_id} />
      {page && <Pagination page={page.page} pages={page.pages} total={page.total} pageSize={page.page_size} onPage={list.setPage} />}
    </div>
  )
}

export function DataQuality() {
  const list = useListPage('/admin/dq-issues', { defaultSort: 'issue_id', defaultDir: 'asc' })
  const fields = [
    { name: 'run_id', label: 'Run', type: 'number', min: 1 }, { name: 'rule_name', label: 'Rule', type: 'text', placeholder: 'DQ03' },
    { name: 'severity', label: 'Severity', type: 'select', options: ['error', 'warning', 'info'].map((s) => ({ value: s, label: s })) },
  ]
  const page = list.data
  const columns = [
    { key: 'issue_id', label: 'Issue', sortKey: 'issue_id' }, { key: 'run_id', label: 'Run' },
    { key: 'rule_name', label: 'Rule', sortKey: 'rule_name' },
    { key: 'severity', label: 'Severity', render: (r) => <Badge className={`badge ${r.severity === 'error' ? 'bad' : r.severity === 'warning' ? 'warn' : 'muted'}`}>{r.severity}</Badge> },
    { key: 'action', label: 'Action' }, { key: 'encounter_id', label: 'Encounter', render: (r) => r.encounter_id ?? '-' },
    { key: 'column_name', label: 'Column', render: (r) => r.column_name || '-' }, { key: 'bad_value', label: 'Value', render: (r) => r.bad_value ?? '-' },
  ]
  return (
    <div>
      <h1>Data quality</h1>
      <p className="muted-text">Row-level findings from each load. “rejected” rows were quarantined, “corrected” values were set to empty, “flagged” rows were kept, “metric” rows count missing values.</p>
      <FilterForm fields={fields} values={list.filters} onApply={list.setFilters} label="Data-quality filters" />
      <DataTable columns={columns} rows={page?.items} loading={list.loading} error={list.error} onRetry={list.reload}
                 sortBy={list.sortBy} sortDir={list.sortDir} onSort={list.onSort} rowKey={(r) => r.issue_id} />
      {page && <Pagination page={page.page} pages={page.pages} total={page.total} pageSize={page.page_size} onPage={list.setPage} />}
    </div>
  )
}

function UserForm({ onClose, onSaved }) {
  const toast = useToast()
  const [v, setV] = useState({ username: '', password: '', role: 'analyst' })
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setV((x) => ({ ...x, [k]: e.target.value }))
  const submit = async (e) => {
    e.preventDefault()
    const problems = {}
    if (!/^[A-Za-z0-9_.-]{3,50}$/.test(v.username)) problems.username = '3 to 50 letters, digits, dot, dash or underscore.'
    if (v.password.length < 12) problems.password = 'At least 12 characters.'
    setErrors(problems)
    if (Object.keys(problems).length) return
    setBusy(true)
    try {
      await api.post('/admin/users', v)
      toast.success(`User ${v.username} created.`)
      onSaved()
    } catch (err) {
      const fields = toFieldErrors(err)
      setErrors(fields)
      if (!Object.keys(fields).length) toast.error(toErrorMessage(err))
    } finally { setBusy(false) }
  }
  return (
    <Modal title="New user" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <div className={`field${errors.username ? ' has-error' : ''}`}><label htmlFor="u-name">Username</label>
          <input id="u-name" value={v.username} onChange={set('username')} autoComplete="off" />{errors.username && <span className="field-error" role="alert">{errors.username}</span>}</div>
        <div className={`field${errors.password ? ' has-error' : ''}`}><label htmlFor="u-pass">Password</label>
          <input id="u-pass" type="password" value={v.password} onChange={set('password')} autoComplete="new-password" />{errors.password && <span className="field-error" role="alert">{errors.password}</span>}</div>
        <div className="field"><label htmlFor="u-role">Role</label>
          <select id="u-role" value={v.role} onChange={set('role')}><option value="analyst">Analyst</option><option value="clinical_ops">Clinical operations</option><option value="administrator">Administrator</option></select></div>
        <div className="actions"><button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button><button type="submit" className="btn primary" disabled={busy}>Create user</button></div>
      </form>
    </Modal>
  )
}

export function Users() {
  const list = useListPage('/admin/users', { defaultSort: 'user_id', defaultDir: 'asc' })
  const [adding, setAdding] = useState(false)
  const page = list.data
  const columns = [
    { key: 'user_id', label: 'ID', sortKey: 'user_id' }, { key: 'username', label: 'Username', sortKey: 'username' }, { key: 'role', label: 'Role' },
    { key: 'is_active', label: 'Active', render: (r) => (r.is_active ? 'yes' : 'no') }, { key: 'last_login_at', label: 'Last login', render: (r) => formatDate(r.last_login_at) },
  ]
  return (
    <div>
      <div className="page-head"><h1>Users</h1><button type="button" className="btn primary" onClick={() => setAdding(true)}>New user</button></div>
      <DataTable columns={columns} rows={page?.items} loading={list.loading} error={list.error} onRetry={list.reload}
                 sortBy={list.sortBy} sortDir={list.sortDir} onSort={list.onSort} rowKey={(r) => r.user_id} />
      {page && <Pagination page={page.page} pages={page.pages} total={page.total} pageSize={page.page_size} onPage={list.setPage} />}
      {adding && <UserForm onClose={() => setAdding(false)} onSaved={() => { setAdding(false); list.reload() }} />}
    </div>
  )
}
