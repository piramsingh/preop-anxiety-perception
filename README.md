# Pre-op anxiety perception

A software-only perception module that estimates pre-operative distress in children aged 5–12. It
outputs one continuous score on the mYPAS range (23.33–100), built from the five items of the
modified Yale Preoperative Anxiety Scale (mYPAS): activity, vocalization, emotional expressivity,
state of arousal, and use of parents. It does not classify discrete emotions. The score is relative
to each child's own early baseline, and everything runs locally.

**Status: M2 in progress.** The score is rules-based and its thresholds are starting guesses. It has
not been compared with human ratings, so it is not a validated mYPAS measurement. Research
prototype, not a medical device. No patient data.

## Run it

Requires macOS on Apple Silicon, [uv](https://docs.astral.sh/uv/) and `ffmpeg`.

```sh
uv sync
uv run preop                         # Mac camera and mic, opens a live window (Q to close)
uv run preop --no-preview            # terminal output only
uv run preop --duration 30           # stop after 30 seconds
uv run preop --video-file clip.mp4   # replay a recording in real time
uv run preop --config config/default.yaml
```

The first run downloads the pose model to `models/` and macOS asks for camera and microphone access.
After that, inference is entirely local. Nothing is saved to disk.

Each line shows the score, its confidence and the five item ratings (`act voc exp aro par`), then
people, `activity` (body lengths per second), `parent_dist` (body lengths), loudness, pitch and
simulated heart rate. `--` means that signal is missing. Simulated heart rate is display-only and
never affects the score.

## How the score works

1. **Calibration.** The first 60 s (`score.baseline_s`) after someone appears set that person's
   reference levels. No score is shown yet. The person should be calm and should talk a little, so
   that their ordinary speaking level is known. `UPSET-AT-BASELINE` marks a session where they
   already looked upset, because scoring against an upset baseline reads low.
2. **Signals to z-scores.** Movement, voice and action units are compared with that baseline using
   the median and MAD, with a minimum spread for each signal.
3. **Items.** `mypas/items.py` rates each item on its own scale, as a continuous value.
4. **Fusion.** The published formula: `(activity/4 + vocalization/6 + expressivity/4 + arousal/4 +
   parents/4) / 5 x 100`. If an item can't be observed, the observed items take over its share of
   the range, and confidence drops. Ratings rise quickly and fall slowly.

A calm person with a neutral face scores about 28, because a human rater would rate a neutral face 2
of 4.

### Known limits

- **A still, silent, frightened child can score low.** Withdrawal, gaze and thumb-sucking are not
  observed. Going silent after a talkative baseline is the only signal for this.
- **The mic hears everyone,** so a parent's or nurse's voice counts as the child's.
- **Crying is approximated** by loudness and pitch until the detector in #5 exists.
- **Second-person signals can swap people** (#6), so the parent item has low confidence, and the
  face may belong to the parent when two people are in view.

## Dashboard

A local web page for testing: the live score, the chart over time, the five items, what the system can
currently see and hear, and the video with tracked body points.

```sh
uv run preop-dashboard                         # opens http://127.0.0.1:8765
uv run preop-dashboard --video-file clip.mp4   # fills in this video on the start screen
```

It only listens on this computer, refuses requests from other websites, loads nothing from the
internet, and saves nothing. It is for the adult running the session, so the screen should face away
from the child, who never sees the score. The dashed line at 30 is a commonly used mYPAS cut-off,
shown for orientation only.

## Facial action units (optional)

Facial analysis needs OpenFace, installed separately because its license doesn't allow copying it
into this repo. Without it, the pipeline prints a notice and runs on the other signals.

```sh
brew install cmake openblas tbb boost dlib opencv@4 wget
git clone https://github.com/TadasBaltrusaitis/OpenFace.git ~/DEV/OpenFace
cd ~/DEV/OpenFace && bash download_models.sh
OpenBLAS_HOME=$(brew --prefix openblas) cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DOpenCV_DIR=$(brew --prefix opencv@4)/lib/cmake/opencv4 \
  -DCMAKE_PREFIX_PATH="$(brew --prefix dlib);$(brew --prefix tbb);$(brew --prefix boost)"
cmake --build build -j8
cp lib/local/LandmarkDetector/model/patch_experts/*.dat build/bin/model/patch_experts/
cd - && ./scripts/build_openface_bridge.sh
```

`download_models.sh` can save Dropbox error pages without failing. The four `cen_patches_*.dat` files
should be 60.6, 60.6, 154 and 154 MB. If one is about 200 KB, download it again with `?dl=1` added to
its URL.

## Layout

```
src/preop/sources/    webcam, mic, video-file replay, simulated pulse-ox
src/preop/features/   pose -> activity + parent proximity; face -> action units; audio -> vocal features
native/               local bridge to OpenFace
src/preop/dashboard/  local web dashboard
src/preop/mypas/      one function per mYPAS item
src/preop/score/      baseline calibration and fusion into the score
src/preop/pipeline.py one thread per source, 1 Hz score tick
config/               input sources and modules, no code changes needed
```

To add an input such as a robot, implement the small `Source` protocol in `sources/__init__.py`.

## Stack

| Part | Tool | License |
|---|---|---|
| Pose | MediaPipe Pose | Apache-2.0 |
| Audio features | openSMILE (`opensmile`) | audEERING Research License, no commercial products |
| Facial action units | OpenFace 2 | CMU, noncommercial research by academic or non-profit users |

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
