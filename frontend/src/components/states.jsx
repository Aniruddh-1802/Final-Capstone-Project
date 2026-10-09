import { toErrorMessage } from '../api/client'

export function Loading({ label = 'Loading…', lines = 3 }) {
  return (
    <div className="skeleton" role="status" aria-live="polite" aria-label={label}>
      {Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton-line" style={{ width: `${95 - i * 12}%` }} />)}
      <span className="sr-only">{label}</span>
    </div>
  )
}

export function ErrorState({ error, message, onRetry }) {
  const text = message || toErrorMessage(error) || 'Something went wrong.'
  return (
    <div className="state error" role="alert">
      <p>{text}</p>
      {onRetry && <button type="button" className="btn" onClick={onRetry}>Retry</button>}
    </div>
  )
}

export function EmptyState({ title = 'No results', hint = 'Try widening the filters.' }) {
  return (
    <div className="state empty">
      <strong>{title}</strong>
      <p>{hint}</p>
    </div>
  )
}

// Shown on every page that displays dates or trends: the dataset has no real dates (see docs/data_contract.md).
export function SimulatedDatesBanner() {
  return (
    <div className="banner" role="note">
      <strong>Admission dates in this dataset are simulated.</strong> The source data has no dates, so monthly and yearly
      patterns are illustrative and must not be read as clinical findings.
    </div>
  )
}

export function Badge({ className = 'badge', children }) {
  return <span className={className}>{children}</span>
}
