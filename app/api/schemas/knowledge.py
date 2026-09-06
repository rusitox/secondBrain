from typing import Dict, Optional

from pydantic import BaseModel


class KnowledgeStatsResponse(BaseModel):
    total_entities: int
    entities_by_confidence: Dict[str, int]
    entities_by_type: Dict[str, int]
    total_claims: int
    claims_by_source: Dict[str, int]
    claims_by_status: Dict[str, int]
    pending_questions_open: int
    pending_questions_by_target: Dict[str, int]
    entities_merged_recent: int
    merged_window_hours: int
    scheduler_active: bool
    next_scheduled_run: Optional[str] = None
