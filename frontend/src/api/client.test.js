import { describe, expect, it } from 'vitest'
import { cleanParams, toErrorMessage, toFieldErrors } from './client'

const failure = (status, body) => ({ response: { status, data: body }, config: { url: '/x' } })

describe('toErrorMessage', () => {
  it('explains a network failure', () => {
    expect(toErrorMessage({ message: 'Network Error' })).toMatch(/cannot reach the server/i)
  })
  it('maps statuses to friendly text', () => {
    expect(toErrorMessage(failure(403, { error: { message: 'x' } }))).toMatch(/permission/i)
    expect(toErrorMessage(failure(401, { error: { message: 'Not authenticated' } }))).toMatch(/session has expired/i)
    expect(toErrorMessage(failure(500, { error: { message: 'A database error occurred' } }))).toMatch(/server had a problem/i)
  })
  it('keeps the generic login failure message', () => {
    expect(toErrorMessage(failure(401, { error: { message: 'Incorrect username or password' } }))).toBe('Incorrect username or password')
  })
  it('uses the API message for 413 and other client errors', () => {
    expect(toErrorMessage(failure(413, { error: { message: 'This export would contain 91,566 encounters' } }))).toMatch(/91,566/)
    expect(toErrorMessage(failure(409, { error: { message: 'Patient 5 already exists' } }))).toBe('Patient 5 already exists')
  })
  it('names the first invalid field for a 422', () => {
    const err = failure(422, { error: { details: [{ loc: ['body', 'time_in_hospital'], msg: 'Input should be greater than or equal to 1' }] } })
    expect(toErrorMessage(err)).toBe('time_in_hospital: Input should be greater than or equal to 1')
  })
  it('is silent for a cancelled request', () => {
    expect(toErrorMessage({ code: 'ERR_CANCELED' })).toBe('')
  })
})

describe('toFieldErrors', () => {
  it('maps loc paths to field keys and strips "Value error, "', () => {
    const err = failure(422, { error: { details: [
      { loc: ['body', 'discharge_date'], msg: 'Value error, must not be before admission_date' },
      { loc: ['body', 'diagnoses', 0, 'icd9_code'], msg: 'invalid ICD-9 code format' },
      { loc: ['query', 'page_size'], msg: 'too big' },
    ] } })
    expect(toFieldErrors(err)).toEqual({ discharge_date: 'must not be before admission_date', 'diagnoses.0.icd9_code': 'invalid ICD-9 code format', page_size: 'too big' })
  })
  it('returns nothing when there are no details', () => {
    expect(toFieldErrors(failure(500, { error: { message: 'x', details: null } }))).toEqual({})
  })
})

describe('cleanParams', () => {
  it('drops empty values but keeps zero and false', () => {
    expect(cleanParams({ a: '', b: null, c: undefined, d: 0, e: false, f: 'x' })).toEqual({ d: 0, e: false, f: 'x' })
  })
})