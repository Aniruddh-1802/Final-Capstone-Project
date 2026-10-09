import { useMemo, useState } from 'react'
import { ChartCard, COLORS, CountLine, GroupTable, KpiCard, RateBars, SMALL_N_NOTE, ValueBars } from '../components/charts'
import { SimulatedDatesBanner } from '../components/states'
import { useApi } from '../hooks/useApi'
import { useDebounce } from '../hooks/useDebounce'
import { formatDecimal, formatInt, formatPercent } from '../lib/format'

const EMPTY_FILTERS = { date_from: '', date_to: '', age_group: '', admission_type_id: '' }
const RATE_HINT = '30-day readmissions ÷ eligible encounters. Expired and hospice discharges are excluded from the denominator because those patients could not be readmitted.'

function FilterBar({ filters, onChange, onClear, invalidRange }) {
  const ages = useApi('/reference/age-groups')
  const types = useApi('/reference/admission-types')
  const set = (key) => (e) => onChange({ ...filters, [key]: e.target.value })
  return (
    <form className="filters" aria-label="Dashboard filters" onSubmit={(e) => e.preventDefault()}>
      <label>From<input type="date" value={filters.date_from} onChange={set('date_from')} /></label>
      <label>To<input type="date" value={filters.date_to} onChange={set('date_to')} /></label>
      <label>Age group
        <select value={filters.age_group} onChange={set('age_group')}>
          <option value="">All ages</option>
          {(ages.data || []).map((a) => <option key={a.id} value={a.label}>{a.label}</option>)}
        </select>
      </label>
      <label>Admission type
        <select value={filters.admission_type_id} onChange={set('admission_type_id')}>
          <option value="">All types</option>
          {(types.data || []).map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
        </select>
      </label>
      <button type="button" className="btn" onClick={onClear}>Clear filters</button>
      {invalidRange && <p className="field-error" role="alert">“From” must not be after “To”.</p>}
    </form>
  )
}

const groupData = (state) => state.data?.data || []
const hasRows = (rows) => rows.length > 0

function Group({ title, question, path, extra, filters, render, slice }) {
  const state = useApi(path, { ...filters, ...extra })
  const rows = useMemo(() => (slice ? groupData(state).slice(0, slice) : groupData(state)), [state.data, slice])
  return (
    <ChartCard title={title} question={question} state={state} hasData={hasRows(rows)}
               table={<GroupTable rows={rows} />} footnote={SMALL_N_NOTE}>
      {render(rows)}
    </ChartCard>
  )
}

export default function Dashboard() {
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const applied = useDebounce(filters, 300)  // one debounced object drives every request on the page
  const invalidRange = Boolean(filters.date_from && filters.date_to && filters.date_from > filters.date_to)
  const [granularity, setGranularity] = useState('month')

  const summary = useApi('/analytics/summary', applied)
  const s = summary.data?.data
  const trend = useApi('/analytics/admissions-trend', { ...applied, granularity })
  const trendRows = groupData(trend)
  const los = useApi('/analytics/length-of-stay', { ...applied, group_by: 'admission_type' })
  const losRows = groupData(los)
  const hist = useApi('/analytics/length-of-stay', { ...applied, group_by: 'overall' })
  const histRows = useMemo(() => (hist.data?.data?.[0]?.histogram || []).map((n, i) => ({ label: String(i + 1), encounters: n })), [hist.data])
  const meds = useApi('/analytics/medications', applied)
  const insulin = meds.data?.data?.insulin_status || []
  const a1c = meds.data?.data?.a1c_result || []
  const medsHint = 'Insulin “No” means no insulin was prescribed. Associations only.'

  return (
    <div className="dashboard">
      <h1>Dashboard</h1>
      <SimulatedDatesBanner />
      <FilterBar filters={filters} onChange={setFilters} onClear={() => setFilters(EMPTY_FILTERS)} invalidRange={invalidRange} />

      <div className="kpis" aria-label="Key figures">
        <KpiCard label="Encounters" value={formatInt(s?.total_encounters)} loading={summary.loading && !s} />
        <KpiCard label="Unique patients" value={formatInt(s?.unique_patients)} loading={summary.loading && !s} />
        <KpiCard label="Average length of stay" value={s ? `${formatDecimal(s.avg_length_of_stay, 2)} days` : '-'} loading={summary.loading && !s} />
        <KpiCard label="30-day readmission rate" value={formatPercent(s?.readmission_rate_30d, 2)} hint={RATE_HINT} loading={summary.loading && !s} />
        <KpiCard label="Medications per encounter" value={formatDecimal(s?.avg_num_medications, 1)} loading={summary.loading && !s} />
      </div>
      {summary.error && <p className="field-error" role="alert">Could not load the key figures. <button type="button" className="link" onClick={summary.reload}>Retry</button></p>}
      <p className="caption">30-day readmission rate among eligible encounters ({formatInt(s?.eligible_encounters)} of {formatInt(s?.total_encounters)}).</p>

      <div className="grid">
        <ChartCard title="Admissions over time" question="How many encounters were admitted each month or year? (simulated dates)" state={trend} hasData={hasRows(trendRows)}
                   table={<GroupTable rows={trendRows} />} footnote="Dates are simulated, so this trend is illustrative only."
                   actions={<div className="seg" role="group" aria-label="Granularity">
                     {['month', 'year'].map((g) => <button key={g} type="button" className={granularity === g ? 'on' : ''} aria-pressed={granularity === g} onClick={() => setGranularity(g)}>{g === 'month' ? 'Month' : 'Year'}</button>)}
                   </div>}>
          <CountLine rows={trendRows} />
        </ChartCard>

        <Group title="30-day readmission rate over time" question="Is the 30-day readmission rate changing month to month? (simulated dates)" path="/analytics/readmissions"
               extra={{ group_by: 'month' }} filters={applied} render={(rows) => <CountLine rows={rows} dataKey="readmission_rate" name="30-day readmission rate" color={COLORS.vermillion} percent />} />

        <ChartCard title="Length of stay by admission type" question="Do some admission types stay longer?" state={los} hasData={hasRows(losRows)}
                   table={<GroupTable rows={losRows} mode="los" />} footnote="Average days per encounter. Grey bars: fewer than 11 encounters.">
          <ValueBars rows={losRows} dataKey="avg_length_of_stay" name="Average length of stay (days)" />
        </ChartCard>

        <ChartCard title="Length of stay distribution" question="How many encounters last 1, 2, … 14 days?" state={hist} hasData={histRows.some((r) => r.encounters > 0)}
                   table={<div className="table-wrap"><table className="data compact"><thead><tr><th scope="col">Days</th><th scope="col">Encounters</th></tr></thead><tbody>{histRows.map((r) => <tr key={r.label}><td>{r.label}</td><td>{formatInt(r.encounters)}</td></tr>)}</tbody></table></div>}>
          <ValueBars rows={histRows} dataKey="encounters" name="Encounters" color={COLORS.sky} digits={0} />
        </ChartCard>

        <Group title="Readmission by age group" question="Which age groups have a higher 30-day readmission rate?" path="/analytics/readmissions"
               extra={{ group_by: 'age_group' }} filters={applied} render={(rows) => <RateBars rows={rows} />} />

        <Group title="Readmission by admission source" question="Does the 30-day readmission rate differ by where patients were admitted from?" path="/analytics/readmissions"
               extra={{ group_by: 'admission_source' }} filters={applied} render={(rows) => <RateBars rows={rows} horizontal color={COLORS.green} />} />

        <Group title="Readmission by medical specialty (top 10 by volume)" question="Which of the most common specialties are associated with higher readmission? (about half of encounters have no specialty recorded)"
               path="/analytics/readmissions" extra={{ group_by: 'specialty' }} filters={applied} slice={10} render={(rows) => <RateBars rows={rows} horizontal color={COLORS.purple} />} />

        <ChartCard title="Insulin dosage and readmission" question="Is the insulin dosage status associated with 30-day readmission?" state={meds} hasData={hasRows(insulin)}
                   table={<GroupTable rows={insulin} />} footnote={`${medsHint} ${SMALL_N_NOTE}`}>
          <RateBars rows={insulin} color={COLORS.orange} />
        </ChartCard>

        <ChartCard title="A1C result and readmission" question="Is the A1C test result associated with 30-day readmission? (“None” = not tested)" state={meds} hasData={hasRows(a1c)}
                   table={<GroupTable rows={a1c} />} footnote={SMALL_N_NOTE}>
          <RateBars rows={a1c} color={COLORS.blue} />
        </ChartCard>

        <Group title="Prior inpatient visits and readmission" question="Do patients with more earlier inpatient visits have a higher readmission rate?" path="/analytics/utilization"
               filters={applied} render={(rows) => <RateBars rows={rows} color={COLORS.vermillion} />} />
      </div>
    </div>
  )
}
