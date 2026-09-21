# Claude Terminal Completion Alarm

You give Claude a task, walk away, and your speaker tells you when Claude is done
and waiting for you again. Press ENTER, give Claude the next task, walk away again.

No terminal scraping, no idle-timeout guessing. Claude Code itself tells the
watcher when it is finished.

---

## 1. What it does

```
[READY]   Waiting for Claude...
[WORKING] Claude is working... monitoring.

[DONE]    Claude finished (stop).
[ALARM]   Playing alarm.mp3
          Press ENTER to silence.
>
[ALARM]   Stopped.

[READY]   Waiting for Claude...
```

The loop repeats until you kill the watcher with Ctrl+C.

## 2. Requirements

- Windows 10/11 and Python 3.8+
- **No third-party packages.** MP3/WAV playback uses the Windows MCI interface
  through `ctypes`, which is part of the standard library.
- Claude Code (the alarm is triggered by its `Stop` hook).

## 3. Installation

Nothing to install. `requirements.txt` is intentionally empty.

Check Python is available in a **new** terminal:

```powershell
python --version
```

## 4. The alarm sound

Currently configured (already in place and tested):

```
sounds/Djo_-_End_Of_Beginning_(Hydr0.org).mp3
```

To swap it for something else, drop it into the `sounds` folder and change one line in
`config.json`:

```json
{ "alarm_file": "sounds/your-song.mp3" }
```

An absolute path works too (`"C:/Users/Arshith/Music/wake-up.mp3"`), as does `.wav`.
The file loops until you press ENTER, so a short clip is fine — but a full-length
song is fine as well, since ENTER cuts it off mid-play.

## 5. One-time setup: wire the hook into Claude

Run this once:

```powershell
cd D:\claude_watcher
python watcher.py --hook
```

It prints a ready-made JSON block with the correct absolute paths. Paste it into
`.claude/settings.json` **inside the project where you run Claude** (create the
file if it does not exist, or merge the `"hooks"` key into what is already there):

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "\"C:\...\python.exe\" \"D:\claude_watcher\notify.py\" stop" } ] }
    ]
  }
}
```

Because the hook lives in *that* project's settings, **only that Claude session
rings your alarm.** Your ssh / git / docker / RunPod terminals are never touched,
and neither are Claude sessions in other projects.

Restart Claude Code after editing the settings file.

Two optional extras are printed as well:

- `UserPromptSubmit` -> shows `[WORKING]` when you hand Claude a task (no sound).
- `Notification` -> also rings when Claude **pauses to ask you for permission**.
  Worth adding: otherwise Claude can sit waiting on a permission prompt while you
  are in another room.

## 6. How to start it

One terminal for the watcher:

```powershell
cd D:\claude_watcher
python watcher.py
```

Another terminal for Claude, as usual. That is it.

Useful flags:

| Command | What it does |
| --- | --- |
| `python watcher.py` | normal use |
| `python watcher.py --test` | fires the alarm immediately, to check your audio |
| `python watcher.py --hook` | prints the hook config to paste into Claude |
| `python watcher.py --alarm other.mp3` | use a different sound for this run only |

## 7. How to stop the alarm

Press **ENTER** in the watcher terminal. The watcher keeps running and goes
straight back to `[READY]`.

## 8. How to stop the watcher

**Ctrl+C** in the watcher terminal.

## 9. How completion detection works

Claude Code fires a `Stop` hook at the exact moment the main agent finishes its
turn and hands control back to you. That is the event, straight from Claude —
not a guess.

```
Claude finishes its turn
        |
        v
Claude Code runs the Stop hook
        |
        v
notify.py  --POST-->  http://127.0.0.1:8787/done?label=stop
        |
        v
watcher.py plays alarm.mp3 on a loop until you press ENTER
```

This is why long tool calls never cause a false alarm: Claude running tests for
six minutes, installing packages, or doing file operations produces **no** `Stop`
hook. The hook fires once per completed turn, full stop.

`notify.py` always exits 0 with a 3-second timeout, so a watcher that is closed,
crashed or not yet started can never disturb or slow down Claude.

## 10. Limitations

- **Claude Code only.** Detection depends on Claude Code's hook system. It will
  not detect anything in a plain `python`/`ssh` terminal, which is exactly the point.
- **Hook config is per-project.** Enable it in each project where you want the alarm.
- **Permission prompts** do not fire `Stop` — add the optional `Notification`
  hook from section 5 if you want those to ring too.
- **One watcher at a time.** Port 8787 is bound exclusively; a second watcher
  exits with a clear message instead of silently splitting the signals.
- **Anything arriving while the alarm rings is discarded**, so you get one alarm
  per acknowledgement rather than a backlog.
- Audio goes through the Windows MCI device. If a codec cannot be opened, the
  watcher falls back to terminal-bell beeps rather than dying — convert the file
  to `.wav` if that happens.

## 11. Later: Claude on RunPod, alarm on your laptop

The split is already in place — `notify.py` (where Claude runs) is separate from
`watcher.py` (where the speaker is). The current version is localhost-only. To go
remote:

1. Keep running `python watcher.py` on your Windows laptop.
2. Expose the watcher port to RunPod. Easiest and safest is an SSH reverse tunnel
   from the pod, which needs no firewall changes and no public port:

   ```bash
   ssh -R 8787:127.0.0.1:8787 you@your-laptop
   ```

   Then `127.0.0.1:8787` *inside the pod* is your laptop's watcher.
3. Copy `notify.py` and `config.json` onto the pod and add the same `Stop` hook
   to the pod project's `.claude/settings.json`, using the pod's `python3`.
4. If you instead expose the watcher directly over the network, set
   `"host": "0.0.0.0"` and a shared `"token"` in **both** `config.json` files so
   random traffic cannot ring your alarm.

`config.json` already has a `"url"` field for this: set it to e.g.
`"http://127.0.0.1:8787"` (tunnel) or `"http://your-laptop-ip:8787"` on the pod
side, and `notify.py` will use it. No code changes needed.

## Files

| File | Purpose |
| --- | --- |
| `watcher.py` | the watcher: listens, rings the alarm, waits for ENTER |
| `alarm.py` | looping sound playback (Windows MCI, POSIX fallback) |
| `notify.py` | tiny client that Claude's Stop hook runs |
| `config.json` | alarm file, loop on/off, host/port/token/url |
| `sounds/` | your alarm audio lives here |
