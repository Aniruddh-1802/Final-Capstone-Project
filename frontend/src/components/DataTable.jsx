import { EmptyState, ErrorState, Loading } from './states'

// columns: [{key, label, sortKey?, render?(row), className?}]. Sorting and paging are SERVER-side: this component only
// reports clicks; the parent changes the query and the API returns the next page.
export function DataTable({ columns, rows, loading, error, onRetry, sortBy, sortDir, onSort, onRowClick, rowKey, empty }) {
  if (error) return <ErrorState error={error} onRetry={onRetry} />
  if (loading && !rows?.length) return <Loading lines={6} />
  if (!rows?.length) return empty || <EmptyState />
  return (
    <div className={`table-wrap${loading ? ' dim' : ''}`}>
      <table className="data">
        <thead>
          <tr>
            {columns.map((c) => {
              const active = c.sortKey && c.sortKey === sortBy
              return (
                <th key={c.key} scope="col" aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined}>
                  {c.sortKey && onSort
                    ? <button type="button" className="th-btn" onClick={() => onSort(c.sortKey)}>{c.label}{active ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}</button>
                    : c.label}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className={onRowClick ? 'clickable' : undefined} tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={onRowClick ? (e) => { if (e.key === 'Enter') onRowClick(row) } : undefined}>
              {columns.map((c) => <td key={c.key} className={c.className}>{c.render ? c.render(row) : row[c.key] ?? '-'}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Pagination({ page, pages, total, pageSize, onPage }) {
  if (!total) return null
  const from = (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  return (
    <nav className="pager" aria-label="Pagination">
      <span>{page > pages ? `Page ${page} is past the last page (${pages})` : `${from.toLocaleString()}–${to.toLocaleString()} of ${total.toLocaleString()}`}</span>
      <div>
        <button type="button" className="btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <span className="page-label">Page {page} of {pages}</span>
        <button type="button" className="btn" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </nav>
  )
}
