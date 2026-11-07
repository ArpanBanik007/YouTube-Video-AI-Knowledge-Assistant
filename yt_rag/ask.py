import os
import re
import sys
import time
import requests
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient

load_dotenv()
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

# ================= CONFIG =================
GROQ_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

COLLECTION = "yt_rag"
DB_PATH = "./qdrant_db"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

TOP_K = 8
MIN_SCORE = 0.12
STRONG_SCORE = 0.22      # RAG ~0.28, Japan ~0.17
RELATIVE_GAP = 0.20
DEBUG = False            # tuning-er shomoy True koro
USE_GEMINI_FALLBACK = True

SYSTEM_PROMPT = (
    "You answer questions using ONLY the numbered transcript excerpts provided. "
    "The excerpts may be in English, Hindi, or Hinglish (transcription may contain errors). "
    "Reply in the same language as the question: English question -> English; "
    "Hindi (Devanagari) question -> Hindi in Devanagari; "
    "Hinglish/Bengali-in-Roman question -> Hinglish written ENTIRELY in Roman script "
    "(never use Devanagari characters in that case, translate transcript words into Roman). "
    "Cite sources inline like [1], [2] using plain square brackets only. "
    "Do not state relationships or conclusions that are not explicitly in the excerpts. "
    "If the excerpts do not contain the answer, say so briefly in the user's language "
    "and do NOT cite anything. Do not use outside knowledge."
)


def fmt(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def link(p):
    return f"https://youtu.be/{p['video_id']}?t={int(p['start'])}"


def search(embedder, client, question):
    vec = embedder.encode(question).tolist()
    res = client.query_points(COLLECTION, query=vec, limit=TOP_K).points
    if DEBUG:
        print("  [debug] top scores:", [round(r.score, 2) for r in res[:5]])
    if not res:
        return []
    best = res[0].score
    if best < STRONG_SCORE:
        return []
    return [r for r in res if r.score >= MIN_SCORE and r.score >= best - RELATIVE_GAP]


def build_context(hits):
    return "\n\n".join(
        f"[{i}] (Video: {h.payload['video_title']}, "
        f"{fmt(h.payload['start'])}-{fmt(h.payload['end'])})\n{h.payload['text']}"
        for i, h in enumerate(hits, 1)
    )


def clean(text):
    return text.replace("【", "[").replace("】", "]").strip()


def call_groq(question, context):
    if not GROQ_KEY:
        raise RuntimeError("GROQ_API_KEY set nai")
    r = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_KEY}"},
        json={
            "model": GROQ_MODEL,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Excerpts:\n{context}\n\nQuestion: {question}"},
            ],
        },
        timeout=(10, 60),
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return clean(r.json()["choices"][0]["message"]["content"])


def call_gemini(question, context):
    if not GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY set nai")
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {"role": "user", "parts": [{"text": f"Excerpts:\n{context}\n\nQuestion: {question}"}]}
        ],
        "generationConfig": {"temperature": 0.2},
    }
    headers = {"x-goog-api-key": GEMINI_KEY, "Content-Type": "application/json"}
    r = requests.post(
        GEMINI_URL.format(model=GEMINI_MODEL),
        headers=headers, json=body, timeout=(10, 45),
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError("Gemini kono answer dayni")
    parts = cands[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise RuntimeError("response khali")
    return clean(text)


def generate(question, hits):
    """Groq age. Groq fail hole Gemini fallback. Return (provider, answer, seconds)."""
    context = build_context(hits)

    t0 = time.time()
    try:
        return "Groq", call_groq(question, context), time.time() - t0
    except Exception as e:
        groq_err = str(e)

    if USE_GEMINI_FALLBACK and GEMINI_KEY:
        print(f"  (Groq fail: {groq_err[:80]} -> Gemini fallback...)")
        t0 = time.time()
        try:
            return "Gemini", call_gemini(question, context), time.time() - t0
        except Exception as e:
            raise RuntimeError(f"Groq: {groq_err} | Gemini: {e}")
    raise RuntimeError(f"Groq: {groq_err}")


def cited_numbers(answer, max_n):
    nums = {int(m) for m in re.findall(r"\[(\d+)\]", answer)}
    return sorted(n for n in nums if 1 <= n <= max_n)


def main():
    if not GROQ_KEY and not GEMINI_KEY:
        print(".env-e kompokkhe ekta key (GROQ_API_KEY ba GEMINI_API_KEY) set koro")
        return
    print("Loading...")
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    client = QdrantClient(path=DB_PATH)
    print("Ready. Question likho (exit likhle bondho).\n")

    while True:
        q = input("Q> ").strip()
        if q.lower() in {"exit", "quit", ""}:
            break

        hits = search(embedder, client, q)
        if not hits:
            print("\nPlaylist-e ei topic-er tathya paoya jayni.\n")
            continue

        try:
            provider, answer, secs = generate(q, hits)
        except Exception as e:
            print(f"\nLLM error: {e}\n")
            continue

        print(f"\n[{provider}, {secs:.1f}s]\n{answer}")

        nums = cited_numbers(answer, len(hits))
        if nums:
            print("\nSources:")
            for n in nums:
                h = hits[n - 1]
                p = h.payload
                print(f"  [{n}] {p['video_title']} @ {fmt(p['start'])} (score {h.score:.2f})")
                print(f"      {link(p)}")
        print()


if __name__ == "__main__":
    main()