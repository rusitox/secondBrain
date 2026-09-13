"""Unit tests for app.api.routers.interactions._validate_answer — checks a
submitted interaction answer against each field's own kind-specific
contract, not just key presence. This matters beyond form correctness: an
unvalidated value can flow into a knowledge-graph claim via the `learn`
directive (apply_learn_directive) at CONFIRMED_BY_USER/1.0 confidence.
"""
from app.api.routers.interactions import _validate_answer

_SELECT_SPEC = {
    "fields": [{
        "key": "decision", "kind": "single_select", "label": "Decisión", "required": True,
        "options": [{"id": "approve", "label": "Aprobar"}, {"id": "reject", "label": "Rechazar"}],
    }],
}


class TestRequiredFields:
    def test_missing_required_field_is_an_error(self) -> None:
        errors = _validate_answer(_SELECT_SPEC, {})
        assert len(errors) == 1

    def test_missing_optional_field_is_not_an_error(self) -> None:
        spec = {"fields": [{"key": "comment", "kind": "text", "required": False}]}
        assert _validate_answer(spec, {}) == []

    def test_missing_optional_single_select_is_not_an_error(self) -> None:
        """The contract the client relies on when a user leaves an
        optional single_select/entity_pick untouched: the key must be
        OMITTED from the answer body, not sent as "" — "" is never a
        member of option_ids, so sending it would fail the value check
        below even though nothing was required (frontend fix: seed such
        fields to `undefined`, which JSON.stringify drops from the body)."""
        spec = {"fields": [{
            "key": "decision", "kind": "single_select", "required": False,
            "options": [{"id": "approve", "label": "Aprobar"}],
        }]}
        assert _validate_answer(spec, {}) == []

    def test_empty_string_for_optional_single_select_is_still_rejected(self) -> None:
        """Documents why omitting the key (not sending "") is required."""
        spec = {"fields": [{
            "key": "decision", "kind": "single_select", "required": False,
            "options": [{"id": "approve", "label": "Aprobar"}],
        }]}
        assert len(_validate_answer(spec, {"decision": ""})) == 1


class TestSingleSelectAndEntityPick:
    def test_valid_option_id_passes(self) -> None:
        assert _validate_answer(_SELECT_SPEC, {"decision": "approve"}) == []

    def test_unknown_option_id_is_rejected(self) -> None:
        errors = _validate_answer(_SELECT_SPEC, {"decision": "not_an_option"})
        assert len(errors) == 1

    def test_non_string_value_is_rejected(self) -> None:
        errors = _validate_answer(_SELECT_SPEC, {"decision": 123})
        assert len(errors) == 1

    def test_entity_pick_allow_none_accepts_null(self) -> None:
        spec = {"fields": [{
            "key": "who", "kind": "entity_pick", "required": True, "allow_none": True,
            "options": [{"id": "e1", "label": "Valentina"}],
        }]}
        assert _validate_answer(spec, {"who": None}) == []

    def test_entity_pick_without_allow_none_rejects_null(self) -> None:
        spec = {"fields": [{
            "key": "who", "kind": "entity_pick", "required": True, "allow_none": False,
            "options": [{"id": "e1", "label": "Valentina"}],
        }]}
        assert len(_validate_answer(spec, {"who": None})) == 1


class TestMultiSelect:
    _SPEC = {"fields": [{
        "key": "tags", "kind": "multi_select", "required": True,
        "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
        "min_select": 1, "max_select": 2,
    }]}

    def test_valid_selection_passes(self) -> None:
        assert _validate_answer(self._SPEC, {"tags": ["a", "b"]}) == []

    def test_unknown_option_in_list_is_rejected(self) -> None:
        assert len(_validate_answer(self._SPEC, {"tags": ["a", "nope"]})) == 1

    def test_non_list_value_is_rejected(self) -> None:
        assert len(_validate_answer(self._SPEC, {"tags": "a"})) == 1

    def test_below_min_select_is_rejected(self) -> None:
        assert len(_validate_answer(self._SPEC, {"tags": []})) == 1

    def test_above_max_select_is_rejected(self) -> None:
        assert len(_validate_answer(self._SPEC, {"tags": ["a", "b", "c"]})) == 1


class TestConfirm:
    _SPEC = {"fields": [{"key": "ok", "kind": "confirm", "required": True}]}

    def test_boolean_true_passes(self) -> None:
        assert _validate_answer(self._SPEC, {"ok": True}) == []

    def test_boolean_false_passes(self) -> None:
        assert _validate_answer(self._SPEC, {"ok": False}) == []

    def test_non_boolean_is_rejected(self) -> None:
        assert len(_validate_answer(self._SPEC, {"ok": "yes"})) == 1


class TestText:
    def test_within_max_length_passes(self) -> None:
        spec = {"fields": [{"key": "comment", "kind": "text", "required": True, "max_length": 10}]}
        assert _validate_answer(spec, {"comment": "short"}) == []

    def test_exceeding_max_length_is_rejected(self) -> None:
        spec = {"fields": [{"key": "comment", "kind": "text", "required": True, "max_length": 5}]}
        assert len(_validate_answer(spec, {"comment": "way too long"})) == 1

    def test_non_string_value_is_rejected(self) -> None:
        spec = {"fields": [{"key": "comment", "kind": "text", "required": True}]}
        assert len(_validate_answer(spec, {"comment": 42})) == 1


class TestMultipleFields:
    def test_reports_one_error_per_invalid_field(self) -> None:
        spec = {
            "fields": [
                {"key": "decision", "kind": "single_select", "required": True,
                 "options": [{"id": "approve", "label": "Aprobar"}]},
                {"key": "ok", "kind": "confirm", "required": True},
            ],
        }
        errors = _validate_answer(spec, {"decision": "bogus", "ok": "not-a-bool"})
        assert len(errors) == 2

    def test_malformed_spec_with_non_list_fields_returns_no_errors(self) -> None:
        assert _validate_answer({"fields": "not-a-list"}, {"x": 1}) == []
