# Funk Check — Fake FLAC Detector for Linux

A native Ubuntu tool that tells you a music file's real format and whether a
"lossless" file (FLAC/ALAC/WAV) is genuine or secretly an upscaled transcode
from a lossy source (MP3/AAC). Same idea as the Windows app "Fakin' The Funk?",
but no Wine/PlayOnLinux needed.

## How it works

Lossy encoders (MP3, AAC) throw away high frequencies with a sharp lowpass
filter. Funk Check decodes the audio, averages its frequency spectrum, and
finds the cutoff frequency:

- Genuine CD-quality lossless has energy up to ~20–22 kHz with a natural rolloff.
- A FLAC faked from a 128 kbps MP3 has a hard wall at ~16 kHz.
- ~192 kbps → ~19 kHz, ~320 kbps → ~20.5 kHz.

### Hi-res files (88.2 / 96 / 176.4 / 192 kHz)

"Hi-res" audio is faked constantly. A real 96 kHz file has content extending
well above 24 kHz. Fakes come in two flavours, both of which Funk Check catches:

- **Upsampled from a 44.1 kHz CD** → hard brick wall at ~22 kHz. Bigger sample
  rate, but no extra detail. (Still lossless CD quality, just not true hi-res.)
- **Upsampled from an MP3/AAC** → wall at ~16–20 kHz. The worst case: fake
  hi-res *and* lossy underneath.

On the spectrum graph, a genuine 96 kHz file fills the space up to ~40+ kHz;
a fake shows empty space above a hard cliff.

A steep cliff well below where it should be = a transcode/upsample. The graph
lets you confirm it yourself.

**Note:** it's an indicator, not absolute proof. Some genuine recordings (old
masters, sparse acoustic tracks) naturally lack high-frequency content — that's
why the tool distinguishes a *sharp* artificial cliff from a *gentle* natural
rolloff, and labels borderline cases SUSPECT rather than FAKE.

## Install

```bash
chmod +x install.sh
./install.sh
```

This installs `ffmpeg`, `python3-tk`, `numpy`, `matplotlib`, adds a `funkcheck`
command, and puts "Funk Check" in your app menu.

## Usage

**GUI** (with spectrum graphs):
```bash
funkcheck --gui
```
Then click "Add files" or "Add folder", and click any row to see its spectrum.

**CLI** (fast batch scan of a whole library):
```bash
funkcheck ~/Music
funkcheck ~/Music/album/track.flac
```

## Verdicts

| Tag      | Meaning                                                        |
|----------|---------------------------------------------------------------|
| GENUINE  | Full frequency range — real lossless.                         |
| FAKE     | Hard lowpass cliff — transcoded from a lossy source.          |
| SUSPECT  | Borderline / inconclusive — check the spectrum yourself.      |
| LOSSY    | Honestly-labeled lossy file (MP3/AAC/etc.).                   |

## Requirements

- Ubuntu 24.04 (or any distro with ffmpeg + Python 3)
- ffmpeg, python3-tk, numpy, matplotlib (installed by `install.sh`)

## Manual run (without installing)

```bash
sudo apt install ffmpeg python3-tk
pip install --break-system-packages numpy matplotlib
python3 funkcheck.py --gui
```
please show support and comment for any problems
