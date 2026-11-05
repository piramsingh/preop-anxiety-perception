# Pre-op anxiety perception

A software-only perception module that estimates pre-operative distress in children aged 5–12. It
outputs one continuous 0–100 score built from the five items of the modified Yale Preoperative
Anxiety Scale (mYPAS): activity, vocalization, emotional expressivity, state of arousal, and use of
parents. It does not classify discrete emotions. The score is relative to each child's own early
baseline, and everything runs locally.

**Status: M1, pipeline skeleton.** The printed score is a placeholder that proves the pipeline runs.
It is not a mYPAS or distress estimate and has not been validated. Research prototype, not a medical
device. No patient data.

## Run it

Requires macOS on Apple Silicon, [uv](https://docs.astral.sh/uv/) and `ffmpeg`.

```sh
uv sync
uv run preop                         # Mac camera and mic, Ctrl-C to stop
uv run preop --duration 30           # stop after 30 seconds
uv run preop --video-file clip.mp4   # replay a recording in real time
uv run preop --config config/default.yaml
```

The first run downloads the pose model to `models/` and macOS asks for camera and microphone access.
After that, inference is entirely local. Nothing is saved to disk.

Each line shows the placeholder score, its confidence, then people, `activity` (body lengths per
second), `parent_dist` (body lengths), loudness, pitch and simulated heart rate. `--` means that
signal is missing. Simulated heart rate is display-only and never affects the score.

## Layout

```
src/preop/sources/    webcam, mic, video-file replay, simulated pulse-ox
src/preop/features/   pose -> activity + parent proximity; audio -> vocal features
src/preop/score/      M1 placeholder
src/preop/pipeline.py one thread per source, 1 Hz score tick
config/               input sources and modules, no code changes needed
```

To add an input such as a robot, implement the small `Source` protocol in `sources/__init__.py`.

## Stack

| Part | Tool | License |
|---|---|---|
| Pose | MediaPipe Pose | Apache-2.0 |
| Audio features | openSMILE (`opensmile`) | audEERING Research License, no commercial products |
| Facial action units (M2) | OpenFace 2 | CMU, noncommercial research by academic or non-profit users |

## Licensing

The code in this repo is MIT. The openSMILE and OpenFace licenses are more restrictive and apply to
those tools regardless, so this system as a whole is for noncommercial research. OpenFace must not
be vendored into this repo.

## Privacy

Never commit audio, video, frames or recordings. `.gitignore` blocks them and CI fails if any are
tracked (`scripts/check_no_media.sh`). Perception uses no cloud APIs. Tests use generated data only.

## Develop

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
