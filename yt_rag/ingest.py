import os
import sys
import uuid
import yt_dlp
from dotenv import load_dotenv
from faster_whisper import WhisperModel
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue,
)

load_dotenv()
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ================= CONFIG =================
COLLECTION = "yt_rag"
DB_PATH = "./qdrant_db"
AUDIO_DIR = "./audio"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE") or None
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
VECTOR_SIZE = 384
CHUNK_SECONDS = 45
OVERLAP_SEGMENTS = 1

DEFAULT_URLS = [
    "https://youtu.be/rJ1Qao09CFI",
    "https://youtu.be/JK-z9Lptx60",
    "https://youtu.be/4UYmdLolCX4",
]


def resolve_videos(urls):
    videos, seen = [], set()
    opts = {"extract_flat": True, "quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        for url in urls:
            info = ydl.extract_info(url, download=False)
            for e in (info.get("entries") or [info]):
                if not e or not e.get("id") or e["id"] in seen:
                    continue
                seen.add(e["id"])
                videos.append({"id": e["id"], "title": e.get("title") or e["id"]})
    return videos


def download_audio(video_id):
    os.makedirs(AUDIO_DIR, exist_ok=True)
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": os.path.join(AUDIO_DIR, "%(id)s.%(ext)s"),
        "quiet": True,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
        return ydl.prepare_filename(info), info.get("title")


def make_chunks(segments):
    chunks, buf = [], []

    def flush():
        chunks.append({
            "start": buf[0]["start"],
            "end": buf[-1]["end"],
            "text": " ".join(s["text"].strip() for s in buf),
        })

    for seg in segments:
        buf.append(seg)
        if buf[-1]["end"] - buf[0]["start"] >= CHUNK_SECONDS:
            flush()
            buf = buf[-OVERLAP_SEGMENTS:] if OVERLAP_SEGMENTS else []
    if buf and (not chunks or buf[-1]["end"] > chunks[-1]["end"]):
        flush()
    return chunks


def already_ingested(client, video_id):
    n = client.count(
        COLLECTION,
        count_filter=Filter(must=[FieldCondition(key="video_id", match=MatchValue(value=video_id))]),
        exact=True,
    ).count
    return n > 0


def main():
    urls = sys.argv[1:] or DEFAULT_URLS

    client = QdrantClient(path=DB_PATH)
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )

    videos = resolve_videos(urls)
    print(f"{len(videos)} ta video paoya gelo")

    todo = []
    for v in videos:
        if already_ingested(client, v["id"]):
            print(f"Skip (age-i stored): {v['title']}")
        else:
            todo.append(v)
    if not todo:
        print("Notun kichu nai. Done.")
        return

    print(f"Models load hocche (whisper={WHISPER_MODEL})...")
    whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    embedder = SentenceTransformer(EMBEDDING_MODEL)

    for i, v in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {v['title']}")
        print("  Audio download...")
        path, title = download_audio(v["id"])
        title = title or v["title"]

        print("  Transcribe hocche (slow, wait koro)...")
        seg_iter, info = whisper.transcribe(
            path,
            language=WHISPER_LANGUAGE,
            vad_filter=True,
            beam_size=1,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
        )
        print(f"  Detected language: {info.language} ({info.language_probability:.2f})")
        print(f"  Video duration: {int(info.duration)}s")

        segments = []
        for s in seg_iter:
            segments.append({"start": s.start, "end": s.end, "text": s.text})
            print(f"\r  {int(s.end)}s / {int(info.duration)}s transcribed", end="", flush=True)
        print()

        if not segments:
            print("  Kono speech paoya jayni, skip")
            continue

        print("  Sample:", segments[min(3, len(segments) - 1)]["text"].strip())

        chunks = make_chunks(segments)
        print(f"  {len(segments)} segments -> {len(chunks)} chunks")

        vectors = embedder.encode([c["text"] for c in chunks], show_progress_bar=False)
        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vec.tolist(),
                payload={
                    "video_id": v["id"],
                    "video_title": title,
                    "start": round(c["start"], 2),
                    "end": round(c["end"], 2),
                    "text": c["text"],
                },
            )
            for c, vec in zip(chunks, vectors)
        ]
        client.upsert(COLLECTION, points=points)
        print("  Qdrant-e stored")

        try:
            os.remove(path)
        except OSError:
            pass

    print("\nDone!")


if __name__ == "__main__":
    main()