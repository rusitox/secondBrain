"""Unit tests for app.api.schemas.ui_protocol — the generative UI vocabulary.

Two concerns: (1) a schema-shape contract test that makes the "no markup"
hard constraint non-regressable — widening the vocabulary to a key that
could carry HTML/markdown/CSS/JS must be a deliberate, reviewed edit to
ui_protocol.py, not something that slips in unnoticed; (2) the per-kind
validation on UIField, which is the part of the "closed vocabulary"
guarantee that Field() alone can't express.
"""
import re
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from app.api.schemas.ui_protocol import (
    EmailAddress,
    EmailDraftArtifact,
    EntityRef,
    KeyValueRow,
    KeyValuesArtifact,
    LearnDirective,
    Option,
    SourceRef,
    TextSpan,
    UIField,
    UIRequest,
    UIRequestContent,
)

_FORBIDDEN_PROPERTY_NAME = re.compile(r"(html|markdown|^md$|css|style|script|template|raw)", re.IGNORECASE)


def _iter_schema_property_names(schema: Dict[str, Any]) -> List[str]:
    """Collect every JSON Schema property name across a model's schema and
    its $defs, so the forbidden-key check covers nested models too."""
    names: List[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.get("properties", {}).items():
                names.append(key)
                _walk(value)
            for value in node.get("$defs", {}).values():
                _walk(value)
            for key in ("anyOf", "allOf", "oneOf"):
                for value in node.get(key, []):
                    _walk(value)
            items = node.get("items")
            if items is not None:
                _walk(items)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(schema)
    return names


class TestNoMarkupContract:
    """The mechanical half of the "the LLM never authors markup" guarantee:
    no property name anywhere in the vocabulary can plausibly carry markup.
    The other half (the frontend never renders a model string as HTML/
    markdown) can't be tested from this repo — see the module docstring."""

    # Deliberate, reviewed exception: LearnDirective.claim_template matches
    # /template/i but isn't markup. It's a plain string with {field_key}
    # placeholders (validated at parse time — _learn_template_only_
    # references_known_fields — to reference only declared field keys),
    # substituted server-side via plain string replacement (never
    # str.format(), which would open a format-string-injection surface) to
    # build a knowledge-graph claim_text. It never reaches a browser, is
    # never rendered as HTML/markdown, and the model only ever fills its
    # {} placeholders, never its literal text. Widening this allowlist for
    # anything that reaches a client is a different, much larger decision.
    _ALLOWED_TEMPLATE_KEYS = {"claim_template"}

    @pytest.mark.parametrize("model", [UIRequest, UIRequestContent, EmailDraftArtifact, KeyValuesArtifact])
    def test_no_forbidden_property_names(self, model: Any) -> None:
        names = _iter_schema_property_names(model.model_json_schema())
        offenders = [
            n for n in names
            if _FORBIDDEN_PROPERTY_NAME.search(n) and n not in self._ALLOWED_TEMPLATE_KEYS
        ]
        assert offenders == [], f"{model.__name__} schema exposes markup-shaped keys: {offenders}"

    @pytest.mark.parametrize("model", [
        UIRequest, UIRequestContent, UIField, TextSpan, Option, EntityRef, SourceRef,
        EmailDraftArtifact, EmailAddress, KeyValuesArtifact, KeyValueRow,
    ])
    def test_extra_fields_are_rejected(self, model: Any) -> None:
        assert model.model_config.get("extra") == "forbid"


def _valid_field(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "key": "decision", "kind": "single_select", "label": "Decisión",
        "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
    }
    base.update(overrides)
    return base


class TestUIFieldKindShape:
    def test_single_select_requires_options(self) -> None:
        with pytest.raises(ValidationError):
            UIField(key="decision", kind="single_select", label="x")

    def test_single_select_default_must_be_a_known_option(self) -> None:
        with pytest.raises(ValidationError):
            UIField(**_valid_field(default="nope"))

    def test_single_select_with_valid_default_is_ok(self) -> None:
        UIField(**_valid_field(default="a"))

    def test_text_kind_forbids_options(self) -> None:
        with pytest.raises(ValidationError):
            UIField(key="comment", kind="text", label="Comentario",
                     options=[{"id": "a", "label": "A"}])

    def test_text_kind_allows_text_only_attributes(self) -> None:
        UIField(key="comment", kind="text", label="Comentario", required=False,
                 multiline=False, max_length=500, placeholder="ej: ...")

    def test_confirm_kind_forbids_options(self) -> None:
        with pytest.raises(ValidationError):
            UIField(key="ok", kind="confirm", label="¿Confirmás?",
                     options=[{"id": "a", "label": "A"}])

    def test_confirm_kind_allows_affirm_deny_labels(self) -> None:
        UIField(key="ok", kind="confirm", label="¿Confirmás?", affirm_label="Sí", deny_label="No")

    def test_datetime_requires_mode(self) -> None:
        with pytest.raises(ValidationError):
            UIField(key="when", kind="datetime", label="¿Cuándo?")

    def test_datetime_with_mode_is_ok(self) -> None:
        UIField(key="when", kind="datetime", label="¿Cuándo?", mode="date")

    def test_datetime_forbids_options(self) -> None:
        with pytest.raises(ValidationError):
            UIField(key="when", kind="datetime", label="¿Cuándo?", mode="date",
                     options=[{"id": "a", "label": "A"}])

    def test_entity_pick_allows_allow_none(self) -> None:
        UIField(key="who", kind="entity_pick", label="¿Quién?",
                 options=[{"id": "e1", "label": "Valentina Ruiz"}],
                 allow_none=True, none_label="Son personas distintas")

    def test_allow_none_outside_entity_pick_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UIField(**_valid_field(allow_none=True))

    def test_multi_select_min_select_must_not_exceed_max_select(self) -> None:
        with pytest.raises(ValidationError):
            UIField(key="tags", kind="multi_select", label="Tags",
                     options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                     min_select=2, max_select=1)

    def test_multi_select_max_select_must_not_exceed_option_count(self) -> None:
        with pytest.raises(ValidationError):
            UIField(key="tags", kind="multi_select", label="Tags",
                     options=[{"id": "a", "label": "A"}],
                     max_select=3)

    def test_min_select_outside_multi_select_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UIField(**_valid_field(min_select=1))


class TestTextSpan:
    def test_entity_ref_requires_entity_emphasis(self) -> None:
        with pytest.raises(ValidationError):
            TextSpan(text="Valentina", emphasis="none", ref={"type": "person", "id": "e1"})

    def test_entity_emphasis_without_ref_is_allowed(self) -> None:
        TextSpan(text="presupuesto Q4", emphasis="entity")

    def test_entity_emphasis_with_ref_is_allowed(self) -> None:
        TextSpan(text="Valentina", emphasis="entity", ref={"type": "person", "id": "e1"})


class TestUIRequestContent:
    def _content(self, **overrides: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "prompt": [{"text": "¿Qué decidís?"}],
            "fields": [_valid_field()],
            "submit_label": "Generar respuesta",
        }
        base.update(overrides)
        return base

    def test_duplicate_field_keys_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UIRequestContent(**self._content(fields=[_valid_field(), _valid_field()]))

    def test_more_than_max_fields_rejected(self) -> None:
        fields = [_valid_field(key=f"f{i}") for i in range(5)]
        with pytest.raises(ValidationError):
            UIRequestContent(**self._content(fields=fields))

    def test_request_id_is_not_a_model_authorable_field(self) -> None:
        """UIRequestContent — what a tool call actually produces — has no
        request_id at all; passing one is an unknown field under
        extra="forbid", not silently accepted."""
        with pytest.raises(ValidationError):
            UIRequestContent(**self._content(request_id="should-not-be-settable"))

    def test_minimal_valid_content(self) -> None:
        content = UIRequestContent(**self._content())
        assert content.kicker == "needs_datum"
        assert content.allow_dismiss is True


class TestUIRequestDesignExample:
    """Round-trips the exact email-approval interaction the MAREA design
    handoff specifies (decision chips + optional comment), confirming the
    protocol actually expresses the use case it was built for."""

    def test_email_approval_request_parses(self) -> None:
        payload = {
            "request_id": "1f0a2c6e-0000-0000-0000-000000000000",
            "kicker": "needs_datum",
            "prompt": [
                {"text": "Valentina", "emphasis": "entity", "ref": {"type": "person", "id": "e3c1"}},
                {"text": " espera tu respuesta sobre el ", "emphasis": "none"},
                {"text": "presupuesto Q4", "emphasis": "entity", "ref": {"type": "topic", "id": "a712"}},
                {"text": ". ¿Qué decidís?", "emphasis": "none"},
            ],
            "fields": [
                {
                    "key": "decision", "kind": "single_select", "label": "Decisión", "required": True,
                    "options": [
                        {"id": "approve", "label": "Aprobar"},
                        {"id": "changes", "label": "Con cambios"},
                        {"id": "reject", "label": "Rechazar"},
                    ],
                    "default": "approve",
                },
                {
                    "key": "comment", "kind": "text", "label": "Comentario", "required": False,
                    "max_length": 500, "placeholder": 'Agregá un comentario, ej: "ajustar la partida de viajes"',
                },
            ],
            "submit_label": "Generar respuesta",
        }
        request = UIRequest(**payload)
        assert request.fields[0].default == "approve"
        assert request.prompt[0].ref is not None and request.prompt[0].ref.type == "person"

    def test_email_draft_artifact_parses(self) -> None:
        artifact = EmailDraftArtifact(
            to=[{"name": "Valentina Ruiz", "address": "valentina@empresa.com"}],
            subject="Re: Presupuesto Q4",
            body_paragraphs=[
                "Hola Valentina: revisé el presupuesto Q4 y queda aprobado.",
                "Un detalle: ajustar la partida de viajes.",
                "¿Lo repasamos cinco minutos antes de la demo de las 15:00?",
            ],
            footnote_token="drafted_by_assistant",
        )
        assert artifact.kind == "email_draft"


class TestEntityDisambiguationExample:
    """Round-trips the entity_pick shape a future PendingQuestion adapter
    (Fase 2) will need to produce for an "are these the same person?" case."""

    def test_disambiguation_request_parses(self) -> None:
        payload = {
            "request_id": "9b2f0000-0000-0000-0000-000000000000",
            "kicker": "disambiguate",
            "source": {"kind": "knowledge_question", "id": "9b2f"},
            "prompt": [{"text": "¿Valentina Ruiz y Valen R. son la misma persona?"}],
            "fields": [{
                "key": "same_entity", "kind": "entity_pick", "label": "Resolución", "required": True,
                "options": [
                    {"id": "e3c1", "label": "Valentina Ruiz", "hint": "person · conf 0.82", "entity_id": "e3c1"},
                    {"id": "77d0", "label": "Valen R.", "hint": "person · conf 0.41", "entity_id": "77d0"},
                ],
                "allow_none": True, "none_label": "Son personas distintas",
            }],
            "submit_label": "Confirmar",
        }
        request = UIRequest(**payload)
        assert request.source is not None and request.source.kind == "knowledge_question"


class TestLearnDirective:
    def _content(self, **overrides: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "prompt": [{"text": "¿Qué decidís?"}],
            "fields": [_valid_field()],
            "submit_label": "Generar respuesta",
        }
        base.update(overrides)
        return base

    def test_template_referencing_known_field_is_ok(self) -> None:
        content = UIRequestContent(**self._content(
            learn={"entity_id": "e1", "claim_template": "Decisión: {decision}"},
        ))
        assert content.learn is not None
        assert content.learn.entity_id == "e1"

    def test_template_referencing_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UIRequestContent(**self._content(
                learn={"entity_id": "e1", "claim_template": "Comentario: {nope}"},
            ))

    def test_template_with_no_placeholders_is_ok(self) -> None:
        UIRequestContent(**self._content(learn={"entity_id": "e1", "claim_template": "Fixed text"}))

    def test_learn_defaults_to_none(self) -> None:
        content = UIRequestContent(**self._content())
        assert content.learn is None

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LearnDirective(entity_id="e1", claim_template="x", extra_key="nope")
