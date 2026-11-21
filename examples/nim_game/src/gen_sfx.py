"""Write deterministic 48 kHz stereo resonance for the 25 timed cues."""
import json
from pathlib import Path
import wave

import numpy as np
from scipy.signal import butter, sosfilt

HERE = Path(__file__).resolve().parent
FPS_AUDIO = 48_000

# Frequency, decay seconds, attack seconds, relative gain, room position.
VOICES = {
    "low_swell": (55, 1.76, .21, .63, -.10),
    "brass_chime": (392, 1.45, .024, .68, .06),
    "caliper_click": (294, .32, .008, .55, .13),
    "beacon_glow": (196, 1.84, .14, .57, 0.0),
    "stone_pick": (238, .48, .009, .68, .16),
    "stone_pick_low": (146.8, .51, .013, .65, -.16),
    "win_bell": (330, 1.40, .039, 1.0, 0.0),
    "scan_sweep": (130.8, 1.16, .16, .46, .12),
    "split_snap": (245, .82, .016, .72, .08),
    "xor_pulse": (294, 1.07, .033, .73, 0.0),
    "lock_zero": (174.6, 1.43, .044, .82, .08),
    "hollow_tick": (117.5, .67, .022, .61, 0.0),
    "snap_break": (187, .62, .011, .69, -.16),
    "cursor_ping": (438, .99, .028, .63, .12),
    "scale_drop": (102, 1.86, .045, .85, -.12),
    "gear_lock": (166, 1.61, .06, .77, .10),
    "page_shimmer": (277, 1.67, .24, .44, -.13),
    "title_resolve": (164.8, 2.43, .17, .68, 0.0),
}
CONTACTS = {"caliper_click", "stone_pick", "stone_pick_low", "snap_break", "scale_drop", "gear_lock"}
CHIMES = {"brass_chime", "beacon_glow", "win_bell", "xor_pulse", "cursor_ping", "title_resolve"}


def synthesize(kind, noise):
    hz, seconds, attack, gain, pan = VOICES[kind]
    t = np.arange(round(seconds * FPS_AUDIO)) / FPS_AUDIO
    phase = 2 * np.pi * hz * t
    envelope = (1 - np.exp(-(t / attack) ** 2)) * np.clip((seconds - t) / .10, 0, 1) ** 2
    if kind in CHIMES:
        tone = (
            np.sin(phase) * np.exp(-4.0 * t / seconds)
            + .34 * np.sin(phase * 1.5) * np.exp(-6.6 * t / seconds)
            + .16 * np.sin(phase * 2.01) * np.exp(-8.0 * t / seconds)
        )
    else:
        tone = (
            np.sin(phase) * np.exp(-4.5 * t / seconds)
            + .30 * np.sin(phase * 2.68) * np.exp(-9 * t / seconds)
            + .12 * np.sin(phase * 4.17) * np.exp(-14 * t / seconds)
        )
    if kind in CONTACTS:
        band = butter(2, [460, 1950], btype="bandpass", fs=FPS_AUDIO, output="sos")
        texture = sosfilt(band, noise.standard_normal(len(t)))
        tone += .13 * texture * np.exp(-33 * t / seconds)
    return (tone * envelope * gain)[:, None] * np.array([1 - pan, 1 + pan])


def main():
    score = json.loads((HERE.parent / "beats.json").read_text("utf-8"))
    cues = score["effects"]
    assert len(cues) == 25 and {e["type"] for e in cues} == set(VOICES)
    generator = np.random.default_rng(1901)
    mix = np.zeros((round(score["totalSec"] * FPS_AUDIO), 2), dtype=np.float32)
    for event in cues:
        start = round(event["timeSec"] * FPS_AUDIO)
        signal = synthesize(event["type"], generator)
        mix[start:start + len(signal)] += signal
    lowpass = butter(4, 3400, fs=FPS_AUDIO, output="sos")
    mix = sosfilt(lowpass, mix, axis=0)
    mix *= 10 ** (-13.6 / 20) / np.max(np.abs(mix))
    with wave.open(str(HERE / "sfx_mix.wav"), "wb") as audio:
        audio.setparams((2, 2, FPS_AUDIO, len(mix), "NONE", "not compressed"))
        audio.writeframes(np.rint(mix * 32767).astype("<i2").tobytes())
    print(f"{len(cues)} cues, {len(mix)/FPS_AUDIO:.3f}s, stereo {FPS_AUDIO} Hz, -13.6 dBFS")


if __name__ == "__main__":
    main()
