export function selectTestGenerationMetrics(metrics, scope, projectId) {
  if (scope === 'project' && projectId != null && String(projectId)) {
    return {
      metrics: metrics?.by_project?.[String(projectId)] ?? null,
      scopeLabel: 'Selected project',
    }
  }
  return {
    metrics: metrics?.workspace ?? null,
    scopeLabel: 'Workspace',
  }
}

export function testGenerationMetricRows(metrics) {
  const coverage = metrics?.requirement_case_coverage_percent
  const linked = metrics?.linked_explicit_requirements
  const explicit = metrics?.explicit_requirements
  const generatedCases = metrics?.persisted_ai_generated_test_cases
  const generationRuns = metrics?.generation_runs_with_saved_cases

  return [
    {
      label: 'Current requirement case coverage',
      value: coverage == null ? 'Unavailable' : `${coverage}%`,
      detail: Number.isInteger(linked) && Number.isInteger(explicit) && explicit > 0
        ? `${linked} of ${explicit} explicit requirements link to at least one persisted test case. Current traceability, not coverage uplift.`
        : explicit === 0
          ? 'No explicit requirements are available; a coverage percentage is not defined.'
          : 'Requirement traceability data is unavailable.',
    },
    {
      label: 'Persisted AI-generated test cases',
      value: Number.isInteger(generatedCases) ? String(generatedCases) : 'Unavailable',
      detail: 'Count of persisted test cases associated with a generation run. This does not imply execution or passing results.',
    },
    {
      label: 'Generation workflows with saved cases',
      value: Number.isInteger(generationRuns) ? String(generationRuns) : 'Unavailable',
      detail: 'Distinct workflows with cases from completed or partial generation runs; retries within one workflow count once. Standalone generation runs count once each.',
    },
  ]
}
