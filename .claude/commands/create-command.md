---
allowed-tools: Read, Write, Glob
description: Create a new slash command for this project
---

1. Ask: What should the command do? What tools does it need? Manual or model-invocable?
2. Generate `.md` with YAML frontmatter + step-by-step instructions
3. Use `$ARGUMENTS` for user input. Include validation steps.
4. Save to `.claude/commands/<name>.md`
5. Confirm: `/project:<name>` to invoke
