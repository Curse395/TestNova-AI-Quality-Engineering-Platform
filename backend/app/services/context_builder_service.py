class ContextBuilderService:
    def build_context(self, retrieved_chunks: list[dict[str, object]], token_budget: int = 1000) -> dict[str, object]:
        context_parts: list[str] = []
        total_chars = 0

        for chunk in retrieved_chunks:
            content = str(chunk.get("content", ""))
            if not content:
                continue
            if total_chars + len(content) > token_budget * 4:
                break
            context_parts.append(content)
            total_chars += len(content)

        return {
            "context": "\n\n".join(context_parts),
            "chunk_count": len(context_parts),
            "token_budget": token_budget,
        }
