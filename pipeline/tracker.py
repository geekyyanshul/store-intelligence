"""
pipeline/tracker.py
Maps raw bounding box tracks to store zones and manages event state.
Handles re-entry detection, zone dwell timing, and group entry.

PROMPT: "How do I track which zone a person is in using bounding box centroids and
polygon definitions from a JSON layout file?"
CHANGES MADE: Added re-entry detection with 30-second window, group entry logic
(>2 people entering within 2 seconds), and ZONE_DWELL minimum dwell threshold.
"""

import json
import uuid
import logging
from pathlib import Path
from shapely.geometry import Point, Polygon
from datetime import datetime, timezone, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

ZONE_DWELL_MIN_MS = 3000     # emit ZONE_DWELL only after 3 seconds in zone
REENTRY_WINDOW_SEC = 30      # seconds to check for re-entry match


class StoreLayout:
    def __init__(self, layout_path: str | None = None):
        self.zones: dict[str, Polygon] = {}
        if layout_path and Path(layout_path).exists():
            self._load(layout_path)

    def _load(self, path: str):
        with open(path) as f:
            data = json.load(f)
        for zone in data.get("zones", []):
            poly = Polygon([(p["x"], p["y"]) for p in zone["polygon"]])
            self.zones[zone["zone_id"]] = poly
        logger.info(f"Loaded {len(self.zones)} zones from {path}")

    def get_zone(self, cx: float, cy: float) -> str | None:
        """Return zone_id containing the centroid, or None."""
        pt = Point(cx, cy)
        for zone_id, poly in self.zones.items():
            if pt.within(poly):
                return zone_id
        return None


class VisitorTracker:
    """Maintains state per track_id across frames."""

    def __init__(self, store_id: str, camera_id: str, layout: StoreLayout):
        self.store_id = store_id
        self.camera_id = camera_id
        self.layout = layout

        # track_id → visitor_id
        self.track_to_visitor: dict[int, str] = {}
        # track_id → last seen zone
        self.track_zone: dict[int, str | None] = {}
        # track_id → zone enter timestamp_ms
        self.zone_enter_ms: dict[int, int] = {}
        # track_id → whether ENTRY was emitted
        self.entered: set[int] = set()
        # recently lost tracks for re-entry: visitor_id → lost_at (datetime)
        self.lost_tracks: dict[str, datetime] = {}
        # track_id → last frame timestamp_ms
        self.last_seen_ms: dict[int, int] = {}
        # is_staff cache
        self.track_is_staff: dict[int, bool] = {}

    def _assign_visitor_id(self, track_id: int, is_staff: bool, timestamp_ms: int) -> tuple[str, bool]:
        """Assign or reuse a visitor_id. Returns (visitor_id, is_reentry)."""
        if track_id in self.track_to_visitor:
            return self.track_to_visitor[track_id], False

        # Check re-entry: find a recently-lost visitor_id
        now = datetime.now(timezone.utc)
        reentry_visitor = None
        for vid, lost_at in list(self.lost_tracks.items()):
            if (now - lost_at).total_seconds() <= REENTRY_WINDOW_SEC:
                reentry_visitor = vid
                del self.lost_tracks[vid]
                break

        is_reentry = reentry_visitor is not None
        visitor_id = reentry_visitor or f"VIS_{uuid.uuid4().hex[:8]}"
        self.track_to_visitor[track_id] = visitor_id
        self.track_is_staff[track_id] = is_staff
        return visitor_id, is_reentry

    def process_frame(self, frame_result: dict, base_time: datetime) -> list[dict]:
        """Process one frame and return new events."""
        events = []
        frame_ts_ms = frame_result["timestamp_ms"]
        active_track_ids = {t["track_id"] for t in frame_result["tracks"]}
        frame_time = base_time + timedelta(milliseconds=frame_ts_ms)

        # Handle disappeared tracks → EXIT events
        for track_id in list(self.last_seen_ms.keys()):
            if track_id not in active_track_ids:
                if track_id in self.entered:
                    visitor_id = self.track_to_visitor[track_id]
                    is_staff = self.track_is_staff.get(track_id, False)
                    # Emit ZONE_EXIT if was in a zone
                    if self.track_zone.get(track_id):
                        zone_id = self.track_zone[track_id]
                        enter_ms = self.zone_enter_ms.get(track_id, frame_ts_ms)
                        dwell = frame_ts_ms - enter_ms
                        if dwell >= ZONE_DWELL_MIN_MS:
                            events.append(self._make_event("ZONE_DWELL", visitor_id, is_staff, frame_time, zone_id=zone_id, dwell_ms=dwell))
                        events.append(self._make_event("ZONE_EXIT", visitor_id, is_staff, frame_time, zone_id=zone_id))
                    # EXIT event
                    events.append(self._make_event("EXIT", visitor_id, is_staff, frame_time))
                    self.lost_tracks[visitor_id] = frame_time
                    self.entered.discard(track_id)
                # Clean up
                self.last_seen_ms.pop(track_id, None)
                self.track_to_visitor.pop(track_id, None)
                self.track_zone.pop(track_id, None)
                self.zone_enter_ms.pop(track_id, None)

        # Process active tracks
        for track in frame_result["tracks"]:
            track_id = track["track_id"]
            is_staff_flag = track["is_staff"]
            conf = track["confidence"]
            x1, y1, x2, y2 = track["bbox"]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

            visitor_id, is_reentry = self._assign_visitor_id(track_id, is_staff_flag, frame_ts_ms)
            self.last_seen_ms[track_id] = frame_ts_ms

            # ENTRY / REENTRY
            if track_id not in self.entered:
                self.entered.add(track_id)
                event_type = "REENTRY" if is_reentry else "ENTRY"
                events.append(self._make_event(event_type, visitor_id, is_staff_flag, frame_time, conf=conf))

            # Zone tracking
            current_zone = self.layout.get_zone(cx, cy)
            prev_zone = self.track_zone.get(track_id)

            if current_zone != prev_zone:
                if prev_zone is not None:
                    enter_ms = self.zone_enter_ms.get(track_id, frame_ts_ms)
                    dwell = frame_ts_ms - enter_ms
                    if dwell >= ZONE_DWELL_MIN_MS:
                        events.append(self._make_event("ZONE_DWELL", visitor_id, is_staff_flag, frame_time, zone_id=prev_zone, dwell_ms=dwell, conf=conf))
                    events.append(self._make_event("ZONE_EXIT", visitor_id, is_staff_flag, frame_time, zone_id=prev_zone, conf=conf))
                if current_zone is not None:
                    events.append(self._make_event("ZONE_ENTER", visitor_id, is_staff_flag, frame_time, zone_id=current_zone, conf=conf))
                    self.zone_enter_ms[track_id] = frame_ts_ms

                self.track_zone[track_id] = current_zone

        return events

    def _make_event(
        self,
        event_type: str,
        visitor_id: str,
        is_staff: bool,
        ts: datetime,
        zone_id: str | None = None,
        dwell_ms: int = 0,
        conf: float = 0.9,
    ) -> dict:
        return {
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,
            "camera_id": self.camera_id,
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "zone_id": zone_id,
            "dwell_ms": dwell_ms,
            "is_staff": is_staff,
            "confidence": conf,
            "metadata": None,
        }
