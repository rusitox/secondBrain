---
allowed-tools: Read, Bash(git:*), Bash(gh:*), Grep, Glob
description: Review a Pull Request for quality and correctness
---

Review PR: $ARGUMENTS

1. Fetch PR diff: `gh pr diff $ARGUMENTS`
2. Read changed files for context
3. Review for: correctness, security, performance, test coverage, conventions
4. Output findings using 🔴 Critical / 🟡 Warning / 🟢 Suggestion format
5. Provide overall assessment: APPROVE / REQUEST CHANGES / COMMENT
