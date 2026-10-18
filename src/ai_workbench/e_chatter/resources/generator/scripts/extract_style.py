from __future__ import annotations

import re
from typing import Dict, Iterable, List


def bullet_list(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _top(items: List, count: int = 8) -> str:
    if not items:
        return "- Not enough corpus signal."
    return "\n".join(f"- `{item}` appears {n} time(s)." for item, n in items[:count])


def _sample_fragments(chunks: List[Dict], max_chars: int) -> str:
    fragments = []
    for chunk in chunks[:3]:
        text = re.sub(r"\s+", " ", chunk["text"]).strip()
        if not text:
            continue
        fragments.append(f"- \"{text[:max_chars]}\"")
    return "\n".join(fragments) if fragments else "- No safe fragment available."


def _skill_name(character_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", character_id.lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return f"{normalized}-style" if normalized else "style-inspired-character"


def _all_text(chunks: List[Dict]) -> str:
    return "\n\n".join(chunk["text"] for chunk in chunks)


def _punctuation_profile(text: str) -> str:
    total = max(len(text), 1)
    marks = {
        "comma": text.count(",") + text.count("，"),
        "period": text.count(".") + text.count("。"),
        "question": text.count("?") + text.count("？"),
        "exclamation": text.count("!") + text.count("！"),
        "semicolon": text.count(";") + text.count("；"),
        "colon": text.count(":") + text.count("："),
    }
    ranked = sorted(marks.items(), key=lambda item: item[1], reverse=True)
    lines = [
        f"- {name}: {count} mark(s), about {round(count / total * 1000, 2)} per 1k chars."
        for name, count in ranked
        if count
    ]
    if not lines:
        lines.append("- Sparse punctuation signal; keep pacing simple and avoid ornamental punctuation.")
    lines.append("- Use punctuation as pacing evidence, not as a surface imitation trick.")
    return "\n".join(lines)


def _paragraph_profile(chunks: List[Dict]) -> str:
    paragraphs: List[str] = []
    for chunk in chunks:
        paragraphs.extend([p.strip() for p in chunk["text"].split("\n\n") if p.strip()])
    if not paragraphs:
        return "- Not enough paragraph signal."

    lengths = [len(p) for p in paragraphs]
    avg = round(sum(lengths) / len(lengths), 2)
    short = sum(1 for length in lengths if length < 80)
    medium = sum(1 for length in lengths if 80 <= length < 220)
    long = sum(1 for length in lengths if length >= 220)
    return (
        f"- Average paragraph length: {avg} characters.\n"
        f"- Short paragraphs: {short}; medium paragraphs: {medium}; long paragraphs: {long}.\n"
        "- Preserve paragraph pressure: each paragraph should change focus, tension, or angle."
    )


def _sentence_rhythm(avg_sentence_length: float) -> str:
    if avg_sentence_length < 24:
        return "Sentences tend to be compact and quick-turning."
    if avg_sentence_length < 45:
        return "Sentences tend to unfold through medium-length clauses with room for qualification."
    return "Sentences tend to be long, layered, and reflective, often delaying closure."


def _style_intensity_rule(style_strength: str) -> str:
    if style_strength == "light":
        return "Keep style low-intensity: preserve user wording and add only subtle rhythm and diction changes."
    if style_strength == "strong":
        return "Allow style to become clearly visible, but stop before rare phrase reuse, identity claims, or ornate padding."
    return "Use medium intensity: make rhythm, structure, and imagery visible while keeping the user's task dominant."


def build_style_values(config: Dict, stats: Dict, chunks: List[Dict], privacy_counts: Dict) -> Dict:
    text = _all_text(chunks)
    avg = stats["average_sentence_length"]
    rhythm = _sentence_rhythm(avg)
    top_chars = _top(stats["top_chars"])
    top_terms = _top(stats["top_terms"])
    target_tasks = config["target_tasks"]
    paragraph_profile = _paragraph_profile(chunks)
    punctuation_profile = _punctuation_profile(text)
    intensity_rule = _style_intensity_rule(config["style_strength"])

    return {
        "skill_name": _skill_name(config["character_id"]),
        "display_name": config["display_name"],
        "character_id": config["character_id"],
        "privacy_level": config["privacy_level"],
        "style_strength": config["style_strength"],
        "quote_policy": config["quote_policy"],
        "max_quote_chars": config["max_quote_chars"],
        "target_tasks_list": bullet_list(target_tasks),
        "target_tasks_inline": ", ".join(target_tasks),
        "forbidden_tasks": ", ".join(config["forbidden_tasks"]),
        "forbidden_tasks_list": bullet_list(config["forbidden_tasks"]),
        "style_summary": (
            f"This profile is derived from {stats['file_count']} file(s), "
            f"{stats['paragraph_count']} paragraph(s), and {stats['sentence_count']} sentence(s). "
            f"It should be used as an abstract craft map with `{config['style_strength']}` strength. "
            f"{intensity_rule}"
        ),
        "dominant_craft_signals": (
            "- Build sentences around observable details before commentary.\n"
            "- Let images carry argument or mood instead of decorating the surface.\n"
            "- Use paragraph turns to create pressure, contrast, or afterthought.\n"
            "- Track style through syntax, rhythm, image function, and paragraph movement before vocabulary.\n"
            "- Keep any direct corpus phrase short and sanitized."
        ),
        "paragraph_movement": (
            "Paragraphs should move from concrete observation to judgment or emotional pressure, "
            "then close with a small turn rather than a slogan.\n"
            f"{paragraph_profile}"
        ),
        "emotional_progression": (
            "Prefer gradual pressure: start from a scene, object, or statement; complicate it with "
            "qualification; end by opening a sharper emotional or intellectual angle."
        ),
        "register": (
            "Use a literate, controlled register. Keep abstraction tied to sensory or structural detail."
        ),
        "speaker_stance": (
            "The speaker should sound observant and exacting, more interested in craft pressure than self-display."
        ),
        "distance_from_subject": (
            "Maintain moderate distance: close enough for texture, distant enough for reflection."
        ),
        "interaction_posture": (
            "- Treat the generated interaction stance as provisional until users validate it across cases.\n"
            "- When an emotional input does not reveal its cause, prefer a brief context-aware question "
            "before naming the cause or prescribing a solution.\n"
            "- When the user has supplied enough concrete facts, a direct response or practical suggestion "
            "may be more natural than compulsory questioning.\n"
            "- Do not force generic therapeutic neutrality when validated character evidence supports a "
            "more direct, skeptical, warm, restrained, or challenging posture."
        ),
        "inference_discipline": (
            "- Objective facts, private details, and another person's motives require explicit evidence; "
            "do not invent them.\n"
            "- Emotional possibilities may be offered as possibilities, not certainties.\n"
            "- Creative completion is acceptable only when the task invites continuation, rewriting, or "
            "clearly marked imaginative interpretation.\n"
            "- Advice should follow the information actually available. If a missing fact could materially "
            "change the advice, ask first."
        ),
        "typical_moves": (
            "- Start with a concrete noun, action, or tension.\n"
            "- Move through contrast, qualification, or delayed clarification.\n"
            "- End paragraphs with a turn that changes the reader's angle of attention."
        ),
        "sentence_patterns": (
            f"{rhythm}\n"
            "- Mix declarative sentences with clauses that refine or reverse the first claim.\n"
            "- Vary short pressure lines with more layered movement.\n"
            "- Keep style visible through sentence function rather than repeated slogans."
        ),
        "rhetorical_patterns": (
            "- Use contrast pairs, delayed explanation, and image-to-idea movement.\n"
            "- Prefer implication over direct moralizing.\n"
            "- Let a paragraph's last sentence slightly reframe the opening detail."
        ),
        "transition_patterns": (
            "- Use soft turns such as however, only, but, later, still, yet, then, or meanwhile when natural.\n"
            "- In Chinese output, prefer light turns such as dan, zhi shi, ran er, hou lai, or yu shi only when the sentence needs them.\n"
            "- Let paragraph order carry transitions when explicit connectors would feel heavy."
        ),
        "structural_patterns": (
            "- Open from a local detail.\n"
            "- Expand through association or argument.\n"
            "- Introduce a pressure point or counter-angle.\n"
            "- Close with a changed emotional or conceptual position."
        ),
        "imagery_fields": (
            "Use high-frequency terms as signal, not decoration:\n"
            f"{top_terms}"
        ),
        "image_function": (
            "Images should perform work: focusing attention, compressing emotion, shifting the argument, "
            "or creating a hinge between concrete scene and abstract claim."
        ),
        "theme_movement": (
            "Move themes through tension rather than announcement. Let conflict appear in syntax and paragraph order."
        ),
        "domain_fit_hypotheses": (
            "Recurring terms can suggest topics worth testing, but they do not prove runtime competence. "
            "Treat the following corpus signals as candidate domains until anonymized cases and user review "
            "confirm them:\n"
            f"{top_terms}"
        ),
        "task_intensity_guidance": (
            f"`{config['style_strength']}` is the configured maximum/default envelope, not a demand to use "
            "the same intensity everywhere.\n"
            "- Use lighter styling for routine chat, practical replies, and fact-sensitive tasks.\n"
            "- Use medium styling when reflection or emotional texture helps the task.\n"
            "- Use stronger styling only when the user requests it or the task benefits from visible craft.\n"
            "- Lower intensity whenever style begins to obscure facts, function, or the user's own voice."
        ),
        "sentence_length": f"Average sentence length is about {avg} characters.",
        "rhythm": rhythm,
        "punctuation": punctuation_profile,
        "paragraph_cadence": (
            "Alternate dense reflective paragraphs with shorter release paragraphs when the task allows. "
            "Avoid making every paragraph the same emotional weight."
        ),
        "high_frequency_chars": top_chars,
        "high_frequency_terms": top_terms,
        "functional_vocabulary": (
            "- Prefer verbs and nouns that move thought forward.\n"
            "- Use repeated function words only when they shape rhythm.\n"
            "- Avoid keyword stuffing from the corpus.\n"
            "- Treat high-frequency terms as evidence for topic pressure, not as a mandatory word list."
        ),
        "sanitized_fragments": _sample_fragments(chunks, int(config["max_quote_chars"])),
        "invented_fragments": (
            "- Newly created: The room kept its silence, not as peace, but as a pressure waiting for a name.\n"
            "- Newly created: What changed first was not the fact itself, but the angle from which it could be endured."
        ),
        "rewrite_recipe": (
            "Preserve meaning, identify the draft's core pressure, then adjust sentence rhythm, image function, "
            "and paragraph turns according to the references. Run drift scoring before final output."
        ),
        "continuation_recipe": (
            "Continue only from user-provided text. Extend its scene or argument using compatible pacing and fresh language."
        ),
        "imitation_recipe": (
            "Write a new passage from abstract traits. Never present it as written by the source person."
        ),
        "critique_recipe": (
            "Evaluate syntax, rhythm, imagery, structure, diction, and drift control. Give concrete revision moves."
        ),
        "style_transfer_recipe": (
            "Transfer craft tendencies while preserving user intent. Remove copied phrases and private details."
        ),
        "discussion_recipe": (
            "Respond directly to the user's thought without first presenting a task menu. "
            "Use the style profile as stance, rhythm, and attention pattern rather than identity roleplay. "
            "First check whether the input contains enough information for interpretation or advice. "
            "If the cause or stakes are unclear and materially affect the response, ask one brief, "
            "context-aware question; if the relevant facts are explicit, respond directly. "
            "Allow agreement, hesitation, questioning, or disagreement when useful, but do not force conflict. "
            "Avoid headings, scoring, tables, flattering summaries, private fact invention, and invented memories."
        ),
        "corpus_coverage": (
            f"The build used {stats['file_count']} file(s), {stats['total_chars']} non-space characters, "
            f"and {len(chunks)} chunk(s)."
        ),
        "known_limits": (
            "Small or narrow corpora may overrepresent topic, period, or genre. Treat the profile as provisional."
        ),
        "privacy_handling": (
            "Sensitive values were redacted before style extraction. Redaction counts: "
            + ", ".join(f"{key}={value}" for key, value in sorted(privacy_counts.items()))
            + "."
        ),
        "build_notes": (
            "Generated by the local character-generator workflow using deterministic heuristics and templates."
        ),
    }


if __name__ == "__main__":
    raise SystemExit("Use build_character.py as the public entry point.")
