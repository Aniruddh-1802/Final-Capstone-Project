import { describe, expect, it } from 'vitest'
import { canAccess, hasRole, navFor, ROLES } from './roles'

const as = (role) => ({ username: 'u', role })

describe('role helpers', () => {
  it('hasRole is false without a user and checks membership', () => {
    expect(hasRole(null, ROLES.ADMIN)).toBe(false)
    expect(hasRole(as('analyst'), ROLES.ADMIN, ROLES.OPS)).toBe(false)
    expect(hasRole(as('clinical_ops'), ROLES.ADMIN, ROLES.OPS)).toBe(true)
  })
  it('navigation differs by role', () => {
    const labels = (r) => navFor(as(r)).map((x) => x.label)
    expect(labels('analyst')).toEqual(['Dashboard', 'Encounters', 'Reports'])
    expect(labels('clinical_ops')).toEqual(['Dashboard', 'Patients', 'Encounters', 'Reports', 'Pipeline Runs', 'Data Quality'])
    expect(labels('administrator')).toEqual(['Dashboard', 'Patients', 'Encounters', 'Reports', 'Pipeline Runs', 'Data Quality', 'Audit Log', 'Users'])
    expect(navFor(null)).toEqual([])
  })
  it('canAccess covers nested paths and unknown paths', () => {
    expect(canAccess(as('analyst'), '/patients')).toBe(false)
    expect(canAccess(as('analyst'), '/patients/12')).toBe(false)
    expect(canAccess(as('clinical_ops'), '/patients/12')).toBe(true)
    expect(canAccess(as('clinical_ops'), '/audit')).toBe(false)
    expect(canAccess(as('administrator'), '/audit')).toBe(true)
    expect(canAccess(as('administrator'), '/nope')).toBe(false)
  })
})