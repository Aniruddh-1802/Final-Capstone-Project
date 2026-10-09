import { useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { formatDecimal, formatInt, formatPercent } from '../lib/format'
import { EmptyState, ErrorState, Loading } from './states'

// Okabe-Ito palette (colour-blind safe). Muted grey marks groups with fewer than 11 encounters (small_n).
export const COLORS = { blue: '#0072B2', orange: '#E69F00', green: '#009E73', vermillion: '#D55E00', sky: '#56B4E9', purple: '#CC79A7', muted: '#B8BFCC' }

export function KpiCard({ label, value, hint, loading }) {
  return (
    <div className="kpi" data-testid={`kpi-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`}>
      <div className="kpi-label">
        {label}
        {hint && <span className="info" tabIndex={0} aria-label={hint}>ⓘ<span className="tip" role="tooltip">{hint}</span></span>}
      </div>
      <div className="kpi-value">{loading ? '…' : value}</div>
    </div>
  )
}

// Every chart states the question it answers, offers the same numbers as a table, and handles loading/empty/error.
export function ChartCard({ title, question, state, hasData, table, footnote, actions, children }) {
  const [asTable, setAsTable] = useState(false)
  const { loading, error, reload } = state
  let body
  if (error) body = <ErrorState error={error} onRetry={reload} />
  else if (loading && !hasData) body = <Loading lines={5} />
  else if (!hasData) body = <EmptyState hint="No encounters match the current filters." />
  else body = asTable ? table : <div className={loading ? 'dim' : undefined}>{children}</div>
  return (
    <section className="card chart-card" aria-label={title}>
      <header>
        <div>
          <h3>{title}</h3>
          <p className="question">{question}</p>
        </div>
        <div className="card-actions">
          {actions}
          {hasData && !error && (
            <button type="button" className="btn small" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
              {asTable ? 'View as chart' : 'View as table'}
            </button>
          )}
        </div>
      </header>
      {body}
      {footnote && <p className="footnote">{footnote}</p>}
    </section>
  )
}

export const SMALL_N_NOTE = 'Grey bars: fewer than 11 encounters, so the rate is unreliable. Rates are the 30-day readmission rate among eligible encounters. Associations only: this observational data cannot show why a readmission happens.'

export function GroupTable({ rows, mode = 'rate' }) {
  const los = mode === 'los'
  return (
    <div className="table-wrap">
      <table className="data compact">
        <thead>
          <tr>
            <th scope="col">Group</th><th scope="col">Encounters</th>
            {los ? <th scope="col">Average length of stay (days)</th>
              : <><th scope="col">Eligible</th><th scope="col">30-day readmissions</th><th scope="col">Rate</th></>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.id ?? ''}${r.label}`} className={r.small_n ? 'muted-row' : undefined}>
              <td>{r.label}{r.small_n ? ' *' : ''}</td><td>{formatInt(r.encounters)}</td>
              {los ? <td>{formatDecimal(r.avg_length_of_stay)}</td>
                : <><td>{formatInt(r.eligible_encounters)}</td><td>{formatInt(r.readmitted_30d)}</td><td>{formatPercent(r.readmission_rate)}</td></>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
const shorten = (s, n = 24) => (String(s).length > n ? `${String(s).slice(0, n - 1)}…` : String(s))

const rateTip = (value, _name, item) => [formatPercent(value), item.payload.small_n ? '30-day readmission rate (small group)' : '30-day readmission rate']

export function RateBars({ rows, horizontal = false, color = COLORS.blue }) {
  const height = horizontal ? Math.max(240, rows.length * 30 + 40) : 280
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} layout={horizontal ? 'vertical' : 'horizontal'} margin={{ top: 8, right: 16, bottom: 8, left: horizontal ? 8 : 0 }}>
        <CartesianGrid strokeDasharray="3 3" />
        {horizontal
          ? <><XAxis type="number" tickFormatter={(v) => formatPercent(v, 0)} /><YAxis type="category" dataKey="label" width={170} interval={0} tick={{ fontSize: 12 }} tickFormatter={(v) => shorten(v, 26)} /></>
          : <><XAxis dataKey="label" interval={0} tick={{ fontSize: 12 }} tickFormatter={(v) => shorten(v, 14)} angle={rows.length > 6 ? -30 : 0} textAnchor={rows.length > 6 ? 'end' : 'middle'} height={rows.length > 6 ? 70 : 30} /><YAxis tickFormatter={(v) => formatPercent(v, 0)} /></>}
        <Tooltip formatter={rateTip} />
        <Bar dataKey="readmission_rate" name="30-day readmission rate" isAnimationActive={false}>
          {rows.map((r) => <Cell key={`${r.id ?? ''}${r.label}`} fill={r.small_n ? COLORS.muted : color} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function CountLine({ rows, dataKey = 'encounters', name = 'Encounters', color = COLORS.blue, percent = false }) {
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="label" interval="preserveStartEnd" minTickGap={24} />
        <YAxis tickFormatter={percent ? (v) => formatPercent(v, 0) : formatInt} />
        <Tooltip formatter={(v) => (percent ? formatPercent(v) : formatInt(v))} />
        <Line type="monotone" dataKey={dataKey} name={name} stroke={color} dot={false} strokeWidth={2} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

export function ValueBars({ rows, dataKey, name, color = COLORS.green, digits = 2 }) {
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="label" interval={0} tick={{ fontSize: 12 }} tickFormatter={(v) => shorten(v, 14)} angle={rows.length > 6 ? -30 : 0} textAnchor={rows.length > 6 ? 'end' : 'middle'} height={rows.length > 6 ? 70 : 30} />
        <YAxis />
        <Tooltip formatter={(v) => formatDecimal(v, digits)} />
        <Legend />
        <Bar dataKey={dataKey} name={name} isAnimationActive={false}>
          {rows.map((r) => <Cell key={r.label} fill={r.small_n ? COLORS.muted : color} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
