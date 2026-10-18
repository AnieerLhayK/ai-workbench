from __future__ import annotations

import collections
import re
from pathlib import Path
from typing import Dict, List


STOP_CHARS = set("的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原")


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"[。！？!?；;\n]+", text) if s.strip()]


def _terms(text: str) -> List[str]:
    zh_terms = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    en_terms = re.findall(r"\b[A-Za-z]{3,}\b", text.lower())
    return zh_terms + en_terms


def compute_stats(documents: List[Dict]) -> Dict:
    full_text = "\n\n".join(doc["text"] for doc in documents)
    non_space_chars = [c for c in full_text if not c.isspace()]
    paragraphs = [p for p in re.split(r"\n\s*\n", full_text) if p.strip()]
    sentences = _sentences(full_text)
    sentence_lengths = [len(s) for s in sentences] or [0]

    char_counter = collections.Counter(c for c in non_space_chars if c not in STOP_CHARS)
    term_counter = collections.Counter(t for t in _terms(full_text) if len(t) > 1)

    return {
        "total_chars": len(non_space_chars),
        "file_count": len(documents),
        "paragraph_count": len(paragraphs),
        "sentence_count": len(sentences),
        "average_sentence_length": round(sum(sentence_lengths) / len(sentence_lengths), 2),
        "top_chars": char_counter.most_common(30),
        "top_terms": term_counter.most_common(30),
    }


def render_corpus_stats(stats: Dict) -> str:
    lines = [
        "# Corpus Stats",
        "",
        f"- Total characters: {stats['total_chars']}",
        f"- File count: {stats['file_count']}",
        f"- Paragraph count: {stats['paragraph_count']}",
        f"- Sentence count: {stats['sentence_count']}",
        f"- Average sentence length: {stats['average_sentence_length']}",
        "",
        "## High-Frequency Characters",
        "",
    ]
    lines.extend(f"- {char}: {count}" for char, count in stats["top_chars"][:20])
    lines.extend(["", "## High-Frequency Terms", ""])
    lines.extend(f"- {term}: {count}" for term, count in stats["top_terms"][:20])
    return "\n".join(lines) + "\n"


def write_corpus_stats(stats: Dict, output_path: Path) -> Path:
    report_path = output_path / "reports" / "corpus_stats.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_corpus_stats(stats), encoding="utf-8")
    return report_path


if __name__ == "__main__":
    raise SystemExit("Use build_character.py as the public entry point.")
