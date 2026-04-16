---
allowed-tools: Read, Bash(git:*), Bash(gh:*)
description: Create a GitHub Pull Request with structured description
---

1. Get current branch: `git branch --show-current`
2. Get commits vs main: `git log main..HEAD --oneline`
3. Generate PR description with: summary, changes list, type of change, testing checklist
4. Create PR: `gh pr create --title "<title>" --body "<description>"`
5. Present the PR URL
