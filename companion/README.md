# Lullaby Companion (Reachy Mini)

A surgery companion for kids aged 4–8. Before surgery it greets the child, lets them name it, tells a story in a theme they pick that walks through their day, leads a breathing game, and promises to be there when they wake up. After surgery it stays silent: slow breathing movements plus the parent's recorded voice. When the child is alert, it tells chapter 2.

Every line is scripted (`lullaby/content.py`). No AI talks to the child. A nurse or parent drives it from a web panel.

## Run it

```bash
cd companion
uv sync
uv run lullaby                 # finds the robot (USB/localhost first, then reachy-mini.local)
uv run lullaby --host 192.168.1.42   # if the robot's name doesn't resolve, use its IP
uv run lullaby --preview       # no robot: voice plays on the laptop, motions are skipped
```

Open **http://127.0.0.1:8890**. The top bar shows whether the robot is connected. If it isn't, press **Reconnect robot** once the robot's daemon is running.

Needs macOS (`say` makes the voice) and `ffmpeg` (`brew install ffmpeg`) for parent recordings.

## Voice: ElevenLabs (optional)

By default the robot uses the built-in Mac voice, which works offline. For a warmer voice:

1. `cp .env.example .env`
2. Open `.env` and paste your key after `ELEVENLABS_API_KEY=`. Optionally set `ELEVENLABS_VOICE_ID` to a voice from the ElevenLabs Voice Library.
3. Restart the app. The terminal and the panel's top bar show which voice is active.

Each line is generated once and cached. If ElevenLabs is down or out of credits, that line falls back to the Mac voice, so the robot never goes silent.

**Privacy:** with ElevenLabs on, every line the robot says is sent to ElevenLabs, including the child's first name. Before using it with real patients, check with the hospital's privacy or compliance team. Parent recordings are never sent anywhere.

## Listening to the child (speech-to-text)

On "Ask the child for a nickname" and "Let the child pick a story", the laptop's microphone listens as soon as the robot finishes asking. It stops by itself when the child goes quiet, or you can tap the mic. The nickname box fills in, or the story is picked, and the nurse can correct either one.

It runs **offline** with Whisper (`base.en`, downloaded once to the Hugging Face cache). The child's voice never leaves the laptop, and each recording is deleted right after it's transcribed. Made-up names have no "right" spelling ("Sparklew" may come out as "Sparklue"), so check the box. For more accuracy, set `LULLABY_WHISPER=small.en` (slower, bigger download).

The browser asks for microphone permission the first time. Open the panel at http://127.0.0.1:8890 on the laptop next to the child.

## How a session goes

1. **Setup**: type the child's name. Show the picture cards and let the child tap a story.
2. **Parent messages**: the parent records 2–3 short messages. Recording only works in a browser on this laptop (http://127.0.0.1). On a tablet, upload a voice memo file instead.
3. **Before surgery**: press steps 1–8 in order. After step 2, type the name the child picks into "Robot's name", then press step 3.
4. **At the OR doors**: step 8 (the promise). The robot does not go in.
5. **Recovery**: press **Recovery quiet mode**, then play parent messages when it helps.
6. **Child is alert**: press **Story, chapter 2**. This ends quiet mode on its own.
7. **End session** deletes the recordings and clears the child's name.

**Stop** (top right) cuts off speech and movement at any time. Quick reactions and "Type a line" work whenever the robot isn't already talking.

## First robot test checklist

These are untested on real hardware. Check them first:
- [ ] Head pitch direction: the "sleepy" motion should look **down**. If it looks up, flip the pitch sign in `robot.py`.
- [ ] Antennas: "sleepy" should droop both antennas evenly. If they move oddly, check `sym()` in `robot.py`.
- [ ] Movement size: nothing should look jerky or scary up close. Shrink the numbers in `MOTIONS` if it does.
- [ ] Voice volume and speed on the robot speaker. Change speed with `LULLABY_RATE=150 uv run lullaby`.
- [ ] Speech lines up with motion, with no long gaps between lines. The first run of a story makes its audio, which is slower.
- [ ] Parent message plays on the robot, and the head stays still in recovery mode.
- [ ] Stop really stops both sound and motion.

## Files

- `lullaby/content.py`: every story, line and theme. Edit wording here.
- `lullaby/robot.py`: motions (keyframes) and robot sound.
- `lullaby/director.py`: runs one thing at a time, recovery mode, parent messages.
- `lullaby/server.py` and `lullaby/static/index.html`: the nurse panel.
- `uv run pytest`: tests the whole flow without a robot.
