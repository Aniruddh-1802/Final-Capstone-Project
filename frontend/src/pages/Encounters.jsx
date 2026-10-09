import { useState } from 'react'
import { api, toErrorMessage } from '../api/client'
import { ConfirmDialog, Modal } from '../components/Modal'
import EncounterForm from '../components/EncounterForm'
import { DataTable, Pagination } from '../components/DataTable'
import { FilterForm } from '../components/FilterForm'
import { Badge, SimulatedDatesBanner } from '../components/states'
import { useToast } from '../components/Toast'
import { useAuth } from '../context/AuthContext'
import { useApi } from '../hooks/useApi'
import { useListPage } from '../hooks/useListPage'
import { formatDate } from '../lib/format'
import { ROLES } from '../lib/roles'

function Detail({ id, onClose, onEdit, onDelete, canWrite, canDelete }) {
  const { data, loading, error, reload } = useApi(`/encounters/${id}`)
  return (
    <Modal title={`Encounter ${id}`} onClose={onClose} wide>
      {loading && !data && <p>Loading…</p>}
      {error && <p className="field-error" role="alert">{toErrorMessage(error)} <button type="button" className="link" onClick={reload}>Retry</button></p>}
      {data && (
        <>
          <dl className="facts">
            {data.patient_nbr !== undefined && <><dt>Patient</dt><dd data-testid="detail-patient">{data.patient_nbr}</dd></>}
            <dt>Admitted (simulated)</dt><dd>{formatDate(data.admission_date)}</dd>
            <dt>Discharged (simulated)</dt><dd>{formatDate(data.discharge_date)}</dd>
            <dt>Age group</dt><dd>{data.age_group}</dd>
            <dt>Length of stay</dt><dd>{data.time_in_hospital} days</dd>
            <dt>Admission type</dt><dd>{data.admission_type}</dd>
            <dt>Admission source</dt><dd>{data.admission_source}</dd>
            <dt>Discharge</dt><dd>{data.discharge_disposition}</dd>
            <dt>Specialty</dt><dd>{data.medical_specialty || 'not recorded'}</dd>
            <dt>Readmitted</dt><dd>{data.readmitted} {data.readmitted_30d && <Badge className="badge warn">within 30 days</Badge>}</dd>
            <dt>Counts in readmission rate</dt><dd>{data.is_readmission_eligible ? 'yes' : 'no (expired or hospice discharge)'}</dd>
            <dt>Diagnoses</dt><dd>{data.diagnoses.map((d) => `${d.position}: ${d.icd9_code}`).join('  ·  ') || 'none'}</dd>
            <dt>Medications</dt><dd>{data.medications.map((m) => `${m.drug_name.replace(/_/g, ' ')} (${m.dosage_status})`).join(', ') || 'none prescribed'}</dd>
          </dl>
          <div className="actions">
            {canWrite && <button type="button" className="btn primary" onClick={() => onEdit(data)}>Edit</button>}
            {canDelete && <button type="button" className="btn danger" onClick={() => onDelete(data)}>Delete</button>}
          </div>
        </>
      )}
    </Modal>
  )
}

export default function Encounters() {
  const { hasRole } = useAuth()
  const toast = useToast()
  const canWrite = hasRole(ROLES.ADMIN, ROLES.OPS)
  const canDelete = hasRole(ROLES.ADMIN)
  const isAnalyst = hasRole(ROLES.ANALYST)
  const list = useListPage('/encounters', { defaultSort: 'admission_date', defaultDir: 'desc' })
  const ages = useApi('/reference/age-groups')
  const types = useApi('/reference/admission-types')
  const [selected, setSelected] = useState(null)
  const [form, setForm] = useState(null)       // {encounter?} -> create when encounter is undefined
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(false)

  const fields = [
    { name: 'date_from', label: 'From', type: 'date' }, { name: 'date_to', label: 'To', type: 'date' },
    { name: 'age_group', label: 'Age group', type: 'select', any: 'All ages', options: (ages.data || []).map((a) => ({ value: a.label, label: a.label })) },
    { name: 'admission_type_id', label: 'Admission type', type: 'select', any: 'All types', options: (types.data || []).map((t) => ({ value: t.id, label: t.label })) },
    { name: 'readmitted', label: 'Readmitted', type: 'select', any: 'Any', options: [{ value: 'NO', label: 'No' }, { value: '>30', label: 'After 30 days' }, { value: '<30', label: 'Within 30 days' }] },
    { name: 'min_los', label: 'Min days', type: 'number', min: 1, max: 14 }, { name: 'max_los', label: 'Max days', type: 'number', min: 1, max: 14 },
    ...(isAnalyst ? [] : [{ name: 'patient_nbr', label: 'Patient number', type: 'number', min: 1 }]),
    { name: 'q', label: 'Search', type: 'text', placeholder: 'id, or ICD-9 prefix e.g. V57' },
  ]
  const columns = [
    { key: 'encounter_id', label: 'Encounter', sortKey: 'encounter_id' },
    ...(isAnalyst ? [] : [{ key: 'patient_nbr', label: 'Patient' }]),
    { key: 'admission_date', label: 'Admitted (simulated)', sortKey: 'admission_date', render: (r) => formatDate(r.admission_date) },
    { key: 'age_group', label: 'Age', sortKey: 'age_order' },
    { key: 'admission_type', label: 'Admission type' },
    { key: 'time_in_hospital', label: 'Days', sortKey: 'time_in_hospital', className: 'num' },
    { key: 'num_medications', label: 'Meds', sortKey: 'num_medications', className: 'num' },
    { key: 'readmitted', label: 'Readmitted', render: (r) => (r.readmitted_30d ? <Badge className="badge warn">{'<30'}</Badge> : r.readmitted) },
  ]

  const remove = async () => {
    setBusy(true)
    try {
      await api.delete(`/encounters/${confirm.encounter_id}`)
      toast.success(`Encounter ${confirm.encounter_id} deleted.`)
      setConfirm(null); setSelected(null); list.reload()
    } catch (err) {
      toast.error(toErrorMessage(err))
    } finally { setBusy(false) }
  }

  const page = list.data
  return (
    <div>
      <div className="page-head">
        <h1>Encounters</h1>
        {canWrite && <button type="button" className="btn primary" onClick={() => setForm({})}>New encounter</button>}
      </div>
      <SimulatedDatesBanner />
      {isAnalyst && <p className="muted-text">Analyst view: read-only, and patient numbers are not shown.</p>}
      <FilterForm fields={fields} values={list.filters} onApply={list.setFilters} label="Encounter filters" />
      <DataTable columns={columns} rows={page?.items} loading={list.loading} error={list.error} onRetry={list.reload}
                 sortBy={list.sortBy} sortDir={list.sortDir} onSort={list.onSort} rowKey={(r) => r.encounter_id}
                 onRowClick={(r) => setSelected(r.encounter_id)} />
      {page && <Pagination page={page.page} pages={page.pages} total={page.total} pageSize={page.page_size} onPage={list.setPage} />}
      {selected && !form && !confirm && (
        <Detail id={selected} onClose={() => setSelected(null)} canWrite={canWrite} canDelete={canDelete}
                onEdit={(enc) => setForm({ encounter: enc })} onDelete={(enc) => setConfirm(enc)} />
      )}
      {form && <EncounterForm encounter={form.encounter} onClose={() => setForm(null)} onSaved={() => { setForm(null); setSelected(null); list.reload() }} />}
      {confirm && (
        <ConfirmDialog title="Delete encounter?" busy={busy} onConfirm={remove} onCancel={() => setConfirm(null)}>
          <p>Encounter <strong>{confirm.encounter_id}</strong> ({confirm.age_group}, {confirm.time_in_hospital} days) will be removed from every list, chart and export.
            It is a soft delete: the record is kept for the audit trail.</p>
        </ConfirmDialog>
      )}
    </div>
  )
}
