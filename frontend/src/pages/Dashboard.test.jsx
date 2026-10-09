import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal()), api: { get: vi.fn() } }))
import { api } from '../api/client'
import Dashboard from './Dashboard'

const meta = { filters: {}, denominator: 'eligible encounters', dates_simulated: true, generated_at: '2026-10-08T12:00:00' }
const row = (label, encounters, rate, small = false) => ({ id: null, label, encounters, eligible_encounters: encounters - 1, readmitted_30d: 2, readmission_rate: rate, small_n: small, avg_length_of_stay: 4.2 })
const ages = [row('[0-10)', 5, 0.019355, true), row('[10-20)', 637, 0.059748), row('[90-100)', 2467, 0.115822)]

function route(url, params) {
  if (url === '/reference/age-groups') return { data: [{ id: 1, label: '[0-10)' }, { id: 2, label: '[10-20)' }] }
  if (url === '/reference/admission-types') return { data: [{ id: 1, label: 'Emergency' }, { id: 2, label: 'Urgent' }] }
  if (url === '/analytics/summary') {
    return { data: { data: { total_encounters: params.admission_type_id ? 9 : 91566, unique_patients: 65472, avg_length_of_stay: 4.428565, avg_num_medications: 15.933272,
      eligible_encounters: 89394, readmitted_30d: 10214, readmission_rate_30d: 0.114258, any_readmission_rate: 0.48 }, meta } }
  }
  if (url === '/analytics/length-of-stay') return { data: { data: params.group_by === 'overall' ? [{ label: 'All', encounters: 6, histogram: [1, 2, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] }] : [{ id: 1, label: 'Emergency', encounters: 30, avg_length_of_stay: 4.5, small_n: false }], meta } }
  if (url === '/analytics/medications') return { data: { data: { top_drugs: [], insulin_status: [row('No', 100, 0.10), row('Up', 8, 0.20, true)], a1c_result: [row('None', 100, 0.11)] }, meta } }
  return { data: { data: params.group_by === 'age_group' || !params.group_by ? ages : [row('x', 20, 0.1)], meta } }
}

const renderPage = () => render(<MemoryRouter><Dashboard /></MemoryRouter>)

describe('Dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockImplementation((url, config) => Promise.resolve(route(url, config?.params || {})))
  })

  it('shows the simulated-dates banner and the KPI cards straight from the API', async () => {
    renderPage()
    expect(screen.getByText(/Admission dates in this dataset are simulated/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('kpi-encounters')).toHaveTextContent('91,566'))
    expect(screen.getByTestId('kpi-unique-patients')).toHaveTextContent('65,472')
    expect(screen.getByTestId('kpi-average-length-of-stay')).toHaveTextContent('4.43 days')
    expect(screen.getByTestId('kpi-30-day-readmission-rate')).toHaveTextContent('11.43%')  // 0.114258 from the API, only formatted
    expect(screen.getByText(/eligible encounters \(89,394 of 91,566\)/i)).toBeInTheDocument()
  })

  it('explains the denominator in a tooltip', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByTestId('kpi-30-day-readmission-rate')).toHaveTextContent('11.43%'))
    expect(screen.getByRole('tooltip')).toHaveTextContent(/Expired and hospice discharges are excluded from the denominator/)
  })

  it('every chart states its question and can be viewed as a table with small groups footnoted', async () => {
    renderPage()
    const card = await screen.findByRole('region', { name: 'Readmission by age group' })
    expect(card).toHaveTextContent('Which age groups have a higher 30-day readmission rate?')
    expect(card).toHaveTextContent(/fewer than 11 encounters/i)
    await userEvent.click(await screen.findAllByRole('button', { name: 'View as table' }).then((b) => b.find((x) => card.contains(x))))
    expect(card).toHaveTextContent('[0-10) *')            // small_n group marked
    expect(card).toHaveTextContent('1.9%')                 // rates are the API's numbers, formatted
    const labels = [...card.querySelectorAll('tbody tr td:first-child')].map((td) => td.textContent)
    expect(labels).toEqual(['[0-10) *', '[10-20)', '[90-100)'])  // clinical order exactly as the API returned it
  })

  it('sends changed filters to every endpoint, debounced, and the cards follow', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByTestId('kpi-encounters')).toHaveTextContent('91,566'))
    api.get.mockClear()
    await userEvent.selectOptions(screen.getByLabelText('Admission type'), 'Urgent')
    const summaryCalls = () => api.get.mock.calls.filter(([u]) => u === '/analytics/summary')
    await waitFor(() => expect(summaryCalls()).toHaveLength(1), { timeout: 3000 })  // one debounced request, not one per keystroke
    await waitFor(() => expect(screen.getByTestId('kpi-encounters').querySelector('.kpi-value').textContent).toBe('9'))
    expect(summaryCalls()[0][1].params).toMatchObject({ admission_type_id: '2' })
    const analyticsCalls = api.get.mock.calls.filter(([u]) => u.startsWith('/analytics/'))
    expect(analyticsCalls.every(([, c]) => c.params.admission_type_id === '2')).toBe(true)  // all charts got the same filter
  })

  it('shows an error with retry when an endpoint fails, and recovers', async () => {
    let fail = true
    api.get.mockImplementation((url, config) => (url === '/analytics/utilization' && fail
      ? Promise.reject({ response: { status: 500, data: { error: { message: 'boom' } } } })
      : Promise.resolve(route(url, config?.params || {}))))
    renderPage()
    const card = await screen.findByRole('region', { name: 'Prior inpatient visits and readmission' })
    const alert = await waitFor(() => { const a = card.querySelector('[role=alert]'); expect(a).toBeTruthy(); return a })
    expect(alert).toHaveTextContent(/server had a problem/i)
    fail = false
    await act(async () => { await userEvent.click(card.querySelector('button.btn')) })
    await waitFor(() => expect(card.querySelector('[role=alert]')).toBeNull())
  })

  it('warns about an impossible date range instead of silently showing odd data', async () => {
    renderPage()
    await userEvent.type(screen.getByLabelText('From'), '2008-05-01')
    await userEvent.type(screen.getByLabelText('To'), '2005-01-01')
    expect(screen.getByRole('alert')).toHaveTextContent(/must not be after/i)
  })

  it('uses careful wording: associations, never causes', async () => {
    renderPage()
    await screen.findByRole('region', { name: 'Insulin dosage and readmission' })
    expect(document.body.textContent).not.toMatch(/\bcauses?\b|\bcaused\b|\bdue to\b/i)
    expect(document.body.textContent).toMatch(/associated with|associations only/i)
  })
})
