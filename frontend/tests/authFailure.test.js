import assert from 'node:assert/strict'
import test from 'node:test'
import { handleUnauthorizedResponse } from '../src/api/errorMessage.js'

test('401 responses clear the access token and emit the unauthorized event', () => {
  const previousStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  const removedKeys = []
  const events = []

  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: () => 'offline-invalid-token',
      removeItem: (key) => removedKeys.push(key),
    },
  })
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: { dispatchEvent: (event) => events.push(event) },
  })

  try {
    assert.equal(
      handleUnauthorizedResponse({ response: { status: 401 } }),
      true,
    )

    assert.deepEqual(removedKeys, ['access_token'])
    assert.equal(events.length, 1)
    assert.equal(events[0].type, 'testnova:unauthorized')
    assert.equal(
      handleUnauthorizedResponse({ response: { status: 403 } }),
      false,
    )
    assert.equal(removedKeys.length, 1)
    assert.equal(events.length, 1)
  } finally {
    if (previousStorage) {
      Object.defineProperty(globalThis, 'localStorage', previousStorage)
    } else {
      delete globalThis.localStorage
    }
    if (previousWindow) {
      Object.defineProperty(globalThis, 'window', previousWindow)
    } else {
      delete globalThis.window
    }
  }
})
