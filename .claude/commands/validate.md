---
allowed-tools: Read, Bash, Glob
description: Run all validation checks on the codebase
---

Run comprehensive validation:

1. **Lint**: `{{LINT_COMMAND}}`
2. **Types**: `{{TYPECHECK_COMMAND}}`
3. **Build**: `{{BUILD_COMMAND}}`
4. **Tests**: `{{TEST_COMMAND}}`
5. **Hygiene**: No console.log in production, no commented-out code, no TODO without issue numbers

Report:
```
✅/❌ Lint:   PASS/FAIL
✅/❌ Types:  PASS/FAIL
✅/❌ Build:  PASS/FAIL
✅/❌ Tests:  PASS/FAIL (X/Y passed)
⚠️  Warnings: [list]
```
