import assert from 'node:assert/strict'
import { test } from 'node:test'
import { workflowStartValidationError } from '../src/pages/workflowValidation.js'

test('change risk analysis requires a non-empty trimmed summary', () => {
  const message = 'Enter a change summary before starting Change Risk Analysis.'

  assert.equal(workflowStartValidationError('change_risk_analysis', ''), message)
  assert.equal(workflowStartValidationError('change_risk_analysis', '   \n  '), message)
  assert.equal(
    workflowStartValidationError('change_risk_analysis', 'Change payment handling.'),
    '',
  )
})

test('other workflow types do not require a change summary', () => {
  assert.equal(workflowStartValidationError('test_generation', ''), '')
  assert.equal(workflowStartValidationError('full_qa_workflow', '   '), '')
})
