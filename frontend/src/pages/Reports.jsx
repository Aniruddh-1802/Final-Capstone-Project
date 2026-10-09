import { useState } from 'react'
import { downloadFile, normaliseBlobError, toErrorMessage } from '../api/client'
import { DataTable, Pagination } from '../components/DataTable'
import { SimulatedDatesBanner } from '../components/states'
import { useToast } from '../components/Toast'
import { useAuth } from '../context/AuthContext'
import { useApi } from '../hooks/useApi'
import { useListPage } from '../hooks/useListPage'
import { formatDate, formatInt } from '../lib/format'
import { ROLES } from '../lib/roles'

const REPORTS = [
  { value: 'readmission_summary', label: 'Readmission summary (by age, type, source, disposition, specialty, month)' },
  { value: 'admissions_trend', label: 'Admissions trend (monthly and yearly)' },
  { value: 'length_of_stay_summary', label: 'Length-of-stay summary (with histogram)' },
  { value: 'encounters', label: 'Encounter-level data (administrator and clinical operations only; max 50,000 rows)', restricted: true },
]

function History() {
  const list = useListPage('/reports/history', { defaultSort: 'generated_at', defaultDir: 'desc', pageSize: 10 })
  const page = list.data
  return (
    <section className="card" aria-label="Report history">
      <h2>Report history</h2>
      <DataTable columns={[
        { key: 'generated_at', label: 'Generated', sortKey: 'generated_at', render: (r) => formatDate(r.generated_at) },
        { key: 'report_type', label: 'Report' }, { key: 'file_path', label: 'File' },
        { key: 'row_count', label: 'Rows', className: 'num', render: (r) => formatInt(r.row_count) }, { key: 'triggered_by', label: 'By' }]}
                 rows={page?.items} loading={list.loading} error={list.error} onRetry={list.reload}
                 sortBy={list.sortBy} sortDir={list.sortDir} onSort={list.onSort} rowKey={(r) => r.report_id} />
      {page && <Pagination page={page.page} pages={page.pages} total={page.total} pageSize={page.page_size} onPage={list.setPage} />}
    </section>
  )
}

export default function Reports() {
  const { hasRole } = useAuth()
  const toast = useToast()
  const staff = hasRole(ROLES.ADMIN, ROLES.OPS)
  const ages = useApi('/reference/age-groups')
  const types = useApi('/reference/admission-types')
  const [form, setForm] = useState({ report: 'readmission_summary', format: 'xlsx', date_from: '', date_to: '', age_group: '', admission_type_id: '' })
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [historyKey, setHistoryKey] = useState(0)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const download = async (e) => {
    e.preventDefault()
    setBusy(true); setMessage(null)
    try {
      const result = await downloadFile('/reports/export', form)
      setMessage({ ok: true, text: `Downloaded ${result.filename} (${formatInt(result.rows)} rows, ${formatInt(Math.round(result.size / 1024))} KB).` })
      toast.success(`Downloaded ${result.filename}`)
      setHistoryKey((k) => k + 1)
    } catch (err) {
      const text = toErrorMessage(await normaliseBlobError(err))
      setMessage({ ok: false, text }); toast.error(text)
    } finally { setBusy(false) }
  }

  return (
    <div>
      <h1>Reports</h1>
      <SimulatedDatesBanner />
      <form className="card report-form" onSubmit={download} aria-label="Report options">
        <label>Report
          <select value={form.report} onChange={set('report')}>
            {REPORTS.filter((r) => !r.restricted || staff).map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </label>
        <label>Format
          <select value={form.format} onChange={set('format')}><option value="xlsx">Excel (.xlsx)</option><option value="csv">CSV</option></select>
        </label>
        <label>From<input type="date" value={form.date_from} onChange={set('date_from')} /></label>
        <label>To<input type="date" value={form.date_to} onChange={set('date_to')} /></label>
        <label>Age group
          <select value={form.age_group} onChange={set('age_group')}><option value="">All ages</option>{(ages.data || []).map((a) => <option key={a.id}>{a.label}</option>)}</select>
        </label>
        <label>Admission type
          <select value={form.admission_type_id} onChange={set('admission_type_id')}><option value="">All types</option>{(types.data || []).map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}</select>
        </label>
        <button type="submit" className="btn primary" disabled={busy}>{busy ? 'Preparing…' : 'Download'}</button>
        {message && <p className={message.ok ? 'ok-text' : 'field-error'} role={message.ok ? 'status' : 'alert'}>{message.text}</p>}
        <p className="hint">Files never contain race or gender. Excel workbooks include a Metadata sheet with the filters, the denominator and the simulated-dates note.</p>
      </form>
      {staff && <History key={historyKey} />}
    </div>
  )
}
