"""Generative UI protocol — the closed vocabulary an agent uses to ask the
user a structured question at runtime, and to preview an artifact (a
drafted email, a set of key/value facts) before any action is taken on it.

Design rules (see plan Fase 1 — this file is the mechanical half of the
"no markup" hard constraint):

1. Six field kinds, closed. ``FieldKind`` is a ``Literal`` — there is no
   escape hatch to a seventh, model-invented kind.
2. Rich text is spans, not markup. A highlighted entity in a question
   (e.g. "**Valentina** espera tu respuesta") becomes a ``TextSpan`` with
   ``emphasis="entity"``, never a markdown/HTML string. The model picks
   *which* span gets emphasis; the frontend owns *how* that renders.
3. Chrome is tokens, content is text. ``kicker`` is a closed enum whose
   copy lives client-side, localized. Only the question text and option
   labels are model-authored plain strings.
4. ``extra="forbid"`` on every model. There is no field anywhere in this
   vocabulary that can carry ``html``/``markdown``/``css``/``script``/
   ``template`` — and the model cannot invent one; validation rejects it
   before it reaches the database, let alone the client. A widening of
   the vocabulary is a deliberate, reviewed edit to this file, not
   something a prompt can talk the model into.
5. ``request_id`` is never model-authored. ``UIRequestContent`` is the
   subset of a request an LLM tool call actually produces; ``UIRequest``
   (server-assigned ``request_id``, optional ``source`` provenance) is
   the only thing ever sent to a client. A tool that accepts model output
   should type its parameter as ``UIRequestContent``, never ``UIRequest``.

Python 3.8 syntax throughout (``Optional``/``List``/``Union``, no ``X | Y``)
per this repo's compatibility convention.
"""
import re
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kicker = Literal["needs_datum", "confirm_knowledge", "disambiguate", "review_draft"]
FieldKind = Literal["single_select", "multi_select", "text", "confirm", "datetime", "entity_pick"]
EntityKind = Literal["person", "project", "initiative", "topic", "organization"]

MAX_FIELDS = 4
MAX_OPTIONS = 8
MAX_PROMPT_SPANS = 24

_FIELD_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
_TEMPLATE_KEY_PATTERN = re.compile(r"\{([a-z][a-z0-9_]{0,31})\}")


# ---------------------------------------------------------------------------
# Rich text — spans, never markup
# ---------------------------------------------------------------------------

class EntityRef(BaseModel):
    """Links a highlighted span back to a known entity in the knowledge graph."""

    model_config = ConfigDict(extra="forbid")

    type: EntityKind
    id: str


class TextSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=400)
    emphasis: Literal["none", "entity"] = "none"
    ref: Optional[EntityRef] = None

    @model_validator(mode="after")
    def _ref_requires_emphasis(self) -> "TextSpan":
        if self.ref is not None and self.emphasis != "entity":
            raise ValueError('a span with "ref" must have emphasis="entity"')
        return self


# ---------------------------------------------------------------------------
# Fields — the six closed widget kinds
# ---------------------------------------------------------------------------

class Option(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    label: str = Field(max_length=80)
    hint: Optional[str] = Field(default=None, max_length=160)
    entity_id: Optional[str] = None  # only meaningful for kind="entity_pick"


class UIField(BaseModel):
    """One request field.

    Deliberately a single flat model with a ``Literal`` ``kind``
    discriminator and per-kind optional attributes rather than a
    discriminated union: function-calling schemas expose this to the model
    as one flat JSON object, which OpenAI/Anthropic tool-use handles far
    more reliably than a ``oneOf``. Strictness is recovered here, in
    ``_check_kind_shape``, instead of at the type level.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=_FIELD_KEY_PATTERN)
    kind: FieldKind
    label: str = Field(max_length=80)
    required: bool = True
    help: Optional[str] = Field(default=None, max_length=200)

    # single_select / multi_select / entity_pick
    options: Optional[List[Option]] = Field(default=None, max_length=MAX_OPTIONS)
    default: Optional[str] = None
    min_select: Optional[int] = Field(default=None, ge=0)
    max_select: Optional[int] = Field(default=None, ge=1)
    allow_none: bool = False
    none_label: Optional[str] = Field(default=None, max_length=80)

    # text
    multiline: bool = False
    max_length: Optional[int] = Field(default=None, gt=0, le=4000)
    placeholder: Optional[str] = Field(default=None, max_length=160)

    # confirm
    affirm_label: Optional[str] = Field(default=None, max_length=40)
    deny_label: Optional[str] = Field(default=None, max_length=40)

    # datetime
    mode: Optional[Literal["date", "time", "datetime"]] = None
    min_iso: Optional[str] = None
    max_iso: Optional[str] = None

    @model_validator(mode="after")
    def _check_kind_shape(self) -> "UIField":
        needs_options = self.kind in ("single_select", "multi_select", "entity_pick")
        option_ids = {o.id for o in self.options} if self.options else set()

        if needs_options:
            if not self.options:
                raise ValueError(f'kind="{self.kind}" requires at least one option')
        elif self.options is not None:
            raise ValueError(f'kind="{self.kind}" must not set "options"')

        if self.kind == "single_select":
            if self.default is not None and self.default not in option_ids:
                raise ValueError('"default" must be the id of one of "options"')
        elif self.default is not None:
            raise ValueError(f'kind="{self.kind}" must not set "default"')

        if self.kind == "multi_select":
            if self.min_select is not None and self.max_select is not None:
                if self.min_select > self.max_select:
                    raise ValueError('"min_select" must be <= "max_select"')
            if self.max_select is not None and self.options and self.max_select > len(self.options):
                raise ValueError('"max_select" must be <= the number of options')
        elif self.min_select is not None or self.max_select is not None:
            raise ValueError(f'kind="{self.kind}" must not set "min_select"/"max_select"')

        if self.kind != "entity_pick" and (self.allow_none or self.none_label is not None):
            raise ValueError('"allow_none"/"none_label" only apply to kind="entity_pick"')

        if self.kind != "text" and (self.multiline or self.max_length is not None or self.placeholder is not None):
            raise ValueError(f'kind="{self.kind}" must not set text-only attributes')

        if self.kind != "confirm" and (self.affirm_label is not None or self.deny_label is not None):
            raise ValueError('"affirm_label"/"deny_label" only apply to kind="confirm"')

        if self.kind == "datetime":
            if self.mode is None:
                raise ValueError('kind="datetime" requires "mode"')
        elif self.mode is not None or self.min_iso is not None or self.max_iso is not None:
            raise ValueError(f'kind="{self.kind}" must not set datetime-only attributes')

        return self


# ---------------------------------------------------------------------------
# The request itself
# ---------------------------------------------------------------------------

class SourceRef(BaseModel):
    """Provenance for a UIRequest adapted from something other than a live
    agent tool call — e.g. a knowledge-graph PendingQuestion (Fase 2)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["knowledge_question"]
    id: str


class LearnDirective(BaseModel):
    """Optional, explicit instruction: when this request is answered, write
    a claim to the knowledge-graph entity ``entity_id``. Never implicit —
    an interaction answer only ever touches the knowledge graph when the
    model asked for exactly this, via ``record_user_claim``
    (app/services/agent/knowledge/answer.py), which is a distinct write
    path from confirm_pending_answer and does not touch PendingQuestion.

    ``claim_template`` is filled server-side with the answer's raw field
    values via a plain regex substitution of ``{field_key}`` tokens (see
    ``app.services.agent.knowledge.answer._render_claim_template``) —
    deliberately not ``str.format()``/``format_map()``, which interpret
    Python's format-spec mini-language and so expose more surface than a
    fixed-token substitution needs. Never LLM-rendered at answer time: the
    template is fixed when the request is authored, only the values change.
    """

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    claim_template: str = Field(max_length=500)


class UIRequestContent(BaseModel):
    """The subset of a request an LLM tool call actually authors.

    No ``request_id`` (server-assigned) and no ``source`` (server-attached
    provenance) — see the module docstring, point 5.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    kicker: Kicker = "needs_datum"
    prompt: List[TextSpan] = Field(min_length=1, max_length=MAX_PROMPT_SPANS)
    fields: List[UIField] = Field(min_length=1, max_length=MAX_FIELDS)
    submit_label: str = Field(max_length=40)
    allow_dismiss: bool = True
    learn: Optional[LearnDirective] = None

    @model_validator(mode="after")
    def _unique_field_keys(self) -> "UIRequestContent":
        keys = [f.key for f in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("field keys must be unique within a request")
        return self

    @model_validator(mode="after")
    def _learn_template_only_references_known_fields(self) -> "UIRequestContent":
        if self.learn is not None:
            keys = {f.key for f in self.fields}
            referenced = set(_TEMPLATE_KEY_PATTERN.findall(self.learn.claim_template))
            unknown = referenced - keys
            if unknown:
                raise ValueError(f'"learn.claim_template" references unknown field keys: {sorted(unknown)}')
        return self


class UIRequest(UIRequestContent):
    """The full request as sent to the client. The only shape a client
    ever receives — never ``UIRequestContent`` directly."""

    request_id: str
    source: Optional[SourceRef] = None


# ---------------------------------------------------------------------------
# Artifacts — a preview born from answering a request
# ---------------------------------------------------------------------------

class EmailAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, max_length=120)
    address: str = Field(max_length=254)


class EmailDraftArtifact(BaseModel):
    """A drafted email preview. ``body_paragraphs`` is plain text, one
    paragraph per client-rendered ``<p>`` — never a single blob that could
    smuggle markdown/HTML formatting."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["email_draft"] = "email_draft"
    to: List[EmailAddress] = Field(min_length=1, max_length=10)
    cc: List[EmailAddress] = Field(default_factory=list, max_length=10)
    subject: str = Field(max_length=200)
    body_paragraphs: List[str] = Field(min_length=1, max_length=20)
    footnote_token: Optional[Literal["drafted_by_assistant"]] = None


class KeyValueRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=80)
    value: str = Field(max_length=400)
    tone: Literal["neutral", "good", "warn"] = "neutral"


class KeyValuesArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["key_values"] = "key_values"
    title: str = Field(max_length=120)
    rows: List[KeyValueRow] = Field(min_length=1, max_length=20)


Artifact = Union[EmailDraftArtifact, KeyValuesArtifact]
