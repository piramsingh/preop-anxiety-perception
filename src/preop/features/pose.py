"""MediaPipe Pose wrapper. The model file is downloaded once, then all inference is local."""

import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

from preop.features.body import Person

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_full/float16/1/pose_landmarker_full.task"
)
DEFAULT_MODEL = Path("models/pose_landmarker_full.task")


def ensure_model(path: Path = DEFAULT_MODEL) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading pose model to {path} (first run only)")
        partial = path.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL, partial)
        partial.rename(path)
    return path


class PoseExtractor:
    def __init__(self, num_poses: int = 2, model_path: Path = DEFAULT_MODEL) -> None:
        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ensure_model(model_path))),
            running_mode=RunningMode.VIDEO,
            num_poses=num_poses,
        )
        self._landmarker = PoseLandmarker.create_from_options(options)
        self._last_ms = -1

    def detect(self, t: float, image_bgr: np.ndarray) -> list[Person]:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        # MediaPipe requires strictly increasing timestamps.
        timestamp_ms = max(int(t * 1000), self._last_ms + 1)
        self._last_ms = timestamp_ms
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        return [
            Person(
                np.array(
                    [[p.x, p.y, p.visibility if p.visibility is not None else 0.0] for p in pose],
                    dtype=np.float32,
                )
            )
            for pose in result.pose_landmarks
        ]

    def close(self) -> None:
        self._landmarker.close()
