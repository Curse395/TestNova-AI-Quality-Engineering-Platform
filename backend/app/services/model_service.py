import math

from sentence_transformers import SentenceTransformer

class ModelService:
    EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
    EMBEDDING_DIMENSIONS = 384
    _embedding_model = None

    @classmethod
    def get_embedding_model(cls):
        if cls._embedding_model is None:
            cls._embedding_model = SentenceTransformer(cls.EMBEDDING_MODEL_NAME)
        return cls._embedding_model

    @classmethod
    def encode_embedding(cls, text: str) -> list[float]:
        encoded = cls.get_embedding_model().encode(
            text,
            normalize_embeddings=True,
        )
        values = encoded.tolist() if hasattr(encoded, "tolist") else list(encoded)
        if len(values) != cls.EMBEDDING_DIMENSIONS:
            raise ValueError("Embedding model returned an unexpected vector dimension")

        try:
            vector = [float(value) for value in values]
        except (TypeError, ValueError) as exc:
            raise ValueError("Embedding model returned an invalid vector") from exc
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Embedding model returned a non-finite vector")
        return vector