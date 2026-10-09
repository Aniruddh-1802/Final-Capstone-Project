import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from './useApi'

// A server-side list whose entire state (filters, page, sort) lives in the URL query string, so a filtered view can be
// bookmarked or shared and survives a refresh. The API does the filtering, sorting and paging; nothing is loaded in bulk.
export function useListPage(path, { defaultSort = '', defaultDir = 'desc', pageSize = 25, fixed = {} } = {}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const entries = Object.fromEntries(searchParams.entries())
  const page = Math.max(1, Number(entries.page) || 1)
  const sortBy = entries.sort_by || defaultSort
  const sortDir = entries.sort_dir || defaultDir
  const filters = useMemo(() => {
    const { page: _p, sort_by: _s, sort_dir: _d, page_size: _ps, ...rest } = entries
    return rest
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const params = { ...filters, ...fixed, page, page_size: pageSize, ...(sortBy ? { sort_by: sortBy, sort_dir: sortDir } : {}) }
  const state = useApi(path, params)

  const update = useCallback((patch, resetPage = true) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      Object.entries(patch).forEach(([k, v]) => (v === '' || v === null || v === undefined ? next.delete(k) : next.set(k, String(v))))
      if (resetPage) next.delete('page')
      return next
    })
  }, [setSearchParams])

  return {
    ...state, page, sortBy, sortDir, filters, pageSize,
    setFilters: (values) => update({ ...Object.fromEntries(Object.keys(filters).map((k) => [k, ''])), ...values }),
    setPage: (p) => update({ page: p }, false),
    onSort: (key) => update({ sort_by: key, sort_dir: key === sortBy && sortDir === 'desc' ? 'asc' : key === sortBy ? 'desc' : 'asc' }),
  }
}
