import { describe, expect, it } from 'vitest'
import { formatDate, formatDecimal, formatInt, formatPercent, rejectRatio, statusClass } from './format'

describe('formatters', () => {
  it('formats counts, decimals and rates; missing values are explicit', () => {
    expect(formatInt(91566)).toBe('91,566')
    expect(formatInt(null)).toBe('-')
    expect(formatDecimal(4.428565, 2)).toBe('4.43')
    expect(formatPercent(0.114258, 2)).toBe('11.43%')
    expect(formatPercent(null)).toBe('n/a')  // a group with no eligible encounters is "n/a", never 0%
  })
  it('keeps ISO dates untouched (no timezone shifting) and trims datetimes', () => {
    expect(formatDate('2005-03-01')).toBe('2005-03-01')
    expect(formatDate('2026-10-08T23:49:51')).toBe('2026-10-08 23:49')
    expect(formatDate(null)).toBe('-')
  })
  it('maps run status to a badge class and reject ratio to a number', () => {
    expect(statusClass('FAILED')).toContain('bad')
    expect(statusClass('SKIPPED_DUPLICATE_FILE')).toContain('muted')
    expect(rejectRatio({ rows_read: 5088, rows_rejected: 23 })).toBeCloseTo(0.00452, 5)
    expect(rejectRatio({ rows_read: 0, rows_rejected: 0 })).toBeNull()
  })
})