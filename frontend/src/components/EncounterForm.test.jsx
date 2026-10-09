import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal()), api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))
vi.mock('./Toast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }))
import { api } from '../api/client'
import EncounterForm from './EncounterForm'

const refs = {
  '/reference/age-groups': [{ id: 8, label: '[70-80)' }], '/reference/admission-types': [{ id: 1, label: 'Emergency' }],
  '/reference/admission-sources': [{ id: 7, label: 'Emergency Room' }], '/reference/discharge-dispositions': [{ id: 1, label: 'Discharged to home' }],
  '/reference/specialties': [{ id: 1, label: 'Cardiology' }],
}
const existing = {
  encounter_id: 77, patient_nbr: 5, admission_date: '2005-03-01', discharge_date: '2005-03-04', age_group: '[70-80)', admission_type_id: 1,
  discharge_disposition_id: 1, admission_source_id: 7, medical_specialty: 'Cardiology', payer_code: 'MC', time_in_hospital: 3, num_lab_procedures: 40,
  num_procedures: 1, num_medications: 12, number_outpatient: 0, number_emergency: 0, number_inpatient: 0, number_diagnoses: 3, max_glu_serum: 'None',
  a1c_result: 'None', med_changed: false, diabetes_med: true, readmitted: 'NO', readmitted_30d: false, is_readmission_eligible: true,
  diagnoses: [{ position: 1, icd9_code: '250.83' }], medications: [],
}

async function fillCreate(user) {
  await user.type(screen.getByLabelText('Encounter ID'), '900000001')
  await user.type(screen.getByLabelText('Patient number'), '5')
  await user.selectOptions(screen.getByLabelText('Age group'), '[70-80)')
  await user.type(screen.getByLabelText('Admission date'), '2005-03-01')
  await user.type(screen.getByLabelText('Discharge date'), '2005-03-04')
  await user.type(screen.getByLabelText(/Length of stay/), '3')
  await user.selectOptions(screen.getByLabelText('Admission type'), 'Emergency')
  await user.selectOptions(screen.getByLabelText('Admission source'), 'Emergency Room')
  await user.selectOptions(screen.getByLabelText('Discharge disposition'), 'Discharged to home')
}

describe('EncounterForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockImplementation((url) => Promise.resolve({ data: refs[url] || [] }))
  })

  it('shows an invalid length of stay against the right field and does not call the API', async () => {
    const user = userEvent.setup()
    render(<EncounterForm onClose={vi.fn()} onSaved={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Emergency' })).toBeInTheDocument())
    await fillCreate(user)
    await user.clear(screen.getByLabelText(/Length of stay/))
    await user.type(screen.getByLabelText(/Length of stay/), '20')
    await user.click(screen.getByRole('button', { name: 'Create encounter' }))
    const field = screen.getByLabelText(/Length of stay/).closest('.field')
    expect(within(field).getByRole('alert')).toHaveTextContent('Enter a whole number from 1 to 14.')
    expect(api.post).not.toHaveBeenCalled()
  })

  it('sends a correct body without the derived flags, and reports success', async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    api.post.mockResolvedValue({ data: { encounter_id: 900000001 } })
    render(<EncounterForm onClose={vi.fn()} onSaved={onSaved} />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Emergency' })).toBeInTheDocument())
    await fillCreate(user)
    await user.click(screen.getByRole('button', { name: 'Create encounter' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
    const [url, body] = api.post.mock.calls[0]
    expect(url).toBe('/encounters')
    expect(body).toMatchObject({ encounter_id: 900000001, patient_nbr: 5, time_in_hospital: 3, admission_type_id: 1, readmitted: 'NO' })
    expect(body).not.toHaveProperty('readmitted_30d')
    expect(body).not.toHaveProperty('is_readmission_eligible')
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
  })

  it('maps a server 422 onto the matching fields', async () => {
    const user = userEvent.setup()
    api.post.mockRejectedValue({ response: { status: 422, data: { error: { code: 'validation_error', message: 'Request validation failed', details: [
      { loc: ['body', 'patient_nbr'], msg: 'patient 5 does not exist', type: 'value_error' },
      { loc: ['body', 'discharge_date'], msg: 'discharge_date must not be before admission_date', type: 'value_error' }] } } } })
    render(<EncounterForm onClose={vi.fn()} onSaved={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Emergency' })).toBeInTheDocument())
    await fillCreate(user)
    await user.click(screen.getByRole('button', { name: 'Create encounter' }))
    await waitFor(() => expect(within(screen.getByLabelText('Patient number').closest('.field')).getByRole('alert')).toHaveTextContent('patient 5 does not exist'))
    expect(within(screen.getByLabelText('Discharge date').closest('.field')).getByRole('alert')).toHaveTextContent('must not be before admission_date')
  })

  it('shows the derived flags read-only when editing and cannot change the identity', async () => {
    render(<EncounterForm encounter={existing} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByTestId('derived-30d')).toHaveTextContent('no')
    expect(screen.getByTestId('derived-eligible')).toHaveTextContent('yes')
    expect(screen.queryByLabelText('Encounter ID')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Patient number')).not.toBeInTheDocument()
  })

  it('limits diagnoses to three', async () => {
    const user = userEvent.setup()
    render(<EncounterForm encounter={existing} onClose={vi.fn()} onSaved={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Add diagnosis' }))
    await user.click(screen.getByRole('button', { name: 'Add diagnosis' }))
    expect(screen.queryByRole('button', { name: 'Add diagnosis' })).not.toBeInTheDocument()
  })
})
