# Accepted e-Chatter visual specification

The six PNGs are the user-approved image-generated references: light/dark main,
settings, character registry, engineering confirmation and revision review.
They are design artifacts, not application data or bundled example characters.

The implementation retains the sidebar width, nested session tree, neutral
surfaces, restrained blue accents, fixed composer and shortcut order. The Doctor
button stays at the far right. Deliberate functional differences are version
labels, an explicit synthetic-demo disclaimer, a neutral assistant icon, a folder
creation affordance and an accessible temporary-skill attachment action.

Visual checks compare screenshots at 1536 × 1024 and inspect the native Qt host.
The source build uses local system fonts; platform rendering can differ slightly
from the generated reference. Screenshots and runtime probes belong in external
staging, not this directory.

## Confirmed multi-Agent extension (2026-10-19)

`models.png` and `agent-settings.png` govern the added controls. Keep the existing
sidebar/message/window implementation: only the Models popover and inline Agent
settings are extended. Agent changes live only in Settings via the existing
bottom-left status. Models controls conversation-by-Agent preferences. Synthetic
paths/models/copy in the reference are examples, not live configuration. Light
and dark variants use existing application tokens. The diagnostic shortcut is
lowercase `doctor`; preserve its stethoscope and far-right position.
