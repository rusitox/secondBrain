---
globs:
  - "**/*.py"
---

# Python Conventions

- Type hints for all function parameters and return types.
- Use `dataclass` or `pydantic.BaseModel` for data structures.
- Prefer f-strings over `.format()` or `%` formatting.
- Use `pathlib.Path` instead of `os.path` for file operations.
- All exceptions must be specific — never bare `except:`.
- Use `logging` module, not `print()` for production code.
- Async functions use `async/await`, not threading for I/O.
- PEP 8 naming: `snake_case` functions/variables, `PascalCase` classes.
- Use `__all__` in `__init__.py` to control public API.
