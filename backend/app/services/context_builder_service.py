from app.core.config import settings


class ContextBuilderService:
    def build_context(
        self,
        retrieved_chunks: list[dict[str, object]],
        token_budget: int | None = None,
    ) -> dict[str, object]:
        budget = settings.CONTEXT_TOKEN_BUDGET if token_budget is None else token_budget
        if budget < 1:
            raise ValueError("Context token budget must be at least one")

        context_parts: list[str] = []
        sources: list[dict[str, object]] = []
        seen_chunk_ids: set[int] = set()
        total_chars = 0
        character_budget = budget * 4

        for chunk in retrieved_chunks:
            content = str(chunk.get("content") or "").strip()
            if not content:
                continue

            chunk_id = chunk.get("chunk_id")
            if isinstance(chunk_id, int) and chunk_id in seen_chunk_ids:
                continue

            source_label = (
                f"[Source: {chunk.get('document_name', 'Unknown document')}; "
                f"document_id={chunk.get('document_id', 'unknown')}; "
                f"chunk_id={chunk_id if chunk_id is not None else 'unknown'}]"
            )
            source_block = f"{source_label}\n{content}"
            additional_chars = len(source_block) + (2 if context_parts else 0)
            if total_chars + additional_chars > character_budget:
                continue

            context_parts.append(source_block)
            total_chars += additional_chars
            sources.append(
                {
                    "document_id": chunk.get("document_id"),
                    "document_name": chunk.get("document_name"),
                    "chunk_id": chunk_id,
                    "source_type": chunk.get("source_type", "document"),
                    "source_metadata": chunk.get("source_metadata") or {},
                    "score": chunk.get("score"),
                    "similarity": chunk.get("similarity"),
                    "distance": chunk.get("distance"),
                    "excerpt": content,
                }
            )
            if isinstance(chunk_id, int):
                seen_chunk_ids.add(chunk_id)

        return {
            "context": "\n\n".join(context_parts),
            "chunk_count": len(context_parts),
            "token_budget": budget,
            "sources": sources,
        }
