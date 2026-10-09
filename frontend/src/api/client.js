import axios from 'axios'

// The ONE place that talks to the API. Every page uses `api`; 401 handling and error mapping are centralised here.
const TOKEN_KEY = 'hc_token'

// The token lives in sessionStorage (cleared when the tab closes, not shared across tabs) and is read from there on
// every request. localStorage was rejected: it persists after the browser closes and is shared by every tab, which
// widens the window if a script ever runs in the page. The app never renders untrusted HTML.
export const tokenStore = {
  get() {
    try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set(token) {
    try { sessionStorage.setItem(TOKEN_KEY, token) } catch { /* storage blocked: the session lasts until reload */ }
  },
  clear() {
    try { sessionStorage.removeItem(TOKEN_KEY) } catch { /* nothing to clear */ }
  },
}

export const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || '/api', timeout: 120000 })

let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) { onUnauthorized = fn }

api.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const isLogin = (error.config?.url || '').includes('/auth/login')
    if (error.response?.status === 401 && !isLogin) {
      tokenStore.clear()
      onUnauthorized()
    }
    return Promise.reject(error)
  },
)

// Drop empty filter values so they never reach the query string.
export function cleanParams(params = {}) {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v !== null && v !== undefined))
}

// The API error contract is {"error": {"code", "message", "details"}}.
export function apiError(err) {
  return err?.response?.data?.error || null
}

export function isCanceled(err) {
  return axios.isCancel(err) || err?.code === 'ERR_CANCELED'
}

export function toErrorMessage(err) {
  if (!err) return ''
  if (isCanceled(err)) return ''
  if (!err.response) return 'Cannot reach the server. Check that the API is running and try again.'
  const status = err.response.status
  const body = apiError(err)
  if (status === 401) return body?.message === 'Incorrect username or password' ? body.message : 'Your session has expired. Please sign in again.'
  if (status === 403) return 'You do not have permission to do that.'
  if (status === 413) return body?.message || 'That export is too large. Narrow the filters and try again.'
  if (status === 422) {
    const fields = toFieldErrors(err)
    const first = Object.entries(fields)[0]
    return first ? `${first[0]}: ${first[1]}` : body?.message || 'Some fields are not valid.'
  }
  if (status >= 500) return 'The server had a problem handling that request. Please try again.'
  return body?.message || `Request failed (${status}).`
}

// 422 details -> {field: message}. loc is like ["body", "time_in_hospital"] or ["body", "diagnoses", 0, "icd9_code"].
export function toFieldErrors(err) {
  const details = apiError(err)?.details
  if (!Array.isArray(details)) return {}
  const out = {}
  for (const d of details) {
    const loc = (d.loc || []).filter((part) => part !== 'body' && part !== 'query')
    const key = loc.join('.') || '_'
    const msg = String(d.msg || 'Invalid value').replace(/^Value error, /, '')
    if (!out[key]) out[key] = msg
  }
  return out
}

// Authenticated download: an axios request with responseType blob, then an object URL and a click on a temporary link.
// window.open cannot send the Authorization header, and putting the token in a URL would leak it into logs and history.
export async function downloadFile(path, params) {
  const response = await api.get(path, { params: cleanParams(params), responseType: 'blob' })
  const disposition = response.headers['content-disposition'] || ''
  const filename = /filename="?([^";]+)"?/.exec(disposition)?.[1] || 'download'
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
  return { filename, rows: Number(response.headers['x-row-count'] || 0), size: response.data.size }
}

// A blob error body is still the JSON error contract; parse it so toErrorMessage can read it.
export async function normaliseBlobError(err) {
  const data = err?.response?.data
  if (data instanceof Blob && data.type.includes('json')) {
    try { err.response.data = JSON.parse(await data.text()) } catch { /* leave as is */ }
  }
  return err
}
