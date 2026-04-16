---
allowed-tools: Read, Write, Bash, Glob, Grep
description: Implement a feature or task following the project plan
---

Implement: $ARGUMENTS

1. Read the plan if it exists in `specs/`
2. Understand existing patterns in the codebase
3. Implement incrementally, validating after each change:
   ```bash
   {{LINT_COMMAND}} && {{TYPECHECK_COMMAND}}
   ```
4. Follow {{LANGUAGE}} / {{FRAMEWORK}} conventions
5. Add error handling and structured logging
6. Self-review before presenting: no hardcoded values, no console.log, clean imports
7. Summarize what was implemented and decisions made
