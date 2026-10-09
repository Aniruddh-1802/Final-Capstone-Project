// Client-side validation that MIRRORS the API rules (src/app/schemas/encounters.py, etl/quality.py). The server is still
// the authority: any rule missed here comes back as a 422 and is shown against the right field.
export const CAPS = {
  time_in_hospital: [1, 14], num_lab_procedures: [0, 250], num_procedures: [0, 20], num_medications: [0, 150],
  number_outpatient: [0, 100], number_emergency: [0, 150], number_inpatient: [0, 50], number_diagnoses: [0, 30],
}
export const COUNT_FIELDS = Object.keys(CAPS)
export const LABELS = {
  encounter_id: 'Encounter ID', patient_nbr: 'Patient number', admission_date: 'Admission date', discharge_date: 'Discharge date',
  age_group: 'Age group', admission_type_id: 'Admission type', discharge_disposition_id: 'Discharge disposition',
  admission_source_id: 'Admission source', medical_specialty: 'Medical specialty', payer_code: 'Payer code',
  time_in_hospital: 'Length of stay (days)', num_lab_procedures: 'Lab procedures', num_procedures: 'Procedures',
  num_medications: 'Medications', number_outpatient: 'Outpatient visits', number_emergency: 'Emergency visits',
  number_inpatient: 'Prior inpatient visits', number_diagnoses: 'Diagnoses', max_glu_serum: 'Max glucose serum', a1c_result: 'A1C result',
  med_changed: 'Medication changed', diabetes_med: 'On diabetes medication', readmitted: 'Readmitted',
}
export const GLUCOSE = ['None', 'Norm', '>200', '>300']
export const A1C = ['None', 'Norm', '>7', '>8']
export const READMITTED = [{ value: 'NO', label: 'No' }, { value: '>30', label: 'After more than 30 days' }, { value: '<30', label: 'Within 30 days' }]
export const DOSAGES = ['Steady', 'Up', 'Down']
// The 21 drugs the system stores (etl.transform.MEDICATION_COLUMNS); the API rejects any other name.
export const DRUGS = [
  'metformin', 'repaglinide', 'nateglinide', 'chlorpropamide', 'glimepiride', 'acetohexamide', 'glipizide', 'glyburide', 'tolbutamide',
  'pioglitazone', 'rosiglitazone', 'acarbose', 'miglitol', 'troglitazone', 'tolazamide', 'insulin', 'glyburide_metformin',
  'glipizide_metformin', 'glimepiride_pioglitazone', 'metformin_rosiglitazone', 'metformin_pioglitazone',
]
const ICD9 = /^(?:\d{1,3}(?:\.\d{1,2})?|V\d{1,2}(?:\.\d{1,2})?|E\d{3}(?:\.\d{1,2})?)$/
const WINDOW_START = '1999-01-01'
const WINDOW_END = '2008-12-31'

export const daysBetween = (a, b) => Math.round((new Date(`${b}T00:00:00Z`) - new Date(`${a}T00:00:00Z`)) / 86400000)

export function emptyEncounter() {
  return {
    encounter_id: '', patient_nbr: '', admission_date: '', discharge_date: '', age_group: '', admission_type_id: '',
    discharge_disposition_id: '', admission_source_id: '', medical_specialty: '', payer_code: '', time_in_hospital: '',
    num_lab_procedures: 0, num_procedures: 0, num_medications: 0, number_outpatient: 0, number_emergency: 0, number_inpatient: 0,
    number_diagnoses: 0, max_glu_serum: 'None', a1c_result: 'None', med_changed: false, diabetes_med: false, readmitted: 'NO',
    diagnoses: [], medications: [],
  }
}

// Returns {field: message}; empty object means valid. `creating` adds the id fields.
export function validateEncounter(v, creating) {
  const e = {}
  const need = (name) => { if (v[name] === '' || v[name] === null || v[name] === undefined) e[name] = 'This field is required.' }
  ;['admission_date', 'discharge_date', 'age_group', 'admission_type_id', 'discharge_disposition_id', 'admission_source_id', 'time_in_hospital'].forEach(need)
  if (creating) { need('encounter_id'); need('patient_nbr') }
  for (const [name, [lo, hi]] of Object.entries(CAPS)) {
    if (v[name] === '' || v[name] === undefined) { if (!e[name]) e[name] = 'This field is required.'; continue }
    const n = Number(v[name])
    if (!Number.isInteger(n) || n < lo || n > hi) e[name] = `Enter a whole number from ${lo} to ${hi}.`
  }
  if (creating) {
    for (const name of ['encounter_id', 'patient_nbr']) if (v[name] !== '' && !(Number.isInteger(Number(v[name])) && Number(v[name]) > 0)) e[name] = 'Enter a positive whole number.'
  }
  if (v.admission_date && (v.admission_date < WINDOW_START || v.admission_date > WINDOW_END)) e.admission_date = 'Must be within 1999-01-01 and 2008-12-31 (simulated study window).'
  if (v.admission_date && v.discharge_date && !e.discharge_date) {
    if (v.discharge_date < v.admission_date) e.discharge_date = 'Discharge date must not be before the admission date.'
    else if (!e.time_in_hospital && daysBetween(v.admission_date, v.discharge_date) !== Number(v.time_in_hospital)) {
      e.discharge_date = `Discharge date minus admission date must equal the length of stay (${v.time_in_hospital} days).`
    }
  }
  if (v.payer_code && v.payer_code.length > 10) e.payer_code = 'At most 10 characters.'
  if (v.medical_specialty && v.medical_specialty.length > 80) e.medical_specialty = 'At most 80 characters.'
  const positions = (v.diagnoses || []).map((d) => d.position)
  if (positions.length > 3) e.diagnoses = 'At most 3 diagnoses.'
  ;(v.diagnoses || []).forEach((d, i) => { if (!ICD9.test(d.icd9_code || '')) e[`diagnoses.${i}.icd9_code`] = 'Enter an ICD-9 code such as 250.83, V57 or E909.' })
  const drugs = (v.medications || []).map((m) => m.drug_name)
  if (new Set(drugs).size !== drugs.length) e.medications = 'Each drug can appear only once.'
  return e
}

export function toPayload(v, creating) {
  const num = (x) => Number(x)
  const body = {
    admission_date: v.admission_date, discharge_date: v.discharge_date, age_group: v.age_group,
    admission_type_id: num(v.admission_type_id), discharge_disposition_id: num(v.discharge_disposition_id),
    admission_source_id: num(v.admission_source_id), medical_specialty: v.medical_specialty?.trim() || null,
    payer_code: v.payer_code?.trim() || null, max_glu_serum: v.max_glu_serum, a1c_result: v.a1c_result,
    med_changed: Boolean(v.med_changed), diabetes_med: Boolean(v.diabetes_med), readmitted: v.readmitted,
    diagnoses: (v.diagnoses || []).map((d, i) => ({ position: i + 1, icd9_code: d.icd9_code.trim() })),
    medications: (v.medications || []).map((m) => ({ drug_name: m.drug_name, dosage_status: m.dosage_status })),
  }
  COUNT_FIELDS.forEach((k) => { body[k] = num(v[k]) })
  if (creating) { body.encounter_id = num(v.encounter_id); body.patient_nbr = num(v.patient_nbr) }
  // readmitted_30d / is_readmission_eligible are derived by the server and are deliberately never sent.
  return body
}

export function fromEncounter(enc) {
  return {
    ...emptyEncounter(), ...Object.fromEntries(Object.keys(emptyEncounter()).filter((k) => enc[k] !== undefined && enc[k] !== null).map((k) => [k, enc[k]])),
    medical_specialty: enc.medical_specialty || '', payer_code: enc.payer_code || '',
    diagnoses: (enc.diagnoses || []).map((d) => ({ position: d.position, icd9_code: d.icd9_code })),
    medications: (enc.medications || []).map((m) => ({ drug_name: m.drug_name, dosage_status: m.dosage_status })),
  }
}
