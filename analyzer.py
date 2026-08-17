"""
Core audio authenticity analysis engine.
Detects whether a 'lossless' file is genuine or a transcode from a lossy source
by measuring the effective frequency cutoff (lossy encoders apply a lowpass).
"""
import json
import subprocess
import numpy as np

LOSSLESS_CODECS = {"flac", "alac", "wav", "pcm_s16le", "pcm_s24le", "pcm_s32le",
                   "ape", "wavpack", "tak", "tta", "aiff", "pcm_f32le"}
LOSSY_CODECS = {"mp3", "aac", "vorbis", "opus", "wmav1", "wmav2", "ac3", "eac3"}


def probe(path):
    """Return metadata dict via ffprobe."""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", path]
    out = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(out.stdout) if out.stdout.strip() else {}
    astream = None
    for s in data.get("streams", []):
        if s.get("codec_type") == "audio":
            astream = s
            break
    fmt = data.get("format", {})
    if astream is None:
        return None
    codec = astream.get("codec_name", "?")
    sr = int(astream.get("sample_rate", 0) or 0)
    ch = int(astream.get("channels", 0) or 0)
    bits = astream.get("bits_per_raw_sample") or astream.get("bits_per_sample")
    try:
        bits = int(bits)
    except (TypeError, ValueError):
        bits = None
    bitrate = fmt.get("bit_rate") or astream.get("bit_rate")
    try:
        bitrate = int(bitrate)
    except (TypeError, ValueError):
        bitrate = None
    duration = fmt.get("duration") or astream.get("duration")
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = None
    return {
        "codec": codec, "sample_rate": sr, "channels": ch,
        "bits": bits, "bitrate": bitrate, "duration": duration,
        "container": fmt.get("format_name", "?"),
    }


def decode_mono(path, sr, max_seconds=60, start_frac=0.15):
    """Decode a central segment to mono float32 via ffmpeg."""
    if not sr:
        sr = 44100
    ss = 0.0
    meta = probe(path)
    if meta and meta.get("duration"):
        dur = meta["duration"]
        ss = max(0.0, dur * start_frac)
        if dur - ss < 5:
            ss = 0.0
    cmd = ["ffmpeg", "-v", "quiet", "-ss", str(ss), "-t", str(max_seconds),
           "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True)
    samples = np.frombuffer(out.stdout, dtype=np.float32)
    return samples, sr


def average_spectrum(samples, sr, nfft=16384):
    """Welch-style averaged power spectrum in dB, normalized so peak = 0 dB."""
    if len(samples) < nfft:
        nfft = 1 << int(np.floor(np.log2(max(len(samples), 256))))
    win = np.hanning(nfft)
    hop = nfft // 2
    n_frames = max(1, (len(samples) - nfft) // hop + 1)
    n_frames = min(n_frames, 400)  # cap for speed
    acc = np.zeros(nfft // 2 + 1)
    count = 0
    for i in range(n_frames):
        start = i * hop
        frame = samples[start:start + nfft]
        if len(frame) < nfft:
            break
        spec = np.fft.rfft(frame * win)
        acc += np.abs(spec) ** 2
        count += 1
    if count == 0:
        return None, None
    psd = acc / count
    freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
    psd_db = 10 * np.log10(psd + 1e-12)
    psd_db -= psd_db.max()
    return freqs, psd_db


def _smooth(x, w=15):
    if w < 2:
        return x
    kernel = np.ones(w)
    # normalize by actual overlap so edges aren't inflated by implicit zeros
    num = np.convolve(x, kernel, mode="same")
    den = np.convolve(np.ones_like(x), kernel, mode="same")
    return num / den


def detect_cutoff(freqs, psd_db):
    """Find effective frequency cutoff and the sharpness of the rolloff.

    Robust to resampler imaging artifacts: upsampling can leave a small,
    isolated island of energy above the true cliff (e.g. 24-25 kHz on a file
    upsampled to 96 kHz). We identify contiguous above-threshold regions and
    take the top of the *main* low-frequency body, discarding small isolated
    islands separated from it by a real gap.
    """
    sm = _smooth(psd_db, 15)
    band = (freqs >= 1000) & (freqs <= 6000)
    if not band.any():
        band = freqs >= 0
    ref = np.median(sm[band])
    thresh = ref - 45.0  # dB relative to musical band

    above = sm >= thresh
    if not above.any():
        return 0.0, 0.0, ref

    # Build contiguous above-threshold regions as (start_idx, end_idx).
    idxs = np.where(above)[0]
    regions = []
    start = prev = idxs[0]
    for i in idxs[1:]:
        if i != prev + 1:
            regions.append((start, prev))
            start = i
        prev = i
    regions.append((start, prev))

    # The main body is the region containing the low-frequency musical energy
    # (it starts at/near DC). Its top edge is the true cutoff. Any region that
    # sits above a gap and is much smaller than the main body is treated as an
    # artifact and ignored.
    main = regions[0]  # regions are in ascending frequency; first contains DC
    main_width = main[1] - main[0]
    cutoff_idx = main[1]
    for (s0, e0) in regions[1:]:
        width = e0 - s0
        gap_hz = freqs[s0] - freqs[cutoff_idx]
        # extend the cutoff only if this region is contiguous-ish (small gap)
        # or comparably large (a genuine continuation, not an island)
        if gap_hz < 800 or width > 0.5 * main_width:
            cutoff_idx = e0
    cutoff = freqs[cutoff_idx]

    # sharpness: dB drop in the ~800 Hz just above the cutoff. A tight window
    # avoids a distant artifact island (further up) averaging the cliff away.
    hi_band = (freqs > cutoff) & (freqs <= cutoff + 800)
    if hi_band.any():
        above_cut = np.median(sm[hi_band])
        sharpness = sm[cutoff_idx] - above_cut
    else:
        sharpness = 0.0
    return float(cutoff), float(sharpness), float(ref)


def verdict(meta, cutoff, sharpness, sr):
    """Produce a human verdict + confidence label."""
    codec = (meta or {}).get("codec", "?")
    nyq = sr / 2.0 if sr else 22050.0
    sharp = sharpness > 22  # steep artificial cliff

    if codec in LOSSY_CODECS:
        return ("LOSSY", f"Lossy format ({codec.upper()}) — as labeled, not lossless.")

    # approximate lossy source from cutoff
    def guess_src(c):
        if c < 16500:
            return "~128 kbps MP3 / low"
        if c < 18500:
            return "~160-192 kbps MP3"
        if c < 20200:
            return "~256 kbps MP3 / AAC"
        return "~320 kbps MP3"

    # ---- HI-RES branch: 88.2 / 96 / 176.4 / 192 kHz ----
    # For these, the question isn't "does it reach Nyquist" (real hi-res often
    # rolls off naturally) but "does it exceed what a 44.1/48 kHz source could
    # hold" — a brick wall at 22.05 or 24 kHz betrays an upsample.
    if sr > 50000:
        if cutoff < 20500 and sharp:
            return ("FAKE", f"Fake hi-res + lossy — hard cutoff ~{cutoff/1000:.1f} kHz. "
                    f"Upsampled from {guess_src(cutoff)}, then wrapped as {sr/1000:.0f} kHz.")
        if 20800 <= cutoff <= 23200 and sharp:
            return ("FAKE", f"Fake hi-res — brick wall at ~{cutoff/1000:.1f} kHz. "
                    f"Upsampled from a 44.1 kHz (CD) source; not true {sr/1000:.0f} kHz "
                    f"(may still be lossless CD quality).")
        if 23200 < cutoff <= 25200 and sharp:
            return ("FAKE", f"Fake hi-res — cutoff ~{cutoff/1000:.1f} kHz. "
                    f"Upsampled from a 48 kHz source; not true {sr/1000:.0f} kHz.")
        if cutoff >= 28000:
            return ("GENUINE", f"Genuine hi-res — real content up to ~{cutoff/1000:.1f} kHz.")
        return ("SUSPECT", f"Inconclusive hi-res — cutoff ~{cutoff/1000:.1f} kHz. "
                f"Could be a band-limited genuine master or an upsample — check the spectrum.")

    # ---- Standard 44.1 / 48 kHz branch ----
    frac = cutoff / nyq if nyq else 0

    if frac >= 0.955:  # ~21.05 kHz+ at 44.1
        return ("GENUINE", f"Genuine lossless — full frequency range (cutoff ~{cutoff/1000:.1f} kHz).")
    if frac >= 0.915 and not sharp:  # ~20.2 kHz, gentle
        return ("GENUINE", f"Likely genuine — high cutoff ~{cutoff/1000:.1f} kHz with natural rolloff.")
    if frac >= 0.915 and sharp:
        return ("SUSPECT", f"Suspicious — sharp cutoff ~{cutoff/1000:.1f} kHz. Possible {guess_src(cutoff)} transcode.")
    if sharp:
        return ("FAKE", f"Likely FAKE — hard lowpass at ~{cutoff/1000:.1f} kHz. Transcoded from {guess_src(cutoff)}.")
    return ("SUSPECT", f"Inconclusive — cutoff ~{cutoff/1000:.1f} kHz, soft rolloff. Could be a quiet/old master or lossy source.")


def analyze(path):
    """Full pipeline for one file. Returns a result dict."""
    meta = probe(path)
    if meta is None:
        return {"path": path, "error": "No audio stream / unreadable"}
    sr = meta["sample_rate"] or 44100
    samples, sr = decode_mono(path, sr)
    if samples is None or len(samples) < 4096:
        return {"path": path, "meta": meta, "error": "Could not decode audio"}
    freqs, psd_db = average_spectrum(samples, sr)
    if freqs is None:
        return {"path": path, "meta": meta, "error": "Analysis failed"}
    cutoff, sharpness, ref = detect_cutoff(freqs, psd_db)
    tag, msg = verdict(meta, cutoff, sharpness, sr)
    return {
        "path": path, "meta": meta, "cutoff": cutoff,
        "sharpness": sharpness, "tag": tag, "message": msg,
        "freqs": freqs, "psd_db": psd_db, "sr": sr,
    }
