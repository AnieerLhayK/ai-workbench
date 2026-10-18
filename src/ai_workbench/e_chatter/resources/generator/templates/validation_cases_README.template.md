# Validation Case Templates

This directory stores empty validation templates for checking whether `{display_name}` changes preserve task fit, style control, originality, and privacy.

Use these as templates. Fill them with user-approved, anonymized, or fully synthetic text before running a real validation pass.

## How To Use

1. Copy a template to a new case file or fill the template directly for a local review.
2. Replace placeholder text with anonymized input.
3. Run the same prompt before and after a generator update or maintainer patch.
4. Let the user judge the subjective "does it feel right" dimension.
5. Record observations in the case file or in a runtime-loop validation note.

## What Not To Store

- Raw private corpus excerpts.
- Real names, schools, addresses, contact details, or identifiable relationships.
- Long source-text quotations.
- Outputs that should stay private.

## Evaluation Split

The agent can check:

- task fit;
- fact retention;
- obvious AI tone;
- over-style risk;
- privacy and originality risk;
- contradiction with references.

The user should judge:

- whether it feels like the intended digital person;
- whether the intensity is too weak or too strong;
- whether the rhythm, restraint, and emotional temperature are right.
