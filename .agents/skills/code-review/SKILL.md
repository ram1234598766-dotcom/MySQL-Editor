---
name: code-review
description: "Use on pull requests and non-trivial code changes to run an independent CodeRabbit review when the CLI and authentication are available."
---

# Code Review with CodeRabbit

1. Confirm the working directory is a Git checkout and inspect the exact diff.
2. Check `coderabbit --version`.
3. Check `coderabbit auth status --agent`.
4. If the CLI is missing, follow the official installer in a suitable development environment. If authentication is missing, initiate `coderabbit auth login --agent` and request the user complete any required login. Do not claim a CodeRabbit review occurred unless its review output is available.
5. Run `coderabbit review --agent --base main` (or the narrowest suitable review scope). Parse review output by severity and tie each issue to a file and impact.
6. Do not blindly apply suggestions. Check each suggestion against repository constraints, add tests for accepted fixes, and rerun CI.
7. If network access or authentication makes a review impossible, report the blocker; never label a human/manual inspection as CodeRabbit output.

Repository PRs should use `.coderabbit.yaml` so the review has context about Qt thread-safety, MySQL credentials, TLS, result exports, and Windows packaging.
