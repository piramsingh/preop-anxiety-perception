# Dr. Juni Remote (iOS)

A native iPhone/iPad remote for the Lullaby companion, for presenting. It controls the same
app as the nurse panel on the Mac, so the Mac still runs the robot, the voice and the sounds.

## Run it

1. On the Mac: `cd companion && uv run lullaby --lan` (add `--host <robot-ip>` if needed).
   `--lan` lets the phone reach it. Only use it on a network you trust: the panel has no login.
2. Open `LullabyRemote.xcodeproj` (regenerate with `xcodegen generate` after editing `project.yml`)
   and run on your iPhone. The phone must be on the same Wi-Fi as the Mac.
3. The app connects to `http://Pirams-Macbook-Pro.local:8890` by default. Change it under
   **… → Mac and robot**. Allow **Local Network** access when iOS asks.

## What's on the screen

- **Now** card: robot and voice status, what Dr. Juni is doing, the line being spoken, what the
  robot's mic heard, and the child's stickers so far.
- **Journey**: the visit as a path of milestones (Hello, Nickname, Story, Part 1, Breathing, Mask,
  Goodbye, Part 2), grouped by phase. Each one finished earns a sticker; the last one earns the
  brave badge. Tap play to run a milestone, or tap its name for its parts and script.
- Bottom dock, always reachable: the next action (**Start intro**, then the next step), and
  **Quiet** (recovery mode), **Stop**, **Say**. Stop is also at the bottom of every sheet.
- **Say**: type a line, quick lines, ask-again lines and parent messages (record them in the Mac panel).
- **This visit** (card icon, top right): child's name, the robot's nickname and the story pictures.
  The pictures also appear on the home screen when Dr. Juni asks for a story.
- **… menu**: start the intro again, sticker book, reconnect robot, Mac address, and **End visit**,
  which clears the child's details and deletes the parent recordings after a confirmation.
- iPad: the journey on the left; the visit, story pictures and every line on the right.

The screen stays awake while the app is open.

### Debug launch arguments

Debug builds only. Nothing here reaches the Mac or the robot.

- `-LullabyMock fresh|ready|intro|listening|talking|pick|heard|midway|princess|heroes|celebrate|parent|brave|done|offline`
  shows a canned state.
- `-LullabyShow say|visit|settings|stickers|end|<milestone id>` opens that sheet at launch.

## Listening (robot's microphone)

After **Nickname** or **Pick a story** (and the "Ask again" lines), the robot's own mic listens
as soon as it finishes asking. It stops by itself once the child goes quiet. Speech is understood
on the Mac, offline. The nickname is filled in, or the story picked, and the top card shows what it
heard. The mic buttons next to the nickname and above the stories listen again. The Mac reaches the
robot's mic over SSH (`~/.ssh/id_ed25519_reachy`, user `pollen`).
