import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildWorkflowAgentDiagram,
  buildWorkflowAgentMap,
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
  workflowAgentCatalog,
  workflowMapEdges,
  workflowTestCasesPageUrl,
} from '../src/pages/workflowPresentation.js'

test('agent workflow blueprint includes every workflow and assistant agent', () => {
  const diagram = buildWorkflowAgentDiagram()
  assert.equal(diagram.length, workflowAgentCatalog.length)
  assert.equal(diagram.length, 10)
  assert.equal(diagram.find((agent) => agent.task_type === 'knowledge_agent').status, 'available')
  assert.equal(diagram.find((agent) => agent.task_type === 'review').status, 'standby')
})

test('agent workflow diagram overlays persisted states without hiding other agents', () => {
  const requirements = { id: 21, task_type: 'requirements_analysis', agent_name: 'requirements_analysis_agent', status: 'completed' }
  const generation = { id: 22, task_type: 'test_generation', agent_name: 'test_generation_agent', status: 'running' }
  const diagram = buildWorkflowAgentDiagram([requirements, generation])

  assert.equal(diagram.length, 10)
  assert.equal(diagram.find((agent) => agent.task_type === 'requirements_analysis').workflowTaskId, 21)
  assert.equal(diagram.find((agent) => agent.task_type === 'test_generation').status, 'running')
  assert.equal(diagram.find((agent) => agent.task_type === 'review').status, 'not_in_run')
  assert.equal(diagram.find((agent) => agent.task_type === 'knowledge_agent').status, 'available')
})

test('agent workflow map contains only agent roles and the orchestrator', () => {
  const { nodes, edges } = buildWorkflowAgentMap([
    { id: 21, task_type: 'requirements_analysis', agent_name: 'requirements_analysis_agent', status: 'completed' },
    { id: 22, task_type: 'bug_analysis', agent_name: 'bug_analysis_agent', status: 'completed' },
    { id: 23, task_type: 'test_generation', agent_name: 'test_generation_agent', status: 'running' },
    { id: 24, task_type: 'deterministic_validation', agent_name: 'workflow_validation_service', status: 'pending' },
    { id: 25, task_type: 'aggregation', agent_name: 'workflow_aggregator', status: 'pending' },
  ])
  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  const edgeByPair = new Map(edges.map((edge) => [`${edge.from}->${edge.to}`, edge]))

  assert.equal(nodes.length, 10)
  assert.equal(nodes.every((node) => ['agent', 'orchestrator'].includes(node.kind)), true)
  assert.equal(nodeById.get('requirements_analysis').workflowTaskId, 21)
  assert.equal(nodeById.get('agent_orchestrator').workflowTaskId, 25)
  assert.equal(nodeById.get('agent_orchestrator').status, 'pending')
  assert.equal(nodeById.get('knowledge_agent').status, 'available')
  assert.equal(nodeById.get('knowledge_agent').workflowTaskId, null)
  assert.equal(edgeByPair.get('bug_analysis->test_generation').active, true)
  assert.equal(edgeByPair.get('requirements_analysis->bug_analysis').active, false)
  assert.equal(edgeByPair.get('agent_orchestrator->test_analysis').kind, 'dispatch')
  assert.equal(edgeByPair.get('review->test_generation').kind, 'feedback')
  assert.equal(workflowMapEdges.some((edge) => edge.from === 'test_analysis' && edge.to === 'quality_insights'), true)
})

test('unknown persisted workflow tasks remain inspectable in the agent map', () => {
  const { nodes } = buildWorkflowAgentMap([
    { id: 99, task_type: 'custom_analysis', agent_name: 'custom_agent', status: 'completed' },
  ])
  const extra = nodes.find((node) => node.id === 'additional-agent-99')
  assert.equal(extra.workflowTaskId, 99)
  assert.equal(extra.agent_name, 'custom_agent')
})

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
