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