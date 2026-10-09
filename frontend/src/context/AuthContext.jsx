import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, setUnauthorizedHandler, tokenStore } from '../api/client'
import { hasRole as roleCheck } from '../lib/roles'

const AuthContext = createContext(null)

// The user and role always come from GET /auth/me (the server's answer), never from anything stored in the browser.
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(tokenStore.get()))

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    if (!tokenStore.get()) return undefined
    let cancelled = false
    api.get('/auth/me')
      .then((r) => { if (!cancelled) setUser(r.data) })
      .catch(() => { if (!cancelled) logout() })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [logout])

  const login = useCallback(async (username, password) => {
    const form = new URLSearchParams({ username, password })  // OAuth2 password flow is form-encoded
    const { data } = await api.post('/auth/login', form)
    tokenStore.set(data.access_token)
    const me = await api.get('/auth/me')
    setUser(me.data)
    return me.data
  }, [])

  const value = useMemo(() => ({
    user, loading, login, logout, hasRole: (...roles) => roleCheck(user, ...roles),
  }), [user, loading, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
