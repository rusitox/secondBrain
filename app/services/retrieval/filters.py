"""Search filters for retrieval queries."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class SearchFilters:
    """Filters applied to semantic search results.

    All filters are optional; when set, they narrow the result set.
    """

    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    source: Optional[str] = None
    sources: List[str] = field(default_factory=list)
    author: Optional[str] = None
