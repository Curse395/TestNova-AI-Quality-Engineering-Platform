from app.core.config import settings


class ContextBuilderService:
    def build_context_batches(
        self,
        retrieved_chunks: list[dict[str, object]],
        token_budget: int | None = None,
    ) -> list[list[dict[str, object]]]:
        """Partition source chunks so every non-empty excerpt fits a bounded context.

        Oversized individual chunks are sent as ordered excerpts in separate
        contexts while retaining the original chunk ID for evidence provenance.
        """
        budget = settings.CONTEXT_TOKEN_BUDGET if token_budget is None else token_budget
        if budget < 1:
            raise ValueError("Context token budget must be at least one")

        pieces: list[dict[str, object]] = []
        content_limit = max(1, budget * 4 - 256)
        for chunk in retrieved_chunks:
            content = str(chunk.get("content") or "").strip()
            if not content:
                continue
            if len(content) <= content_limit:
                pieces.append(chunk)
                continue
            for offset in range(0, len(content), content_limit):
                pieces.append({**chunk, "content": content[offset : offset + content_limit]})

        batches: list[list[dict[str, object]]] = []
        current: list[dict[str, object]] = []
        for piece in pieces:
            candidate = current + [piece]
            built = self.build_context(candidate, token_budget=budget)
            if len(built["sources"]) == len(candidate):
                current = candidate
                continue
            if current:
                batches.append(current)
                current = []
            single = self.build_context([piece], token_budget=budget)
            if single["sources"]:
                current = [piece]
        if current:
            batches.append(current)
        return batches

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
