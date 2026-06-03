from typing import Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime

class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: Optional[int] = None

class DetectionEvent(BaseModel):
    event_id: str = Field(..., description="Must be globally unique uuid-v4")
    store_id: str = Field(..., description="from store_layout.json")
    camera_id: str = Field(..., description="which camera produced this event")
    visitor_id: str = Field(..., description="unique per visit session")
    event_type: Literal[
        "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL", 
        "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY"
    ]
    timestamp: datetime = Field(..., description="ISO-8601 UTC")
    zone_id: Optional[str] = Field(None, description="null for ENTRY / EXIT events")
    dwell_ms: int = Field(..., description="duration; 0 for instantaneous events")
    is_staff: bool = Field(..., description="true if classified as staff")
    confidence: float = Field(..., description="detection confidence")
    metadata: Optional[EventMetadata] = None
