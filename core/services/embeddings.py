import numpy as np
from django.conf import settings

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(settings.SBERT_MODEL_NAME)
    return _model


def chunk_text(text, chunk_size=500, overlap=100):
    """Split text into overlapping chunks of ~chunk_size characters."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def embed_text(text):
    """Embed a single text, chunking and mean-pooling if needed. Returns np.ndarray(384,)."""
    model = _get_model()
    chunks = chunk_text(text)
    embeddings = model.encode(chunks, show_progress_bar=False)
    return embeddings.mean(axis=0)


def embed_texts_batch(texts, batch_size=256):
    """Embed multiple texts. Returns np.ndarray(n, 384)."""
    model = _get_model()
    all_vectors = []
    for text in texts:
        chunks = chunk_text(text)
        chunk_embeddings = model.encode(chunks, show_progress_bar=False)
        all_vectors.append(chunk_embeddings.mean(axis=0))
    return np.array(all_vectors)


def compute_umap_projection(vectors):
    """Reduce vectors to 2D with UMAP. Returns np.ndarray(n, 2)."""
    import umap
    n_neighbors = min(15, len(vectors) - 1)
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=max(2, n_neighbors),
        min_dist=0.1,
        metric='cosine',
        random_state=42,
    )
    return reducer.fit_transform(vectors)


def compute_hdbscan_clusters(vectors):
    """Cluster vectors with HDBSCAN. Returns np.ndarray(n,) of labels (-1 = noise)."""
    import hdbscan
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=5,
        min_samples=3,
        metric='euclidean',
    )
    clusterer.fit(vectors)
    return clusterer.labels_
