import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import { apiClient } from '../src/api/client.js'
import { resumeWorkflow } from '../src/api/workflows.js'

test('resumeWorkflow posts to the project and workflow resume endpoint', async () => {
  const resumed = { id: 42, project_id: 7, status: 'pending' }
  const post = mock.method(apiClient, 'post', async () => ({
    data: { success: true, data: resumed },
  }))

  try {
    assert.deepEqual(await resumeWorkflow(7, 42), resumed)
    assert.deepEqual(post.mock.calls.map(({ arguments: args }) => args), [
      ['/projects/7/workflows/42/resume'],
    ])
  } finally {
    mock.restoreAll()
  }
})

test('resumeWorkflow rejects malformed API responses', async () => {
  mock.method(apiClient, 'post', async () => ({ data: { success: true } }))

  try {
    await assert.rejects(resumeWorkflow(7, 42), /Unexpected workflow response/)
  } finally {
    mock.restoreAll()
  }
})
