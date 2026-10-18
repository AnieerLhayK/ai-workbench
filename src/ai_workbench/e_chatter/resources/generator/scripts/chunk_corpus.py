from __future__ import annotations

from typing import Dict, List


def chunk_documents(documents: List[Dict], max_chars: int = 1200) -> List[Dict]:
    chunks: List[Dict] = []
    chunk_index = 1

    for doc in documents:
        paragraphs = [p.strip() for p in doc["text"].split("\n\n") if p.strip()]
        current: List[str] = []
        current_len = 0

        for paragraph in paragraphs:
            para_len = len(paragraph)
            if current and current_len + para_len + 2 > max_chars:
                chunks.append(
                    {
                        "chunk_id": f"chunk_{chunk_index:04d}",
                        "source_path": doc["path"],
                        "text": "\n\n".join(current),
                        "chars": current_len,
                    }
                )
                chunk_index += 1
                current = []
                current_len = 0

            if para_len > max_chars:
                for start in range(0, para_len, max_chars):
                    part = paragraph[start : start + max_chars]
                    chunks.append(
                        {
                            "chunk_id": f"chunk_{chunk_index:04d}",
                            "source_path": doc["path"],
                            "text": part,
                            "chars": len(part),
                        }
                    )
                    chunk_index += 1
                continue

            current.append(paragraph)
            current_len += para_len + (2 if current_len else 0)

        if current:
            chunks.append(
                {
                    "chunk_id": f"chunk_{chunk_index:04d}",
                    "source_path": doc["path"],
                    "text": "\n\n".join(current),
                    "chars": current_len,
                }
            )
            chunk_index += 1

    return chunks


if __name__ == "__main__":
    raise SystemExit("Use build_character.py as the public entry point.")
