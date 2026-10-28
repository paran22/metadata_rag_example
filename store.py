"""Chroma 컬렉션 생성과 메타데이터 필터(where) 조립."""
import sys

# Streamlit Cloud의 기본 sqlite3가 Chroma 요구 버전보다 낮을 때 pysqlite3로 바꿔 끼운다.
try:
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import chromadb

from chunks import build_chunks

COLLECTION = "hanbit_fee"


def build_collection(embedding_function):
    """메모리 위 Chroma에 청크를 임베딩해 넣는다. 앱이 뜰 때마다 새로 만든다."""
    client = chromadb.EphemeralClient()
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    col = client.create_collection(
        COLLECTION,
        embedding_function=embedding_function,
        configuration={"hnsw": {"space": "cosine"}},
    )
    ids, documents, metadatas = build_chunks()
    col.add(ids=ids, documents=documents, metadatas=metadatas)
    return col


def resolve_version(col, yyyymmdd):
    """기준일에 유효한 버전 = 시행일이 기준일 이전인 버전 중 가장 늦은 것. 없으면 None.

    Chroma where로는 '최댓값'을 고를 수 없어서, 시행일 목록을 먼저 읽고 코드에서 고른다.
    """
    starts = {m["effective_from"]: m["source"] for m in col.get(include=["metadatas"])["metadatas"]}
    valid = [s for s in starts if s <= yyyymmdd]
    if not valid:
        return None
    best = max(valid)
    return {"effective_from": best, "source": starts[best]}


def search(col, question, k, where=None):
    res = col.query(query_texts=[question], n_results=k, where=where,
                    include=["documents", "metadatas", "distances"])
    return [
        {"id": i, "document": d, "metadata": m, "distance": dist}
        for i, d, m, dist in zip(res["ids"][0], res["documents"][0],
                                 res["metadatas"][0], res["distances"][0])
    ]
