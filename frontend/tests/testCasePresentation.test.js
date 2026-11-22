import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  reviewStatusDistributionData,
  reviewStatusLabel,
  testCaseDistributionData,
} from '../src/pages/testCasePresentation.js'

test('review status labels preserve known states and safely label historical values', () => {
  assert.equal(reviewStatusLabel('draft'), 'Draft')
  assert.equal(reviewStatusLabel('APPROVED'), 'Approved')
  assert.equal(reviewStatusLabel('rejected'), 'Rejected')
  assert.equal(reviewStatusLabel('  '), 'Status unavailable')
  assert.equal(reviewStatusLabel('legacy-state'), 'Other (legacy-state)')
})

test('review status chart percentages are calculated from persisted status counts', () => {
  assert.deepEqual(
    reviewStatusDistributionData({
      draft: 2,
      approved: 1,
      rejected: 1,
      other: 1,
      missing: 0,
      blank: 0,
    }),
    [
      { name: 'Draft', value: 2, percentage: 40 },
      { name: 'Approved', value: 1, percentage: 20 },
      { name: 'Rejected', value: 1, percentage: 20 },
    ],
  )
  assert.deepEqual(reviewStatusDistributionData({}), [])
})

test('category and priority charts use canonical labels and stable category ordering', () => {
  assert.deepEqual(
    testCaseDistributionData({
      critical: 2,
      edge: 4,
      boundary: 3,
      negative: 2,
      positive: 5,
      other: 1,
      missing: 0,
      blank: 0,
    }, 'category'),
    [
      { name: 'Positive', value: 5 },
      { name: 'Negative', value: 2 },
      { name: 'Boundary', value: 3 },
      { name: 'Edge', value: 4 },
      { name: 'Other', value: 1 },
    ],
  )
  assert.deepEqual(
    testCaseDistributionData({ critical: 1, high: 3, medium: 2, low: 4, other: 9 }, 'priority'),
    [
      { name: 'Low', value: 4 },
      { name: 'Medium', value: 2 },
      { name: 'High', value: 3 },
      { name: 'Critical', value: 1 },
    ],
  )
})

test('test-case chart mappings omit empty values and combine equivalent raw keys once', () => {
  assert.deepEqual(
    testCaseDistributionData({
      Positive: 2,
      positive: 3,
      negative: 0,
      ' ': 7,
      missing: 1,
      blank: 1,
      null: 1,
      undefined: 1,
      obsolete: 4,
    }, 'category'),
    [{ name: 'Positive', value: 5 }],
  )
  assert.deepEqual(
    testCaseDistributionData({ draft: 2, Draft: 3, approved: null, rejected: 0 }, 'reviewStatus'),
    [
      { name: 'Draft', value: 5 },
    ],
  )
})

test('review status percentages retain the persisted total when hidden statuses exist', () => {
  assert.deepEqual(
    reviewStatusDistributionData({ draft: 2, approved: 1, rejected: 1, other: 4, blank: 2 }),
    [
      { name: 'Draft', value: 2, percentage: 20 },
      { name: 'Approved', value: 1, percentage: 10 },
      { name: 'Rejected', value: 1, percentage: 10 },
    ],
  )
})
