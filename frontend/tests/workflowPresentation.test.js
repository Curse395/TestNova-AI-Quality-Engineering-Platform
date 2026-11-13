import assert from 'node:assert/strict'
import test from 'node:test'
import {
  getTaskStatus,
  isCurrentWorkflowProject,
  isTaskTerminal,
  isWorkflowActive,
  isWorkflowTerminal,
  safeTaskDiagnostic,
  safeWorkflowOutput,
  selectAvailableProjectId,
  statusPresentation,
  testCaseEvidenceSources,
  workflowGeneratedCases,
  workflowTestCasesPageUrl,
} from '../src/pages/workflowPresentation.js'

test('workflow status labels and active/terminal states match the backend contracts', () => {
  assert.equal(statusPresentation('partially_completed').label, 'partially completed')
  assert.equal(statusPresentation('pending').label, 'pending')
  assert.equal(statusPresentation('cancelled').label, 'Unknown status')
  assert.equal(isWorkflowActive('pending'), true)
  assert.equal(isWorkflowActive('running'), true)
  assert.equal(isWorkflowActive('completed'), false)
  assert.equal(isWorkflowTerminal('failed'), true)
  assert.equal(isWorkflowTerminal('cancelled'), false)
})

test('task terminal states and dependency blocking match persisted task fields', () => {
  assert.equal(getTaskStatus({
    status: 'skipped',
    error_details: { code: 'DEPENDENCY_NOT_SATISFIED' },
  }), 'blocked')
  assert.equal(getTaskStatus({ status: 'skipped' }), 'skipped')
  assert.equal(isTaskTerminal('partial'), true)
  assert.equal(isTaskTerminal('retrying'), false)
})

test('project guards and test-case navigation preserve the selected project', () => {
  assert.equal(isCurrentWorkflowProject(12, '12'), true)
  assert.equal(isCurrentWorkflowProject(11, '12'), false)
  assert.equal(selectAvailableProjectId([{ id: 12 }, { id: 13 }], '13'), '13')
  assert.equal(selectAvailableProjectId([{ id: 12 }, { id: 13 }], '999'), '12')
  assert.equal(selectAvailableProjectId([], '12'), '')
  assert.equal(workflowTestCasesPageUrl(12), '/test-cases?project_id=12')
})

test('generated cases are read from final output with a persisted task-output fallback', () => {
  const finalCase = { id: 8, title: 'Persisted result' }
  assert.deepEqual(workflowGeneratedCases({
    final_output: { results: { test_generation: { test_cases: [finalCase] } } },
  }), [finalCase])

  const recoveredCase = { id: 9, title: 'Task result' }
  assert.deepEqual(workflowGeneratedCases({
    tasks: [{
      task_type: 'test_generation',
      output_data: { structured_data: { test_cases: [recoveredCase] } },
    }],
  }), [recoveredCase])
  assert.deepEqual(workflowGeneratedCases({}), [])
})

test('cited evidence metadata is preserved and missing source metadata is explicit', () => {
  const evidence = [{ chunk_id: 3, document_name: 'requirements.pdf', excerpt: 'Sign in.' }]
  assert.deepEqual(testCaseEvidenceSources({ evidence }), [
    { ...evidence[0], sourceUnavailable: false },
  ])
  assert.deepEqual(testCaseEvidenceSources({ evidence_chunk_ids: [4] }), [
    { chunk_id: 4, sourceUnavailable: true },
  ])
  assert.deepEqual(testCaseEvidenceSources({}), [])
})

test('diagnostics redact secrets and withhold technical stack details', () => {
  assert.deepEqual(safeTaskDiagnostic({
    code: 'GENERATION_FAILED',
    message: 'Provider rejected API key=secret-value',
  }), {
    code: 'GENERATION_FAILED',
    message: 'Provider rejected API key=[redacted]',
  })
  assert.equal(
    safeTaskDiagnostic({ message: 'Traceback (most recent call last): File "app.py"' }).message,
    'Detailed diagnostic information is withheld.',
  )
  assert.deepEqual(safeWorkflowOutput({
    api_token: 'private',
    private_key: 'private-key-value',
    result: 'Authorization: Bearer abc.def.ghi',
  }), {
    api_token: '[redacted]',
    private_key: '[redacted]',
    result: 'Authorization=[redacted]',
  })
})
