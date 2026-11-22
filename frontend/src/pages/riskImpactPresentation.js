const IMPACT_GROUPS = [
  {
    name: 'Data Integrity',
    pattern: /\b(?:data|records?|information)\b.{0,50}\b(?:corrupt(?:ion|ed)?|inconsisten(?:t|cy)|integrity|loss|lost|overwrit(?:e|es|ten)|duplicat(?:e|es|ed|ion))\b|\b(?:corrupt(?:ion|ed)?|inconsisten(?:t|cy)|integrity|loss|lost|overwrit(?:e|es|ten)|duplicat(?:e|es|ed|ion))\b.{0,50}\b(?:data|records?|information)\b/i,
  },
  {
    name: 'Security Vulnerabilities',
    pattern: /\b(?:security|unauthori[sz]ed|authentication|authorization|access control|credential|vulnerabilit(?:y|ies)|injection|expos(?:e|es|ed|ure))\b/i,
  },
  {
    name: 'Scheduling Conflicts',
    pattern: /\b(?:scheduling|schedule|appointment|booking)\b.{0,50}\b(?:conflict|overlap|double[ -]?book(?:ed|ing)?)\b|\b(?:conflict|overlap|double[ -]?book(?:ed|ing)?)\b.{0,50}\b(?:scheduling|schedule|appointment|booking)\b/i,
  },
  {
    name: 'Financial Discrepancies',
    pattern: /\b(?:financial|billing|invoice|payment|charge|fee|tax|balance|amount)\b.{0,50}\b(?:discrepanc\w*|mismatch\w*|incorrect|inaccurate|duplicate|overcharg\w*|undercharg\w*|miscalculat\w*)\b|\b(?:discrepanc\w*|mismatch\w*|incorrect|inaccurate|duplicate|overcharg\w*|undercharg\w*|miscalculat\w*)\b.{0,50}\b(?:financial|billing|invoice|payment|charge|fee|tax|balance|amount)\b/i,
  },
]

export function potentialImpactHighlights(risks) {
  if (!Array.isArray(risks)) return []

  const groups = new Map()
  risks.forEach((risk, riskIndex) => {
    if (risk?.kind !== 'ai_inferred' || !Array.isArray(risk.potential_impact)) return
    const findingKey = risk.id ?? `risk-index-${riskIndex}`
    const findingTitle = typeof risk.description === 'string' && risk.description.trim()
      ? risk.description
      : 'Untitled risk finding'

    for (const rawDescription of risk.potential_impact) {
      if (typeof rawDescription !== 'string' || !rawDescription.trim()) continue
      const descriptionKey = rawDescription.trim().replace(/\s+/g, ' ').toLowerCase()
      const groupName = IMPACT_GROUPS.find(({ pattern }) => pattern.test(rawDescription))?.name
        || 'Other Impacts'
      if (!groups.has(groupName)) groups.set(groupName, new Map())
      const groupImpacts = groups.get(groupName)
      if (!groupImpacts.has(descriptionKey)) {
        groupImpacts.set(descriptionKey, { description: rawDescription, findings: new Map() })
      }
      groupImpacts.get(descriptionKey).findings.set(findingKey, findingTitle)
    }
  })

  return [...IMPACT_GROUPS.map(({ name }) => name), 'Other Impacts'].flatMap((name) => {
    const impacts = groups.get(name)
    if (!impacts?.size) return []
    const descriptions = [...impacts.values()].map((impact) => ({
      description: impact.description,
      findingTitles: [...new Set(impact.findings.values())],
    }))
    const findingCount = new Set(
      [...impacts.values()].flatMap((impact) => [...impact.findings.keys()]),
    ).size
    return [{ name, descriptions, descriptionCount: descriptions.length, findingCount }]
  })
}
