import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, toErrorMessage, toFieldErrors } from '../api/client'
import { DataTable, Pagination } from '../components/DataTable'
import { FilterForm } from '../components/FilterForm'
import { ConfirmDialog, Modal } from '../components/Modal'
import { ErrorState, Loading, SimulatedDatesBanner } from '../components/states'
import { useToast } from '../components/Toast'
import { useAuth } from '../context/AuthContext'
import { useApi } from '../hooks/useApi'
import { useListPage } from '../hooks/useListPage'
import { formatDate } from '../lib/format'
import { ROLES } from '../lib/roles'

function PatientForm({ patient, onClose, onSaved }) {
  const creating = !patient
  const toast = useToast()
  const [values, setValues] = useState({ patient_nbr: patient?.patient_nbr ?? '', race: patient?.race ?? '', gender: patient?.gender ?? '' })
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setValues((v) => ({ ...v, [k]: e.target.value }))
  const submit = async (e) => {
    e.preventDefault()
    const problems = {}
    if (creating && !(Number.isInteger(Number(values.patient_nbr)) && Number(values.patient_nbr) > 0)) problems.patient_nbr = 'Enter a positive whole number.'
    if (values.race.length > 30) problems.race = 'At most 30 characters.'
    setErrors(problems)
    if (Object.keys(problems).length) return
    setBusy(true)
    try {
      const body = { race: values.race.trim() || null, gender: values.gender || null }
      const { data } = creating ? await api.post('/patients', { ...body, patient_nbr: Number(values.patient_nbr) }) : await api.put(`/patients/${patient.patient_nbr}`, body)
      toast.success(creating ? `Patient ${data.patient_nbr} created.` : `Patient ${data.patient_nbr} updated.`)
      onSaved(data)
    } catch (err) {
      const fields = toFieldErrors(err)
      setErrors(fields)
      if (!Object.keys(fields).length) toast.error(toErrorMessage(err))
    } finally { setBusy(false) }
  }
  return (
    <Modal title={creating ? 'New patient' : `Edit patient ${patient.patient_nbr}`} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {creating && (
          <div className={`field${errors.patient_nbr ? ' has-error' : ''}`}>
            <label htmlFor="p-nbr">Patient number</label>
            <input id="p-nbr" type="number" min="1" value={values.patient_nbr} onChange={set('patient_nbr')} aria-invalid={Boolean(errors.patient_nbr)} />
            {errors.patient_nbr && <span className="field-error" role="alert">{errors.patient_nbr}</span>}
          </div>
        )}
        <div className={`field${errors.race ? ' has-error' : ''}`}>
          <label htmlFor="p-race">Race</label>
          <input id="p-race" value={values.race} onChange={set('race')} maxLength={30} />
          {errors.race && <span className="field-error" role="alert">{errors.race}</span>}
        </div>
        <div className={`field${errors.gender ? ' has-error' : ''}`}>
          <label htmlFor="p-gender">Gender</label>
          <select id="p-gender" value={values.gender} onChange={set('gender')}>
            <option value="">Not recorded</option><option>Female</option><option>Male</option><option>Unknown</option>
          </select>
          {errors.gender && <span className="field-error" role="alert">{errors.gender}</span>}
        </div>
        <p className="hint">Race and gender are sensitive: they are shown only on these pages, never in charts or exports.</p>
        <div className="actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Modal>
  )
}

export default function Patients() {
  const { hasRole } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const list = useListPage('/patients', { defaultSort: 'patient_nbr', defaultDir: 'asc' })
  const [form, setForm] = useState(null)
  const canWrite = hasRole(ROLES.ADMIN, ROLES.OPS)
  const fields = [
    { name: 'q', label: 'Patient number', type: 'number', min: 1, placeholder: 'exact number' },
    { name: 'has_multiple_encounters', label: 'Encounters', type: 'select', any: 'Any number', options: [{ value: 'true', label: 'More than one' }, { value: 'false', label: 'One or none' }] },
  ]
  const columns = [
    { key: 'patient_nbr', label: 'Patient', sortKey: 'patient_nbr' },
    { key: 'gender', label: 'Gender', render: (r) => r.gender || '-' },
    { key: 'race', label: 'Race', render: (r) => r.race || '-' },
    { key: 'encounter_count', label: 'Encounters', className: 'num' },
    { key: 'created_at', label: 'Added', sortKey: 'created_at', render: (r) => formatDate(r.created_at) },
  ]
  const page = list.data
  return (
    <div>
      <div className="page-head">
        <h1>Patients</h1>
        {canWrite && <button type="button" className="btn primary" onClick={() => setForm({})}>New patient</button>}
      </div>
      <FilterForm fields={fields} values={list.filters} onApply={list.setFilters} label="Patient filters" />
      <DataTable columns={columns} rows={page?.items} loading={list.loading} error={list.error} onRetry={list.reload}
                 sortBy={list.sortBy} sortDir={list.sortDir} onSort={list.onSort} rowKey={(r) => r.patient_nbr}
                 onRowClick={(r) => navigate(`/patients/${r.patient_nbr}`)} />
      {page && <Pagination page={page.page} pages={page.pages} total={page.total} pageSize={page.page_size} onPage={list.setPage} />}
      {form && <PatientForm onClose={() => setForm(null)} onSaved={(p) => { setForm(null); toast.success(`Opening patient ${p.patient_nbr}`); navigate(`/patients/${p.patient_nbr}`) }} />}
    </div>
  )
}

export function PatientDetail() {
  const { id } = useParams()
  const { hasRole } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const patient = useApi(`/patients/${id}`)
  const [tab, setTab] = useState('profile')
  const [editing, setEditing] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const encounters = useListPage(`/patients/${id}/encounters`, { defaultSort: 'admission_date', defaultDir: 'desc', pageSize: 10 })

  const remove = async () => {
    setBusy(true)
    try {
      await api.delete(`/patients/${id}`)
      toast.success(`Patient ${id} deleted.`)
      navigate('/patients', { replace: true })
    } catch (err) { toast.error(toErrorMessage(err)); setBusy(false) }
  }
  if (patient.loading && !patient.data) return <Loading />
  if (patient.error) return <ErrorState error={patient.error} onRetry={patient.reload} />
  const p = patient.data
  const page = encounters.data
  return (
    <div>
      <div className="page-head">
        <h1>Patient {p.patient_nbr}</h1>
        <div>
          {hasRole(ROLES.ADMIN, ROLES.OPS) && <button type="button" className="btn" onClick={() => setEditing(true)}>Edit</button>}
          {hasRole(ROLES.ADMIN) && <button type="button" className="btn danger" onClick={() => setConfirm(true)}>Delete</button>}
        </div>
      </div>
      <div className="tabs" role="tablist">
        {['profile', 'encounters'].map((t) => <button key={t} role="tab" type="button" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t === 'profile' ? 'Profile' : 'Encounters'}</button>)}
      </div>
      {tab === 'profile' && (
        <dl className="facts card">
          <dt>Patient number</dt><dd>{p.patient_nbr}</dd><dt>Gender</dt><dd>{p.gender || 'not recorded'}</dd>
          <dt>Race</dt><dd>{p.race || 'not recorded'}</dd><dt>Added</dt><dd>{formatDate(p.created_at)}</dd><dt>Last updated</dt><dd>{formatDate(p.updated_at)}</dd>
        </dl>
      )}
      {tab === 'encounters' && (
        <>
          <SimulatedDatesBanner />
          <DataTable columns={[
            { key: 'encounter_id', label: 'Encounter', sortKey: 'encounter_id' }, { key: 'admission_date', label: 'Admitted (simulated)', sortKey: 'admission_date', render: (r) => formatDate(r.admission_date) },
            { key: 'time_in_hospital', label: 'Days', sortKey: 'time_in_hospital' }, { key: 'readmitted', label: 'Readmitted' }]}
                     rows={page?.items} loading={encounters.loading} error={encounters.error} onRetry={encounters.reload}
                     sortBy={encounters.sortBy} sortDir={encounters.sortDir} onSort={encounters.onSort} rowKey={(r) => r.encounter_id}
                     onRowClick={(r) => navigate(`/encounters?q=${r.encounter_id}`)} />
          {page && <Pagination page={page.page} pages={page.pages} total={page.total} pageSize={page.page_size} onPage={encounters.setPage} />}
        </>
      )}
      {editing && <PatientForm patient={p} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); patient.reload() }} />}
      {confirm && (
        <ConfirmDialog title="Delete patient?" busy={busy} onConfirm={remove} onCancel={() => setConfirm(false)}>
          <p>Patient <strong>{p.patient_nbr}</strong> and all of their encounters will disappear from lists, charts and exports. The records are kept for the audit trail.</p>
        </ConfirmDialog>
      )}
    </div>
  )
}
