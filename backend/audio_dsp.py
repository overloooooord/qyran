"""Real audio DSP: decoding, 16 kHz mono conversion, radio passband filter, SNR & waveform."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt


@dataclass
class AudioAnalysis:
    samples: np.ndarray  # float32 mono [-1, 1] at 16 kHz
    sample_rate: int
    duration_sec: float
    rms_db: float
    snr_db: float
    voice_activity_ratio: float
    waveform: list[float]  # 64 normalized bins [0..1]
    radio_filtered: bool = False


def decode_to_16k_mono(raw_bytes: bytes, suffix: str = ".webm") -> tuple[int, np.ndarray]:
    """Decode any browser/uploaded audio format into 16 kHz mono float32 via ffmpeg."""
    with tempfile.TemporaryDirectory() as td:
        in_path = Path(td) / f"input{suffix or '.bin'}"
        out_path = Path(td) / "out_16k.wav"
        in_path.write_bytes(raw_bytes)
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(in_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(out_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not out_path.exists():
            raise ValueError(f"Audio decode failed: {res.stderr.strip()[:200]}")
        sr, pcm = wavfile.read(out_path)
        samples = pcm.astype(np.float32) / 32768.0
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        return int(sr), samples


def load_wav_16k(path: Path) -> tuple[int, np.ndarray]:
    """Load a local WAV file into float32 mono at 16 kHz."""
    sr, pcm = wavfile.read(path)
    if pcm.dtype == np.int16:
        samples = pcm.astype(np.float32) / 32768.0
    elif pcm.dtype == np.int32:
        samples = pcm.astype(np.float32) / 2147483648.0
    else:
        samples = pcm.astype(np.float32)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if sr != 16000:
        return decode_to_16k_mono(path.read_bytes(), suffix=path.suffix)
    return int(sr), samples


def apply_radio_degradation(
    samples: np.ndarray,
    sr: int = 16000,
    noise_level: float = 0.025,
    seed: int = 42,
) -> np.ndarray:
    """Simulate real VHF/UHF 300-3400 Hz analog radio channel with FM limiter & static."""
    rng = np.random.default_rng(seed)
    sos = butter(4, [300, 3400], btype="bandpass", fs=sr, output="sos")
    sig = sosfilt(sos, samples.astype(np.float32))
    peak = float(np.max(np.abs(sig))) + 1e-6
    sig = sig / peak * 0.82
    sig = np.tanh(sig * 1.5) / np.tanh(1.5)
    noise = rng.normal(0.0, noise_level, size=sig.shape).astype(np.float32)
    noise = sosfilt(sos, noise)
    out = np.clip(sig + noise, -0.99, 0.99).astype(np.float32)
    return out


def analyze_audio(
    samples: np.ndarray,
    sr: int = 16000,
    radio_filtered: bool = False,
    n_bins: int = 64,
) -> AudioAnalysis:
    """Extract real signal telemetry: duration, RMS dB, estimated SNR dB, VAD ratio, waveform."""
    samples = np.asarray(samples, dtype=np.float32)
    n = len(samples)
    if n == 0:
        return AudioAnalysis(
            samples=samples,
            sample_rate=sr,
            duration_sec=0.0,
            rms_db=-60.0,
            snr_db=0.0,
            voice_activity_ratio=0.0,
            waveform=[0.0] * n_bins,
            radio_filtered=radio_filtered,
        )

    duration = n / float(sr)
    rms = float(np.sqrt(np.mean(samples**2)) + 1e-9)
    rms_db = round(20.0 * float(np.log10(rms)), 1)

    # Frame-based energy for SNR & voice activity estimation (30 ms frames)
    frame_len = max(1, int(sr * 0.03))
    n_frames = max(1, n // frame_len)
    framed = samples[: n_frames * frame_len].reshape(n_frames, frame_len)
    frame_rms = np.sqrt(np.mean(framed**2, axis=1) + 1e-10)
    noise_floor = float(np.percentile(frame_rms, 15)) + 1e-6
    speech_level = float(np.percentile(frame_rms, 90)) + 1e-6
    snr_db = round(float(np.clip(20.0 * np.log10(speech_level / noise_floor), 0.0, 45.0)), 1)

    vad_thresh = max(0.015, noise_floor * 2.2)
    vad_ratio = round(float(np.mean(frame_rms > vad_thresh)), 2)

    # 64-bin waveform envelope for canvas rendering
    chunks = np.array_split(np.abs(samples), n_bins)
    raw_env = [float(np.sqrt(np.mean(c**2))) if len(c) else 0.0 for c in chunks]
    max_env = max(raw_env) + 1e-6
    waveform = [round(v / max_env, 3) for v in raw_env]

    return AudioAnalysis(
        samples=samples,
        sample_rate=sr,
        duration_sec=round(duration, 2),
        rms_db=rms_db,
        snr_db=snr_db,
        voice_activity_ratio=vad_ratio,
        waveform=waveform,
        radio_filtered=radio_filtered,
    )
