from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient

import ask  # ask.py-r search, generate, config reuse hobe

state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["embedder"] = SentenceTransformer(ask.EMBEDDING_MODEL)
    state["client"] = QdrantClient(path=ask.DB_PATH)
    yield
    state["client"].close()


app = FastAPI(title="YouTube RAG API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask_question(req: AskRequest):
    q = req.question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Question khali")

    hits = ask.search(state["embedder"], state["client"], q)
    if not hits:
        return {
            "answer": "Playlist-e ei topic-er tathya paoya jayni.",
            "provider": None,
            "seconds": 0,
            "sources": [],
        }

    try:
        provider, answer, secs = ask.generate(q, hits)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    sources = []
    for n in ask.cited_numbers(answer, len(hits)):
        h = hits[n - 1]
        p = h.payload
        sources.append({
            "n": n,
            "title": p["video_title"],
            "video_id": p["video_id"],
            "start": int(p["start"]),
            "timestamp": ask.fmt(p["start"]),
            "url": ask.link(p),
            "score": round(h.score, 2),
            "text": p["text"][:220],
        })

    return {
        "answer": answer,
        "provider": provider,
        "seconds": round(secs, 1),
        "sources": sources,
    }