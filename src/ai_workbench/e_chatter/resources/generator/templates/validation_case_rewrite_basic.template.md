# Case 001: Basic Rewrite

## Task

Rewrite the input with a light to medium `{display_name}`-inspired style while preserving facts and intent.

## Input

```text
<Insert anonymized or synthetic source text here.>
```

## Prompt Variables

- length: <keep original length / target word count>
- style_strength: light / medium
- must_keep: <facts, relationship, time, purpose>
- avoid: <privacy, over-stylization, repeated motifs>

## Expected Behavior

- Preserve the original facts and speaker intent.
- Add style influence only where it fits the task.
- Avoid impersonation, private facts, and corpus-like phrasing.
- Keep changes small enough that the source purpose remains clear.

## User Judgment

- Does the rewritten version feel natural?
- Is the style-inspired layer too weak, appropriate, or too strong?
- Which sentence feels most unlike the intended style?

## Agent Checks

- Task fit:
- Fact retention:
- Style fit:
- Over-style risk:
- Privacy/originality:
