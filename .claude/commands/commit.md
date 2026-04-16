---
allowed-tools: Read, Bash(git:*)
description: Create a well-structured git commit with conventional commit format
---

1. Run `git diff --staged` to review staged changes
2. If nothing staged, run `git diff` and suggest what to stage
3. Generate commit message: `<type>(<scope>): <description>`
   Types: feat, fix, refactor, docs, style, test, chore, perf
   Rules: under 50 chars, imperative mood, no period
4. Present message for approval before executing
5. Run `git commit -m "<message>"` only after confirmation
