import faulthandler
import sys
import time

faulthandler.dump_traceback_later(30, repeat=True)
print(f"BOOT {time.time():.1f}", file=sys.stderr, flush=True)

from mcp.server.fastmcp import FastMCP

print(f"MCP_IMPORT {time.time():.1f}", file=sys.stderr, flush=True)

mcp = FastMCP("iis-rag-debug")


@mcp.tool()
def search(query: str, k: int = 5) -> list[dict]:
    print(f"SEARCH_START {time.time():.1f}", file=sys.stderr, flush=True)
    import config

    print(f"CONFIG_IMPORT {time.time():.1f}", file=sys.stderr, flush=True)
    collection = config.get_collection()
    print(f"COLLECTION_READY {time.time():.1f}", file=sys.stderr, flush=True)
    result = collection.query(query_texts=[query], n_results=k)
    print(f"QUERY_DONE {time.time():.1f}", file=sys.stderr, flush=True)
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    return [
        {
            "text": text,
            "source": (meta or {}).get("source", ""),
            "page": (meta or {}).get("page", 0),
            "category": (meta or {}).get("category", ""),
            "score": round(1.0 - float(distance), 4),
        }
        for text, meta, distance in zip(documents, metadatas, distances)
    ]


if __name__ == "__main__":
    mcp.run()
