import argparse
import sys
from pathlib import Path

from preop.config import Config, load_config
from preop.features.audio import VocalWindow, make_smile_analyzer
from preop.pipeline import Pipeline, Tick
from preop.sources.mic import MicSource
from preop.sources.pulse import SimulatedPulseSource
from preop.sources.video_file import AudioFileSource, VideoFileSource
from preop.sources.webcam import SourceUnavailable, WebcamSource


def _fmt(value: float | None, spec: str = ".2f") -> str:
    return "--" if value is None else format(value, spec)


def format_tick(tick: Tick) -> str:
    score = _fmt(tick.score.value, "5.1f") if tick.score.value is not None else "   --"
    body, vocal = tick.body, tick.vocal
    return (
        f"PLACEHOLDER {score}  conf {tick.score.confidence:.2f} | "
        f"people {body.people if body else '--'}  "
        f"activity {_fmt(body.activity if body else None)}  "
        f"parent_dist {_fmt(body.parent_distance if body else None)} | "
        f"dBFS {_fmt(vocal.dbfs if vocal else None, '.0f')}  "
        f"pitch {_fmt(vocal.pitch_semitones if vocal else None, '.1f')} | "
        f"sim_hr {_fmt(tick.pulse.bpm if tick.pulse else None, '.0f')}"
    )


def build_pipeline(config: Config) -> Pipeline:
    video = detect = None
    if config.video.source != "off":
        from preop.features.pose import PoseExtractor

        if config.video.source == "webcam":
            video = WebcamSource(config.video.camera_index)
            video.open()  # On the main thread, so macOS can show its permission prompt.
        else:
            video = VideoFileSource(Path(config.video.path))
        detect = PoseExtractor(num_poses=config.video.num_poses).detect

    audio = window = None
    if config.audio.source != "off":
        if config.audio.source == "mic":
            audio = MicSource(config.audio.device_hint)
        else:
            audio = AudioFileSource(Path(config.audio.path))
        if config.audio.opensmile:
            analyzer = make_smile_analyzer()
        else:
            from preop.features.audio import F0_COLUMN, HNR_COLUMN, LOUDNESS_COLUMN

            def analyzer(samples, rate):
                return {F0_COLUMN: 0.0, LOUDNESS_COLUMN: 0.0, HNR_COLUMN: 0.0}

        window = VocalWindow(analyzer)

    pulse = SimulatedPulseSource() if config.pulse.source == "simulated" else None
    return Pipeline(video, audio, pulse, detect, window)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="preop", description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="YAML config (default: built-in)")
    parser.add_argument("--video-file", type=Path, help="Replay this file instead of live capture")
    parser.add_argument("--duration", type=float, default=None, help="Stop after this many seconds")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.video_file:
        config.video.source, config.video.path = "file", str(args.video_file)
        config.audio.source, config.audio.path = "file", str(args.video_file)

    print("Placeholder output only: this is not a mYPAS or distress estimate. Ctrl-C to stop.")
    try:
        pipeline = build_pipeline(config)
        pipeline.run(lambda tick: print(format_tick(tick), flush=True), args.duration)
    except KeyboardInterrupt:
        pass
    except SourceUnavailable as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(pipeline.latency_summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
