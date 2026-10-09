import { useState } from 'react'
import { api, toErrorMessage, toFieldErrors } from '../api/client'
import { useApi } from '../hooks/useApi'
import {
  A1C, COUNT_FIELDS, DOSAGES, DRUGS, GLUCOSE, LABELS, READMITTED, emptyEncounter, fromEncounter, toPayload, validateEncounter,
} from '../lib/encounterSchema'
import { Modal } from './Modal'
import { useToast } from './Toast'

function Field({ name, errors, children, label = LABELS[name], hint }) {
  const id = `f-${name.replace(/\./g, '-')}`
  const error = errors[name]
  return (
    <div className={`field${error ? ' has-error' : ''}`}>
      <label htmlFor={id}>{label}</label>
      {children(id, error)}
      {hint && !error && <span className="hint">{hint}</span>}
      {error && <span className="field-error" id={`${id}-error`} role="alert">{error}</span>}
    </div>
  )
}

export default function EncounterForm({ encounter, onSaved, onClose }) {
  const creating = !encounter
  const toast = useToast()
  const [values, setValues] = useState(encounter ? fromEncounter(encounter) : emptyEncounter())
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const ages = useApi('/reference/age-groups')
  const types = useApi('/reference/admission-types')
  const sources = useApi('/reference/admission-sources')
  const dispositions = useApi('/reference/discharge-dispositions')
  const specialties = useApi('/reference/specialties')

  const set = (name, value) => setValues((v) => ({ ...v, [name]: value }))
  const input = (name, type = 'text', extra = {}) => (id, error) => (
    <input id={id} name={name} type={type} value={values[name] ?? ''} onChange={(e) => set(name, e.target.value)}
           aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined} {...extra} />
  )
  const select = (name, options, any = 'Choose…') => (id, error) => (
    <select id={id} name={name} value={values[name] ?? ''} onChange={(e) => set(name, e.target.value)} aria-invalid={Boolean(error)}>
      <option value="">{any}</option>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
  const refOptions = (state) => (state.data || []).map((r) => ({ value: r.id, label: r.label }))

  const submit = async (e) => {
    e.preventDefault()
    const problems = validateEncounter(values, creating)
    setErrors(problems)
    setFormError('')
    if (Object.keys(problems).length) { setFormError('Please fix the highlighted fields.'); return }
    setBusy(true)
    try {
      const body = toPayload(values, creating)
      const { data } = creating ? await api.post('/encounters', body) : await api.put(`/encounters/${encounter.encounter_id}`, body)
      toast.success(creating ? `Encounter ${data.encounter_id} created.` : `Encounter ${data.encounter_id} updated.`)
      onSaved(data)
    } catch (err) {
      const fields = toFieldErrors(err)
      setErrors(fields)  // server-side 422 field errors land on the same fields
      setFormError(Object.keys(fields).length ? 'The server rejected some fields.' : toErrorMessage(err))
      if (!Object.keys(fields).length) toast.error(toErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const setDiagnosis = (i, code) => set('diagnoses', values.diagnoses.map((d, j) => (j === i ? { ...d, icd9_code: code } : d)))
  const setMedication = (i, patch) => set('medications', values.medications.map((m, j) => (j === i ? { ...m, ...patch } : m)))

  return (
    <Modal title={creating ? 'New encounter' : `Edit encounter ${encounter.encounter_id}`} onClose={onClose} wide>
      <form onSubmit={submit} noValidate className="enc-form">
        {formError && <p className="field-error form-error" role="alert">{formError}</p>}
        <fieldset disabled={busy}>
          <legend>Identity</legend>
          {creating && <>
            <Field name="encounter_id" errors={errors}>{input('encounter_id', 'number', { min: 1 })}</Field>
            <Field name="patient_nbr" errors={errors} hint="The patient must already exist.">{input('patient_nbr', 'number', { min: 1 })}</Field>
          </>}
          <Field name="age_group" errors={errors}>{select('age_group', refOptions(ages).map((o) => ({ value: o.label, label: o.label })))}</Field>
        </fieldset>
        <fieldset disabled={busy}>
          <legend>Stay (dates are simulated)</legend>
          <Field name="admission_date" errors={errors}>{input('admission_date', 'date')}</Field>
          <Field name="discharge_date" errors={errors}>{input('discharge_date', 'date')}</Field>
          <Field name="time_in_hospital" errors={errors} hint="1 to 14 days; must match the two dates.">{input('time_in_hospital', 'number', { min: 1, max: 14 })}</Field>
        </fieldset>
        <fieldset disabled={busy}>
          <legend>Categories</legend>
          <Field name="admission_type_id" errors={errors}>{select('admission_type_id', refOptions(types))}</Field>
          <Field name="admission_source_id" errors={errors}>{select('admission_source_id', refOptions(sources))}</Field>
          <Field name="discharge_disposition_id" errors={errors}>{select('discharge_disposition_id', refOptions(dispositions))}</Field>
          <Field name="medical_specialty" errors={errors} hint="Optional; leave empty if unknown.">{input('medical_specialty', 'text', { list: 'specialty-list', maxLength: 80 })}</Field>
          <datalist id="specialty-list">{(specialties.data || []).map((s) => <option key={s.id} value={s.label} />)}</datalist>
          <Field name="payer_code" errors={errors}>{input('payer_code', 'text', { maxLength: 10 })}</Field>
        </fieldset>
        <fieldset disabled={busy}>
          <legend>Counts</legend>
          {COUNT_FIELDS.filter((n) => n !== 'time_in_hospital').map((n) => <Field key={n} name={n} errors={errors}>{input(n, 'number', { min: 0 })}</Field>)}
        </fieldset>
        <fieldset disabled={busy}>
          <legend>Clinical</legend>
          <Field name="max_glu_serum" errors={errors}>{select('max_glu_serum', GLUCOSE.map((g) => ({ value: g, label: g })), 'Choose…')}</Field>
          <Field name="a1c_result" errors={errors}>{select('a1c_result', A1C.map((g) => ({ value: g, label: g })))}</Field>
          <Field name="readmitted" errors={errors} hint="The 30-day flag and eligibility are worked out by the server.">{select('readmitted', READMITTED)}</Field>
          <div className="field check"><label><input type="checkbox" checked={Boolean(values.med_changed)} onChange={(e) => set('med_changed', e.target.checked)} /> {LABELS.med_changed}</label></div>
          <div className="field check"><label><input type="checkbox" checked={Boolean(values.diabetes_med)} onChange={(e) => set('diabetes_med', e.target.checked)} /> {LABELS.diabetes_med}</label></div>
          {!creating && (
            <div className="derived" aria-label="Derived by the server (read-only)">
              <span>Within 30 days: <strong data-testid="derived-30d">{encounter.readmitted_30d ? 'yes' : 'no'}</strong></span>
              <span>Eligible for readmission rate: <strong data-testid="derived-eligible">{encounter.is_readmission_eligible ? 'yes' : 'no'}</strong></span>
            </div>
          )}
        </fieldset>
        <fieldset disabled={busy}>
          <legend>Diagnoses (ICD-9, up to 3)</legend>
          {errors.diagnoses && <p className="field-error" role="alert">{errors.diagnoses}</p>}
          {values.diagnoses.map((d, i) => (
            <div className="row" key={i}>
              <span className="pos">#{i + 1}{i === 0 ? ' primary' : ''}</span>
              <Field name={`diagnoses.${i}.icd9_code`} errors={errors} label={`Diagnosis ${i + 1}`}>{(id, error) => <input id={id} value={d.icd9_code} onChange={(e) => setDiagnosis(i, e.target.value)} aria-invalid={Boolean(error)} />}</Field>
              <button type="button" className="btn small" onClick={() => set('diagnoses', values.diagnoses.filter((_, j) => j !== i).map((x, j) => ({ ...x, position: j + 1 })))}>Remove</button>
            </div>
          ))}
          {values.diagnoses.length < 3 && <button type="button" className="btn small" onClick={() => set('diagnoses', [...values.diagnoses, { position: values.diagnoses.length + 1, icd9_code: '' }])}>Add diagnosis</button>}
        </fieldset>
        <fieldset disabled={busy}>
          <legend>Medications prescribed</legend>
          {errors.medications && <p className="field-error" role="alert">{errors.medications}</p>}
          {values.medications.map((m, i) => (
            <div className="row" key={i}>
              <Field name={`medications.${i}.drug_name`} errors={errors} label={`Drug ${i + 1}`}>{(id) => (
                <select id={id} value={m.drug_name} onChange={(e) => setMedication(i, { drug_name: e.target.value })}>{DRUGS.map((d) => <option key={d} value={d}>{d.replace(/_/g, ' ')}</option>)}</select>)}</Field>
              <Field name={`medications.${i}.dosage_status`} errors={errors} label="Dosage">{(id) => (
                <select id={id} value={m.dosage_status} onChange={(e) => setMedication(i, { dosage_status: e.target.value })}>{DOSAGES.map((d) => <option key={d}>{d}</option>)}</select>)}</Field>
              <button type="button" className="btn small" onClick={() => set('medications', values.medications.filter((_, j) => j !== i))}>Remove</button>
            </div>
          ))}
          <button type="button" className="btn small" onClick={() => set('medications', [...values.medications, { drug_name: DRUGS.find((d) => !values.medications.some((m) => m.drug_name === d)) || DRUGS[0], dosage_status: 'Steady' }])}>Add medication</button>
        </fieldset>
        <div className="actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn primary" disabled={busy}>{busy ? 'Saving…' : creating ? 'Create encounter' : 'Save changes'}</button>
        </div>
      </form>
    </Modal>
  )
}
