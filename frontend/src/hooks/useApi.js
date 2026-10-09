import { useCallback, useEffect, useRef, useState } from 'react'
import { api, cleanParams, isCanceled } from '../api/client'

// GET with cancellation. When path/params change (or the component unmounts) the in-flight request is aborted AND its
// result is ignored, so a slow response for an old filter can never overwrite the newest one.
export function useApi(path, params, { enabled = true } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: enabled })
  const [nonce, setNonce] = useState(0)
  const key = JSON.stringify([path, cleanParams(params)])
  const latest = useRef(0)

  useEffect(() => {
    if (!enabled) return undefined
    const controller = new AbortController()
    const ticket = ++latest.current
    setState((s) => ({ data: s.data, error: null, loading: true }))
    api.get(path, { params: cleanParams(params), signal: controller.signal })
      .then((response) => {
        if (ticket === latest.current && !controller.signal.aborted) setState({ data: response.data, error: null, loading: false })
      })
      .catch((error) => {
        if (isCanceled(error) || ticket !== latest.current) return
        setState({ data: null, error, loading: false })
      })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, nonce, enabled])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { ...state, reload }
}
