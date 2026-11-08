from collections import Counter
from typing import Any, Mapping, Sequence


def summarize_execution_statuses(
    executions: Sequence[Mapping[str, Any]],
    unknown_status: str = "unknown",
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for execution in executions:
        status = execution.get("status", unknown_status)
        counts[status if isinstance(status, str) else unknown_status] += 1
    return dict(counts)
