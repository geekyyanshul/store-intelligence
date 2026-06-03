"""
pipeline/detect.py
Detects persons in a CCTV video clip using YOLOv8 and ByteTrack.
Returns tracked bounding boxes per frame with assigned track IDs.

PROMPT: "How do I integrate YOLOv8 with ByteTrack in Python for multi-person tracking?"
CHANGES MADE: Added staff colour-histogram exclusion, confidence thresholds tuned for
retail CCTV, and graceful handling of frames with no detections.
"""

import cv2
import numpy as np
from ultralytics import YOLO
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

PERSON_CLASS_ID = 0          # COCO class 0 = person
DETECT_CONF_THRESHOLD = 0.5  # minimum detection confidence
STAFF_DIST_THRESHOLD = 0.35  # Bhattacharyya distance for staff detection


def build_staff_histogram(sample_bgr_images: list) -> np.ndarray | None:
    """Build a reference colour histogram from staff uniform samples."""
    if not sample_bgr_images:
        return None
    combined = []
    for img in sample_bgr_images:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        combined.append(hsv)
    ref = np.vstack(combined)
    hist = cv2.calcHist([ref], [0, 1], None, [36, 32], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def is_staff(crop_bgr: np.ndarray, staff_hist: np.ndarray | None, threshold: float = STAFF_DIST_THRESHOLD) -> bool:
    """Return True if the cropped bounding box matches staff uniform colours."""
    if staff_hist is None:
        return False
    h, w = crop_bgr.shape[:2]
    torso = crop_bgr[:h // 2, :]  # top half = torso region
    hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [36, 32], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    dist = cv2.compareHist(staff_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
    return dist < threshold


def load_model(model_path: str = "yolov8n.pt") -> YOLO:
    """Load YOLOv8 model (downloads automatically on first run)."""
    logger.info(f"Loading model: {model_path}")
    model = YOLO(model_path)
    return model


def process_video(
    video_path: str,
    model: YOLO,
    staff_hist: np.ndarray | None = None,
    skip_frames: int = 2,
) -> list[dict]:
    """
    Process a video clip and return a list of track frames.

    Returns:
        List of dicts: {frame_idx, timestamp_ms, tracks: [{track_id, bbox, confidence, is_staff}]}
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_results = []
    frame_idx = 0

    logger.info(f"Processing {video_path} at {fps:.1f} fps")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % (skip_frames + 1) != 0:
            frame_idx += 1
            continue

        timestamp_ms = int((frame_idx / fps) * 1000)

        # Run detection + tracking
        results = model.track(
            frame,
            persist=True,
            classes=[PERSON_CLASS_ID],
            conf=DETECT_CONF_THRESHOLD,
            iou=0.5,
            tracker="bytetrack.yaml",
            verbose=False,
        )

        tracks = []
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            for box in boxes:
                if box.id is None:
                    continue
                track_id = int(box.id.item())
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                conf = float(box.conf[0].item())

                crop = frame[max(0, y1):y2, max(0, x1):x2]
                staff = is_staff(crop, staff_hist) if crop.size > 0 else False

                tracks.append({
                    "track_id": track_id,
                    "bbox": [x1, y1, x2, y2],
                    "confidence": round(conf, 3),
                    "is_staff": staff,
                })

        frame_results.append({
            "frame_idx": frame_idx,
            "timestamp_ms": timestamp_ms,
            "tracks": tracks,
        })
        frame_idx += 1

    cap.release()
    logger.info(f"Processed {frame_idx} frames, found {len(frame_results)} sampled frames")
    return frame_results
