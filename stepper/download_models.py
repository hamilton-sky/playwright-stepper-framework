"""
download_models.py — Pre-cache all ML models used by the Stepper healer.

Run once before using the framework offline or in CI:
    python stepper/download_models.py
"""

import pathlib

MODELS_DIR = pathlib.Path(__file__).parent / "models"
MODELS_DIR.mkdir(exist_ok=True)


def download_minilm():
    from sentence_transformers import SentenceTransformer
    dest = MODELS_DIR / "all-MiniLM-L6-v2"
    if dest.exists():
        print(f"[skip] all-MiniLM-L6-v2 already at {dest}")
        return
    print("[download] all-MiniLM-L6-v2 ...")
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    model.save(str(dest))
    print(f"[ok] saved to {dest}")


def download_cross_encoder():
    from sentence_transformers.cross_encoder import CrossEncoder
    dest = MODELS_DIR / "cross-encoder-ms-marco-MiniLM-L-6-v2"
    if dest.exists():
        print(f"[skip] cross-encoder already at {dest}")
        return
    print("[download] cross-encoder/ms-marco-MiniLM-L-6-v2 ...")
    model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    model.save(str(dest))
    print(f"[ok] saved to {dest}")


if __name__ == "__main__":
    download_minilm()
    download_cross_encoder()
    print("\nAll models ready.")
