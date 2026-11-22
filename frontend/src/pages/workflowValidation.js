export function workflowStartValidationError(workflowType, changeSummary) {
  if (
    workflowType === 'change_risk_analysis'
    && (typeof changeSummary !== 'string' || changeSummary.trim().length === 0)
  ) {
    return 'Enter a change summary before starting Change Risk Analysis.'
  }
  return ''
}
