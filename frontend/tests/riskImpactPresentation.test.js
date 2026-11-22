import assert from 'node:assert/strict'
import { test } from 'node:test'
import { potentialImpactHighlights } from '../src/pages/riskImpactPresentation.js'

test('potential impact descriptions are grouped, deduplicated, and linked to findings', () => {
  const highlights = potentialImpactHighlights([
    {
      id: 'risk-a',
      kind: 'ai_inferred',
      description: 'Booking flow risk',
      potential_impact: [
        'Appointment scheduling conflicts may result in double booking.',
        'Customer data may be lost or corrupted.',
        'An impact without a supported category.',
        'Incorrect duplicate billing charges may create financial discrepancies.',
      ],
    },
    {
      id: 'risk-b',
      kind: 'ai_inferred',
      description: 'Reservation processing risk',
      potential_impact: [
        ' customer   data may be lost or corrupted. ',
        'Unauthorized access could expose patient records.',
      ],
    },
  ])

  assert.deepEqual(highlights.map(({ name, descriptionCount, findingCount }) => ({
    name,
    descriptionCount,
    findingCount,
  })), [
    { name: 'Data Integrity', descriptionCount: 1, findingCount: 2 },
    { name: 'Security Vulnerabilities', descriptionCount: 1, findingCount: 1 },
    { name: 'Scheduling Conflicts', descriptionCount: 1, findingCount: 1 },
    { name: 'Financial Discrepancies', descriptionCount: 1, findingCount: 1 },
    { name: 'Other Impacts', descriptionCount: 1, findingCount: 1 },
  ])
  assert.equal(highlights[0].descriptions[0].description, 'Customer data may be lost or corrupted.')
  assert.deepEqual(highlights[0].descriptions[0].findingTitles, [
    'Booking flow risk',
    'Reservation processing risk',
  ])
  assert.equal(highlights.at(-1).descriptions[0].description, 'An impact without a supported category.')
})

test('impacts without a supported theme remain under Other Impacts', () => {
  assert.deepEqual(potentialImpactHighlights([
    { id: 'observed', kind: 'observed_fact', potential_impact: ['Observed execution issue.'] },
    { id: 'none', kind: 'ai_inferred', potential_impact: [] },
    { id: 'other', kind: 'ai_inferred', potential_impact: ['Service continuity may be reduced.'] },
  ]), [{
    name: 'Other Impacts',
    descriptions: [{
      description: 'Service continuity may be reduced.',
      findingTitles: ['Untitled risk finding'],
    }],
    descriptionCount: 1,
    findingCount: 1,
  }])
})
