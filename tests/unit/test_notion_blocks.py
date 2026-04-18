"""Unit tests for Notion blocks-to-text conversion."""
import pytest

from app.services.notion.blocks import blocks_to_text, extract_rich_text


class TestExtractRichText:
    def test_single_element(self) -> None:
        arr = [{"plain_text": "Hello world"}]
        assert extract_rich_text(arr) == "Hello world"

    def test_multiple_elements(self) -> None:
        arr = [
            {"plain_text": "Hello "},
            {"plain_text": "world"},
        ]
        assert extract_rich_text(arr) == "Hello world"

    def test_empty_array(self) -> None:
        assert extract_rich_text([]) == ""

    def test_missing_plain_text(self) -> None:
        arr = [{"type": "text"}]
        assert extract_rich_text(arr) == ""


class TestBlocksToText:
    def test_paragraph(self) -> None:
        blocks = [
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Some text"}]}},
        ]
        assert blocks_to_text(blocks) == "Some text"

    def test_heading_1(self) -> None:
        blocks = [
            {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Title"}]}},
        ]
        assert blocks_to_text(blocks) == "# Title"

    def test_heading_2(self) -> None:
        blocks = [
            {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Section"}]}},
        ]
        assert blocks_to_text(blocks) == "## Section"

    def test_heading_3(self) -> None:
        blocks = [
            {"type": "heading_3", "heading_3": {"rich_text": [{"plain_text": "Sub"}]}},
        ]
        assert blocks_to_text(blocks) == "### Sub"

    def test_bulleted_list(self) -> None:
        blocks = [
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "Item A"}]}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "Item B"}]}},
        ]
        result = blocks_to_text(blocks)
        assert "- Item A" in result
        assert "- Item B" in result

    def test_numbered_list(self) -> None:
        blocks = [
            {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "First"}]}},
        ]
        assert blocks_to_text(blocks) == "1. First"

    def test_to_do_checked(self) -> None:
        blocks = [
            {"type": "to_do", "to_do": {"rich_text": [{"plain_text": "Done task"}], "checked": True}},
        ]
        assert blocks_to_text(blocks) == "[x] Done task"

    def test_to_do_unchecked(self) -> None:
        blocks = [
            {"type": "to_do", "to_do": {"rich_text": [{"plain_text": "Open task"}], "checked": False}},
        ]
        assert blocks_to_text(blocks) == "[ ] Open task"

    def test_code_block(self) -> None:
        blocks = [
            {"type": "code", "code": {"rich_text": [{"plain_text": "print('hi')"}], "language": "python"}},
        ]
        result = blocks_to_text(blocks)
        assert "```python" in result
        assert "print('hi')" in result
        assert result.endswith("```")

    def test_quote(self) -> None:
        blocks = [
            {"type": "quote", "quote": {"rich_text": [{"plain_text": "Wise words"}]}},
        ]
        assert blocks_to_text(blocks) == "> Wise words"

    def test_callout_with_emoji(self) -> None:
        blocks = [
            {
                "type": "callout",
                "callout": {
                    "rich_text": [{"plain_text": "Important"}],
                    "icon": {"type": "emoji", "emoji": "!"},
                },
            },
        ]
        result = blocks_to_text(blocks)
        assert "> " in result
        assert "Important" in result

    def test_divider(self) -> None:
        blocks = [{"type": "divider", "divider": {}}]
        assert blocks_to_text(blocks) == "---"

    def test_table_row(self) -> None:
        blocks = [
            {
                "type": "table_row",
                "table_row": {
                    "cells": [
                        [{"plain_text": "A"}],
                        [{"plain_text": "B"}],
                        [{"plain_text": "C"}],
                    ],
                },
            },
        ]
        assert blocks_to_text(blocks) == "| A | B | C |"

    def test_skipped_blocks(self) -> None:
        blocks = [
            {"type": "child_page", "child_page": {"title": "Sub page"}},
            {"type": "image", "image": {"type": "external"}},
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Keep me"}]}},
        ]
        result = blocks_to_text(blocks)
        assert "Sub page" not in result
        assert "Keep me" in result

    def test_nested_children(self) -> None:
        blocks = [
            {
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"plain_text": "Parent"}]},
                "children": [
                    {
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [{"plain_text": "Child"}]},
                    },
                ],
            },
        ]
        result = blocks_to_text(blocks)
        assert "- Parent" in result
        assert "  - Child" in result

    def test_max_depth_stops_recursion(self) -> None:
        deep_block = {
            "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": "deep"}]},
            "children": [
                {
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"plain_text": "deeper"}]},
                },
            ],
        }
        result = blocks_to_text([deep_block], depth=0, max_depth=1)
        assert "deep" in result
        assert "deeper" in result

        # At max depth, children should not be processed
        result2 = blocks_to_text([deep_block], depth=3, max_depth=3)
        assert "deep" in result2
        assert "deeper" not in result2

    def test_empty_blocks(self) -> None:
        assert blocks_to_text([]) == ""

    def test_toggle_block(self) -> None:
        blocks = [
            {"type": "toggle", "toggle": {"rich_text": [{"plain_text": "Toggle text"}]}},
        ]
        assert blocks_to_text(blocks) == "Toggle text"

    def test_unknown_type_with_text(self) -> None:
        blocks = [
            {"type": "new_fancy_block", "new_fancy_block": {"rich_text": [{"plain_text": "Future"}]}},
        ]
        assert blocks_to_text(blocks) == "Future"

    def test_unknown_type_without_text(self) -> None:
        blocks = [
            {"type": "some_empty_block", "some_empty_block": {}},
        ]
        assert blocks_to_text(blocks) == ""
