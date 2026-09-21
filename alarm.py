"""Alarm playback.

Windows: uses the built-in MCI interface via ctypes -> plays .mp3/.wav with no
third-party packages at all.
POSIX (for a future Linux/Mac watcher): shells out to whichever common player
is installed (ffplay / mpg123 / mpv / afplay / paplay / aplay).
If nothing works we fall back to terminal bell beeps so the alarm still happens.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time


class AlarmError(Exception):
    """Raised when the alarm file is missing or cannot be opened."""


_POSIX_PLAYERS = [
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ("mpg123", ["-q"]),
    ("mpv", ["--no-video", "--really-quiet"]),
    ("afplay", []),
    ("paplay", []),
    ("aplay", ["-q"]),
]


class Alarm:
    """Plays a sound file in a background thread until stop() is called."""

    def __init__(self, path: str, loop: bool = True):
        self.path = os.path.abspath(path)
        self.loop = loop
        self.backend = "none"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None

    # ---------------------------------------------------------------- public

    def start(self) -> None:
        if not os.path.isfile(self.path):
            raise AlarmError("alarm file not found: %s" % self.path)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None

    # --------------------------------------------------------------- private

    def _run(self) -> None:
        try:
            if os.name == "nt":
                self.backend = "windows-mci"
                self._run_windows()
            else:
                self._run_posix()
        except Exception as exc:  # never let the watcher die because of audio
            print("[ALARM] playback failed (%s) - falling back to beeps" % exc)
            self._run_beep()

    # -- Windows MCI ------------------------------------------------------

    @staticmethod
    def _mci(command: str):
        buf = ctypes.create_unicode_buffer(256)
        err = ctypes.windll.winmm.mciSendStringW(command, buf, 255, 0)
        return err, buf.value

    def _run_windows(self) -> None:
        alias = "cw_alarm_%d" % (int(time.time() * 1000) % 1000000)
        opened = False
        for opener in (
            'open "%s" alias %s' % (self.path, alias),
            'open "%s" type mpegvideo alias %s' % (self.path, alias),
            'open "%s" type waveaudio alias %s' % (self.path, alias),
        ):
            err, _ = self._mci(opener)
            if err == 0:
                opened = True
                break
        if not opened:
            raise AlarmError("Windows could not open %s" % self.path)

        try:
            self._mci("seek %s to start" % alias)
            self._mci("play %s" % alias)
            # Poll instead of relying on MCI's "repeat" flag, which is not
            # supported by every codec. This loops any format reliably.
            while not self._stop.wait(0.3):
                err, mode = self._mci("status %s mode" % alias)
                if err:
                    break
                if mode.strip() != "playing":
                    if not self.loop:
                        break
                    self._mci("seek %s to start" % alias)
                    self._mci("play %s" % alias)
        finally:
            self._mci("stop %s" % alias)
            self._mci("close %s" % alias)

    # -- POSIX ------------------------------------------------------------

    def _run_posix(self) -> None:
        player = None
        for name, args in _POSIX_PLAYERS:
            if shutil.which(name):
                player = [name] + args + [self.path]
                self.backend = name
                break
        if player is None:
            raise AlarmError("no audio player found (install ffmpeg or mpg123)")

        while not self._stop.is_set():
            self._proc = subprocess.Popen(
                player, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            while self._proc.poll() is None:
                if self._stop.wait(0.2):
                    break
            if not self.loop:
                break

    # -- last resort ------------------------------------------------------

    def _run_beep(self) -> None:
        self.backend = "terminal-bell"
        while not self._stop.is_set():
            sys.stdout.write("\a")
            sys.stdout.flush()
            if self._stop.wait(1.0):
                break
            if not self.loop:
                break
