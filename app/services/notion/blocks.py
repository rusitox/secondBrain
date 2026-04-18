"""Bidirectional conversion between Notion blocks and plain text.

Notion pages are composed of nested block objects. This module converts
them to plain text for embedding, and from markdown-ish text back to
Notion blocks for publishing.
"""
import re
from typing import Any, Dict, List


def extract_rich_text(rich_text_array: List[Dict[str, Any]]) -> str:
    """Extract plain text from a Notion rich_text array.

    Each element has a ``plain_text`` field.  We concatenate them.
    """
    parts: List[str] = []
    for item in rich_text_array:
        text = item.get("plain_text", "")
        if text:
            parts.append(text)
    return "".join(parts)


def _extract_block_text(block: Dict[str, Any]) -> str:
    """Return the rich_text content of a block, regardless of type."""
    btype = block.get("type", "")
    data = block.get(btype, {})
    rich_text = data.get("rich_text", [])
    return extract_rich_text(rich_text)


def _convert_block(block: Dict[str, Any], depth: int = 0) -> str:
    """Convert a single Notion block to a text line."""
    btype = block.get("type", "")
    text = _extract_block_text(block)

    if btype in ("paragraph", "toggle"):
        return text

    if btype == "heading_1":
        return "# " + text

    if btype == "heading_2":
        return "## " + text

    if btype == "heading_3":
        return "### " + text

    if btype == "bulleted_list_item":
        indent = "  " * depth
        return indent + "- " + text

    if btype == "numbered_list_item":
        indent = "  " * depth
        return indent + "1. " + text

    if btype == "to_do":
        data = block.get("to_do", {})
        checked = data.get("checked", False)
        marker = "[x]" if checked else "[ ]"
        return marker + " " + text

    if btype == "code":
        data = block.get("code", {})
        lang = data.get("language", "")
        return "```%s\n%s\n```" % (lang, text)

    if btype == "quote":
        return "> " + text

    if btype == "callout":
        data = block.get("callout", {})
        icon = data.get("icon", {})
        emoji = icon.get("emoji", "") if icon else ""
        prefix = emoji + " " if emoji else ""
        return "> " + prefix + text

    if btype == "divider":
        return "---"

    if btype == "table_row":
        data = block.get("table_row", {})
        cells = data.get("cells", [])
        cell_texts = [extract_rich_text(cell) for cell in cells]
        return "| " + " | ".join(cell_texts) + " |"

    # Blocks we intentionally skip (fetched separately or non-text)
    if btype in (
        "child_page", "child_database",
        "image", "file", "video", "embed", "pdf",
        "bookmark", "link_preview", "link_to_page",
        "table_of_contents", "breadcrumb", "column_list", "column",
        "synced_block", "template", "unsupported",
    ):
        return ""

    # Unknown block type — return text if any, else skip
    return text


def blocks_to_text(
    blocks: List[Dict[str, Any]],
    depth: int = 0,
    max_depth: int = 3,
) -> str:
    """Convert a list of Notion blocks to plain text.

    Args:
        blocks: List of Notion block objects.
        depth: Current nesting depth (for indentation of list items).
        max_depth: Maximum recursion depth for child blocks.

    Returns:
        Plain text representation of the blocks.
    """
    lines: List[str] = []

    for block in blocks:
        line = _convert_block(block, depth=depth)
        if line:
            lines.append(line)

        # Recurse into children if present and within depth limit
        children = block.get("children", [])
        if children and depth < max_depth:
            child_text = blocks_to_text(children, depth=depth + 1, max_depth=max_depth)
            if child_text:
                lines.append(child_text)

    return "\n".join(lines)


# ── Text → Notion blocks (for publishing) ──────────────────────


_MAX_TEXT_LENGTH = 2000


def _rich_text(text: str) -> List[Dict[str, Any]]:
    """Wrap plain text in a Notion rich_text array, splitting at 2000-char limit."""
    if not text:
        return []
    chunks: List[Dict[str, Any]] = []
    for i in range(0, len(text), _MAX_TEXT_LENGTH):
        chunks.append({"type": "text", "text": {"content": text[i:i + _MAX_TEXT_LENGTH]}})
    return chunks


def _paragraph_block(text: str) -> Dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(text)}}


def _heading_block(text: str, level: int) -> Dict[str, Any]:
    key = "heading_%d" % level
    return {"object": "block", "type": key, key: {"rich_text": _rich_text(text)}}


def _bullet_block(text: str) -> Dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text(text)},
    }


def _numbered_block(text: str) -> Dict[str, Any]:
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": _rich_text(text)},
    }


def _quote_block(text: str) -> Dict[str, Any]:
    return {"object": "block", "type": "quote", "quote": {"rich_text": _rich_text(text)}}


def _code_block(text: str, language: str) -> Dict[str, Any]:
    return {
        "object": "block",
        "type": "code",
        "code": {"rich_text": _rich_text(text), "language": language or "plain text"},
    }


def _divider_block() -> Dict[str, Any]:
    return {"object": "block", "type": "divider", "divider": {}}


def _todo_block(text: str, checked: bool) -> Dict[str, Any]:
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": _rich_text(text), "checked": checked},
    }


# Patterns for line-level parsing
_RE_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
_RE_BULLET = re.compile(r"^\s*[-*]\s+(.+)$")
_RE_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.+)$")
_RE_QUOTE = re.compile(r"^>\s?(.*)$")
_RE_TODO = re.compile(r"^\[([xX ])\]\s+(.+)$")
_RE_CODE_FENCE = re.compile(r"^```(\w*)$")
_RE_DIVIDER = re.compile(r"^---+$")


def text_to_blocks(text: str) -> List[Dict[str, Any]]:
    """Convert markdown-ish text to a list of Notion block objects.

    Supports: headings, bullets, numbered lists, quotes, code fences,
    dividers, to-do items, and plain paragraphs.
    """
    blocks: List[Dict[str, Any]] = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Empty line → skip
        if not line.strip():
            i += 1
            continue

        # Divider
        m = _RE_DIVIDER.match(line)
        if m:
            blocks.append(_divider_block())
            i += 1
            continue

        # Heading
        m = _RE_HEADING.match(line)
        if m:
            level = min(len(m.group(1)), 3)
            blocks.append(_heading_block(m.group(2), level))
            i += 1
            continue

        # Code fence
        m = _RE_CODE_FENCE.match(line)
        if m:
            lang = m.group(1)
            code_lines: List[str] = []
            i += 1
            while i < len(lines) and not _RE_CODE_FENCE.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            blocks.append(_code_block("\n".join(code_lines), lang))
            continue

        # To-do
        m = _RE_TODO.match(line)
        if m:
            checked = m.group(1).lower() == "x"
            blocks.append(_todo_block(m.group(2), checked))
            i += 1
            continue

        # Quote
        m = _RE_QUOTE.match(line)
        if m:
            blocks.append(_quote_block(m.group(1)))
            i += 1
            continue

        # Bullet
        m = _RE_BULLET.match(line)
        if m:
            blocks.append(_bullet_block(m.group(1)))
            i += 1
            continue

        # Numbered list
        m = _RE_NUMBERED.match(line)
        if m:
            blocks.append(_numbered_block(m.group(1)))
            i += 1
            continue

        # Default: paragraph
        blocks.append(_paragraph_block(line))
        i += 1

    return blocks
