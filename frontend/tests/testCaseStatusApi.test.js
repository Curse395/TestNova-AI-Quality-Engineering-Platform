import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import { apiClient } from '../src/api/client.js'
import {
  approveProjectTestCase,
  rejectProjectTestCase,
} from '../src/api/projects.js'

test('approve and reject use the project-scoped status endpoints', async () => {
  const patch = mock.method(apiClient, 'patch', async (url) => ({
    data: {
      success: true,
      review_status: url.endsWith('/approve') ? 'approved' : 'rejected',
    },
  }))

  try {
    assert.equal((await approveProjectTestCase(3, 18)).review_status, 'approved')
    assert.equal((await rejectProjectTestCase(3, 18)).review_status, 'rejected')
    assert.deepEqual(patch.mock.calls.map(({ arguments: args }) => args[0]), [
      '/projects/3/test-cases/18/approve',
      '/projects/3/test-cases/18/reject',
    ])
  } finally {
    mock.restoreAll()
  }
})
