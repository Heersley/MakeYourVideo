"""Episode voices accept (event, sample_rate, rng) and return mono or stereo float PCM."""
import hashlib
import math
import os
import tempfile
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

CHANNELS = 2


def as_stereo(sound, name):
    """Lay mono voices out as equal L = R; keep an authored stereo pair intact.

    A mono master is upmixed by FFmpeg at -3.01 dB (1/sqrt(2) per channel) when
    mix_bgm reads it as stereo, which silently drops a -14 dB master under the
    -16 dB floor. Writing real two-channel PCM keeps the mastered peak exact.
    """
    if sound.ndim == 2 and sound.shape[1] == 1:
        sound = sound[:, 0]
    if sound.ndim == 1:
        return np.repeat(sound[:, None], CHANNELS, axis=1)
    if sound.ndim == 2 and sound.shape[1] == CHANNELS:
        return sound
    raise ValueError(f"Voice {name} must return finite mono or stereo PCM")


def render_sfx(events, voices, total_frames, fps, profile, out_wav, seed=0, *, lowpass_hz=None):
    audio = profile["hard"]["audio"]
    rate = audio["sampleRate"]
    if type(total_frames) is not int or total_frames <= 0 or type(fps) is not int or fps <= 0:
        raise ValueError("Expected positive integer frame count and fps")

    def offset(frame):
        # Round half up using integers, including for non-integral samples per frame.
        return (2 * frame * rate + fps) // (2 * fps)

    track = np.zeros((offset(total_frames), CHANNELS), dtype=np.float64)
    rng = np.random.default_rng(seed)
    cues = []
    for event in events:
        frame, name = event["frame"], event["voice"]
        if type(frame) is not int or not 0 <= frame < total_frames or name not in voices:
            raise ValueError(f"Invalid event: {event}")
        sound = as_stereo(np.asarray(voices[name](event, rate, rng), dtype=np.float64), name)
        if not sound.size or not np.all(np.isfinite(sound)):
            raise ValueError(f"Voice {name} must return finite mono or stereo PCM")
        start = offset(frame)
        size = min(len(sound), len(track) - start)
        track[start:start + size] += sound[:size]
        cues.append({"frame": frame, "voice": name, "sample": start, "samples": size,
                     "channels": CHANNELS})
    if lowpass_hz is not None:
        sections = butter(2, lowpass_hz, fs=rate, output="sos")
        track = sosfilt(sections, track, axis=0)
    peak = np.abs(track).max(initial=0)
    if not cues or not math.isfinite(peak) or peak < 10 ** (-90 / 20):
        raise ValueError("Empty or near-silent SFX")
    lo, hi = audio["sfxPeak"]
    if not lo <= hi <= 0:
        raise ValueError("Invalid SFX peak range")
    # Normalize against the real two-channel peak so the loudest sample lands on
    # the profile midpoint (-14.0 dB for [-16, -12]) and survives any later read.
    pcm = np.rint(track * (32767 * 10 ** ((lo + hi) / 40) / peak)).astype("<i2")
    actual = 20 * math.log10(np.max(np.abs(pcm.astype(np.int32))) / 32768)
    if not lo <= actual <= hi:
        raise ValueError("Quantized peak outside profile")
    out = Path(out_wav)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=out.parent, delete=False) as tmp:
        path = Path(tmp.name)
    try:
        with wave.open(str(path), "wb") as wav:
            wav.setparams((CHANNELS, 2, rate, 0, "NONE", ""))
            wav.writeframes(pcm.tobytes())
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        os.replace(path, out)
    finally:
        path.unlink(missing_ok=True)
    return {"sha256": digest, "profile": profile["id"], "seed": seed, "sampleRate": rate,
            "samples": len(pcm), "channels": CHANNELS, "fps": fps, "peakDbfs": actual,
            "events": cues}
