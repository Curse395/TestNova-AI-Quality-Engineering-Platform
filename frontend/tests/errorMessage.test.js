import assert from 'node:assert/strict'
import test from 'node:test'
import { getApiErrorMessage } from '../src/api/errorMessage.js'

test('extracts nested backend detail messages', () => {
  const error = {
    response: {
      data: {
        detail: { message: 'Reviewer could not access the test case.' },
      },
    },
  }

  assert.equal(
    getApiErrorMessage(error, 'fallback'),
    'Reviewer could not access the test case.',
  )
})

test('extracts FastAPI validation messages', () => {
  const error = {
    response: {
      data: {
        detail: [{ loc: ['body', 'title'], msg: 'Field required' }],
      },
    },
  }

  assert.equal(getApiErrorMessage(error, 'fallback'), 'Field required')
})

test('uses the fallback when the response has no message', () => {
  assert.equal(getApiErrorMessage({}, 'Request failed.'), 'Request failed.')
})

test('uses a clear access-denied message for an empty 403 response', () => {
  assert.equal(
    getApiErrorMessage({ response: { status: 403 } }, 'Request failed.'),
    'You do not have permission to access this resource.',
  )
})

test('uses a retry-friendly message for an empty 429 response', () => {
  assert.equal(
    getApiErrorMessage({ response: { status: 429 } }, 'Request failed.'),
    'Too many requests. Please try again shortly.',
  )
})

test('preserves backend messages for authorization, not-found, validation, and server errors', () => {
  for (const [status, detail] of [
    [401, 'Authentication required.'],
    [403, 'Project access denied.'],
    [429, 'Too many requests. Retry after one minute.'],
    [404, 'Workflow not found.'],
    [422, 'At least one scenario category is required.'],
    [500, 'Workflow could not be created.'],
  ]) {
    assert.equal(
      getApiErrorMessage({ response: { status, data: { detail } } }, 'Request failed.'),
      detail,
    )
  }
})
