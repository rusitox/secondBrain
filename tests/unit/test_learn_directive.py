"""Unit tests for the `learn` directive's claim-template substitution
(app.services.agent.knowledge.answer._render_claim_template) — the pure
part of Fase 2's learning loop. See
tests/integration/test_learn_directive.py for apply_learn_directive's
DB-backed behavior.
"""
from app.services.agent.knowledge.answer import _render_claim_template


class TestRenderClaimTemplate:
    def test_substitutes_known_key(self) -> None:
        result = _render_claim_template("Decisión: {decision}", {"decision": "approve"})
        assert result == "Decisión: approve"

    def test_multiple_keys(self) -> None:
        result = _render_claim_template(
            "{decision} — {comment}", {"decision": "approve", "comment": "ajustar viajes"},
        )
        assert result == "approve — ajustar viajes"

    def test_missing_answer_key_substitutes_empty_string(self) -> None:
        result = _render_claim_template("Nota: {comment}", {})
        assert result == "Nota: "

    def test_no_placeholders_returns_template_unchanged(self) -> None:
        assert _render_claim_template("Texto fijo", {"decision": "approve"}) == "Texto fijo"

    def test_never_interprets_format_spec_syntax(self) -> None:
        """A malformed token like {decision!r} must not trigger Python's
        format-spec mini-language — it isn't a valid {lowercase_key} token
        so it's left as literal text, never str.format()-evaluated."""
        result = _render_claim_template("{decision!r}", {"decision": "approve"})
        assert result == "{decision!r}"
