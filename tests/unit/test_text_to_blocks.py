"""Unit tests for text_to_blocks conversion (text → Notion blocks)."""
import pytest

from app.services.notion.blocks import text_to_blocks


class TestTextToBlocks:
    def test_paragraph(self) -> None:
        blocks = text_to_blocks("Hello world")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "paragraph"
        assert blocks[0]["paragraph"]["rich_text"][0]["text"]["content"] == "Hello world"

    def test_heading_1(self) -> None:
        blocks = text_to_blocks("# Title")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_1"
        assert blocks[0]["heading_1"]["rich_text"][0]["text"]["content"] == "Title"

    def test_heading_2(self) -> None:
        blocks = text_to_blocks("## Section")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_2"

    def test_heading_3(self) -> None:
        blocks = text_to_blocks("### Subsection")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "heading_3"

    def test_bullet_list(self) -> None:
        blocks = text_to_blocks("- Item A\n- Item B")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "bulleted_list_item"
        assert blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "Item A"
        assert blocks[1]["type"] == "bulleted_list_item"

    def test_bullet_with_asterisk(self) -> None:
        blocks = text_to_blocks("* Starred item")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "bulleted_list_item"

    def test_numbered_list(self) -> None:
        blocks = text_to_blocks("1. First\n2. Second")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "numbered_list_item"
        assert blocks[0]["numbered_list_item"]["rich_text"][0]["text"]["content"] == "First"

    def test_quote(self) -> None:
        blocks = text_to_blocks("> Some quote")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "quote"
        assert blocks[0]["quote"]["rich_text"][0]["text"]["content"] == "Some quote"

    def test_code_block(self) -> None:
        text = "```python\nprint('hi')\n```"
        blocks = text_to_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "code"
        assert blocks[0]["code"]["language"] == "python"
        assert blocks[0]["code"]["rich_text"][0]["text"]["content"] == "print('hi')"

    def test_code_block_no_language(self) -> None:
        text = "```\nsome code\n```"
        blocks = text_to_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "code"
        assert blocks[0]["code"]["language"] == "plain text"

    def test_divider(self) -> None:
        blocks = text_to_blocks("---")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "divider"

    def test_long_divider(self) -> None:
        blocks = text_to_blocks("------")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "divider"

    def test_todo_checked(self) -> None:
        blocks = text_to_blocks("[x] Done task")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "to_do"
        assert blocks[0]["to_do"]["checked"] is True
        assert blocks[0]["to_do"]["rich_text"][0]["text"]["content"] == "Done task"

    def test_todo_unchecked(self) -> None:
        blocks = text_to_blocks("[ ] Open task")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "to_do"
        assert blocks[0]["to_do"]["checked"] is False

    def test_empty_text(self) -> None:
        blocks = text_to_blocks("")
        assert blocks == []

    def test_blank_lines_skipped(self) -> None:
        blocks = text_to_blocks("First\n\n\nSecond")
        assert len(blocks) == 2
        assert blocks[0]["type"] == "paragraph"
        assert blocks[1]["type"] == "paragraph"

    def test_mixed_content(self) -> None:
        text = "# Title\n\nSome paragraph\n\n- Bullet 1\n- Bullet 2\n\n> A quote\n\n---"
        blocks = text_to_blocks(text)
        types = [b["type"] for b in blocks]
        assert types == [
            "heading_1", "paragraph",
            "bulleted_list_item", "bulleted_list_item",
            "quote", "divider",
        ]

    def test_all_blocks_have_object_field(self) -> None:
        text = "# H\n- B\n1. N\n> Q\n---\n[x] T\nParagraph"
        blocks = text_to_blocks(text)
        for block in blocks:
            assert block.get("object") == "block"
