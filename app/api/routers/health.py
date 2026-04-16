from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    message: str


@router.get("/", response_model=HealthResponse)
async def root() -> dict:
    return {"status": "online", "message": "Digital Twin Core is active and ready."}
