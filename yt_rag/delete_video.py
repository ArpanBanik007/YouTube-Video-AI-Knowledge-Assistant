import sys
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, FilterSelector

COLLECTION = "yt_rag"
client = QdrantClient(path="./qdrant_db")

for vid in sys.argv[1:]:
    client.delete(
        COLLECTION,
        points_selector=FilterSelector(
            filter=Filter(must=[FieldCondition(key="video_id", match=MatchValue(value=vid))])
        ),
    )
    print("deleted:", vid)