import { describe, expect, it } from 'vitest'
import { emptyEncounter, toPayload, validateEncounter } from './encounterSchema'

const valid = () => ({
  ...emptyEncounter(), encounter_id: 5, patient_nbr: 9, admission_date: '2005-03-01', discharge_date: '2005-03-04', age_group: '[70-80)',
  admission_type_id: 1, discharge_disposition_id: 1, admission_source_id: 7, time_in_hospital: 3, diagnoses: [{ position: 1, icd9_code: '250.83' }],
})

describe('validateEncounter mirrors the API rules', () => {
  it('accepts a valid encounter', () => {
    expect(validateEncounter(valid(), true)).toEqual({})
  })
  it('rejects a length of stay outside 1-14, attached to the field', () => {
    expect(validateEncounter({ ...valid(), time_in_hospital: 0 }, true).time_in_hospital).toMatch(/1 to 14/)
    expect(validateEncounter({ ...valid(), time_in_hospital: 15 }, true).time_in_hospital).toMatch(/1 to 14/)
  })
  it('requires discharge >= admission and dates that agree with the stay length', () => {
    expect(validateEncounter({ ...valid(), discharge_date: '2005-02-27' }, true).discharge_date).toMatch(/before/i)
    expect(validateEncounter({ ...valid(), discharge_date: '2005-03-10' }, true).discharge_date).toMatch(/length of stay \(3 days\)/)
  })
  it('requires the lookups and the ids when creating', () => {
    const e = validateEncounter({ ...valid(), admission_type_id: '', encounter_id: '' }, true)
    expect(e.admission_type_id).toMatch(/required/i)
    expect(e.encounter_id).toMatch(/required/i)
    expect(validateEncounter({ ...valid(), encounter_id: '' }, false).encounter_id).toBeUndefined()  // not needed when editing
  })
  it('checks ICD-9 format, duplicate drugs and the study window', () => {
    expect(validateEncounter({ ...valid(), diagnoses: [{ position: 1, icd9_code: 'ABC' }] }, true)['diagnoses.0.icd9_code']).toBeDefined()
    expect(validateEncounter({ ...valid(), diagnoses: [{ position: 1, icd9_code: 'V57' }, { position: 2, icd9_code: '38' }] }, true)).toEqual({})
    expect(validateEncounter({ ...valid(), medications: [{ drug_name: 'insulin', dosage_status: 'Up' }, { drug_name: 'insulin', dosage_status: 'Down' }] }, true).medications).toBeDefined()
    expect(validateEncounter({ ...valid(), admission_date: '2015-03-01', discharge_date: '2015-03-04' }, true).admission_date).toMatch(/1999/)
  })
})

describe('toPayload', () => {
  it('never sends the server-derived flags and converts types', () => {
    const body = toPayload({ ...valid(), readmitted_30d: true, is_readmission_eligible: false }, true)
    expect(body).not.toHaveProperty('readmitted_30d')
    expect(body).not.toHaveProperty('is_readmission_eligible')
    expect(body.encounter_id).toBe(5)
    expect(body.time_in_hospital).toBe(3)
    expect(body.medical_specialty).toBeNull()
    expect(body.diagnoses).toEqual([{ position: 1, icd9_code: '250.83' }])
  })
  it('omits the identity fields when editing', () => {
    expect(toPayload(valid(), false)).not.toHaveProperty('encounter_id')
  })
})