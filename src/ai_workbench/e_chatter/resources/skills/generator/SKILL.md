---
name: generator
description: Create a style-inspired character from user-authorized material and intended writing tasks.
---

# Generator

Create a new character baseline from the application's supplied materials.
Gather the approved display label/id, authorization, intended tasks and privacy
boundaries; reuse supplied answers and request only missing required inputs with
`status: needs_input`. Abstract style from evidence, keep uncertainty visible,
and use fresh examples within quote limits. Avoid impersonation and private-fact
inference. Existing character repairs belong to Maintainer.

Use the existing JSON envelope. For direct synthesis, return `files` containing
complete UTF-8 text for SKILL.md and every referenced resource, with relative
paths. For an explicitly requested packaged builder, return `build_intake` as a
JSON object string referencing only supplied material IDs. The app runs its
fixed builder on task-staged copies; the model does not execute it.

Complete with a reviewable proposal or a precise missing-input explanation.
Distinguish a proposed package, structural checks actually reported by the app,
and writing quality still requiring trials. The application validates, stages
and saves user-accepted versions. Shared application policy owns permissions and
storage; no Workspace installation or external reference loading is required.
