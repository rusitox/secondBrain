"""Text chunking for embedding pipeline.

Uses RecursiveCharacterTextSplitter from LangChain to split
cleaned text into overlapping chunks suitable for embedding.
"""
import logging
from typing import List

from langchain.text_splitter import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

# Default chunking parameters (per spec: ~500-1000 tokens ≈ 800 chars, 100 overlap)
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100

# Separators ordered by preference: paragraphs → sentences → words → chars
DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    separators: List[str] = None,
) -> List[str]:
    """Split text into overlapping chunks for embedding.

    Returns an empty list for empty/whitespace-only input.
    Returns a single-element list if text is shorter than chunk_size.
    """
    if not text or not text.strip():
        return []

    stripped = text.strip()
    if len(stripped) <= chunk_size:
        return [stripped]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators or DEFAULT_SEPARATORS,
        length_function=len,
        strip_whitespace=True,
    )
    chunks = splitter.split_text(stripped)
    logger.debug("Chunked text (%d chars) into %d chunks", len(stripped), len(chunks))
    return chunks
