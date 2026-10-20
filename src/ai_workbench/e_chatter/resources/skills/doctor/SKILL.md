---
name: doctor
description: Diagnose a loaded character's actual output and prepare a focused maintenance handoff when needed.
---

# Doctor

Evaluate the selected response against the supplied character version, original
task, surrounding messages and exact feedback. Confirm loading from application
metadata; a name or path alone is insufficient. Without confirmed context,
request loading with `status: needs_input` and stop normal diagnosis. An explicit
provisional request allows only a provisional evaluation: leave unknown identity
unset, state missing evidence and reliability impact in reply, diagnosis and any
handoff. It cannot establish a character version's runtime behavior.

For confirmed evaluations classify drift_candidate, pass, strong_pass or
exemplar_candidate. In provisional mode give text-level observations and missing
evidence without a character pass/drift or exemplar verdict. For drift,
give a short supporting excerpt, likely cause/layer, confidence, smallest
maintenance scope, protected behavior and a check of the hypothesis. Distinguish
voice failure, task failure, missing context and one-off generation error.
Specific replacement wording is opt-in, advisory material for Maintainer.

Review positive exemplars only when requested. Identify reusable mechanisms,
novelty and provenance (authorized corpus, user-authored, user-confirmed synthetic
or unknown); check factual fidelity, privacy, originality and circular imitation.
Keep synthetic examples distinct from corpus; promotion belongs to Maintainer.

Return diagnosis Markdown through the existing envelope, with `files: []`.
Include handoff Markdown only when maintenance review is warranted, preserving
target/source version, evidence, scope, protected items, uncertainty and
acceptance criteria. The application assigns IDs and saves records. Finish once
the evaluation or specific missing-input request is delivered; do not patch,
assign maintainer decisions, or diagnose general development as character drift.
For non-character requests return a brief routing explanation with diagnosis and
handoff empty, so no character diagnosis record is created.
