import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))
import { useAuth } from '../context/AuthContext'
import { ProtectedRoute, RoleRoute } from './guards'

const tree = (path) => (
  <MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route path="/login" element={<div>login page</div>} />
      <Route element={<ProtectedRoute />}>
        <Route path="/home" element={<div>home page</div>} />
        <Route element={<RoleRoute roles={['administrator']} />}>
          <Route path="/audit" element={<div>audit page</div>} />
        </Route>
      </Route>
    </Routes>
  </MemoryRouter>
)

describe('route guards', () => {
  beforeEach(() => vi.clearAllMocks())

  it('sends an unauthenticated visitor to the login page and shows nothing else', () => {
    useAuth.mockReturnValue({ user: null, loading: false })
    render(tree('/audit'))
    expect(screen.getByText('login page')).toBeInTheDocument()
    expect(screen.queryByText('audit page')).not.toBeInTheDocument()
  })

  it('waits while the session is being checked (no flash of protected content)', () => {
    useAuth.mockReturnValue({ user: null, loading: true })
    render(tree('/home'))
    expect(screen.queryByText('home page')).not.toBeInTheDocument()
    expect(screen.queryByText('login page')).not.toBeInTheDocument()
  })

  it('shows "Not permitted" to a signed-in user with the wrong role', () => {
    useAuth.mockReturnValue({ user: { username: 'ana', role: 'analyst' }, loading: false })
    render(tree('/audit'))
    expect(screen.getByRole('heading', { name: 'Not permitted' })).toBeInTheDocument()
    expect(screen.queryByText('audit page')).not.toBeInTheDocument()
  })

  it('renders the page for the right role', () => {
    useAuth.mockReturnValue({ user: { username: 'admin', role: 'administrator' }, loading: false })
    render(tree('/audit'))
    expect(screen.getByText('audit page')).toBeInTheDocument()
  })
})
