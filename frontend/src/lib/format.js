// Presentation-only helpers. No rate or KPI is ever computed here: the API is the single source of truth.
export function formatInt(value) {
  return value === null || value === undefined ? '-' : Number(value).toLocaleString('en-US')
}

export function formatDecimal(value, digits = 2) {
  return value === null || value === undefined ? '-' : Number(value).toFixed(digits)
}

// The API returns rates as 0-1 (or null when a group has no eligible encounters).
export function formatPercent(value, digits = 1) {
  return value === null || value === undefined ? 'n/a' : `${(Number(value) * 100).toFixed(digits)}%`
}

// ISO date string -> "2005-03-01" kept as-is (no timezone shifting); ISO datetime -> "2005-03-01 14:05".
export function formatDate(value) {
  if (!value) return '-'
  const text = String(value)
  return text.length > 10 ? text.slice(0, 16).replace('T', ' ') : text
}

export function statusClass(status) {
  return { SUCCESS: 'badge ok', FAILED: 'badge bad', RUNNING: 'badge warn', SKIPPED_DUPLICATE_FILE: 'badge muted' }[status] || 'badge'
}

export function rejectRatio(run) {
  return run.rows_read ? run.rows_rejected / run.rows_read : null  // display only: both numbers come from the API
}
