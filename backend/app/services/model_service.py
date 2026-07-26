from sentence_transformers import SentenceTransformer

class ModelService:
    _embedding_model=None

    @classmethod 
    def get_embedding_model(cls):
        if cls._embedding_model is None:
            print("Loading SentenceTransformer model...")
            cls._embedding_model=SentenceTransformer("all-MiniLM-L6-v2")
            print("Model Loaded successfully.")
        return cls._embedding_model