---
name: karpathy-guidelines
description: "Use before code changes that need focused debugging, refactoring, or regression prevention."
---

# Surgical Engineering

1. State the observable failure and the acceptance criteria before changing code.
2. Read the existing implementation and tests; do not infer unseen behavior.
3. Prefer the smallest coherent patch. Avoid broad rewrites and speculative abstractions.
4. Add a regression test before or alongside the fix, including relevant failure paths.
5. Keep error handling specific and useful. Do not swallow exceptions or weaken checks.
6. Run the narrow test first, then the full relevant suite. Report the exact checks that ran.
7. Every modified line should support the requested outcome; mention unrelated findings separately.

## Done means verified

A source edit is not a release. Distinguish tests that passed locally from tests that passed in CI, and distinguish both from manual testing on a user's machine.
