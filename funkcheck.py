#!/usr/bin/env python3
"""
Funk Check — detect fake lossless audio on Linux.

Tells you the real format of a music file and whether a "lossless" file
(FLAC/ALAC/WAV) is genuine or a transcode upscaled from a lossy source
(MP3/AAC), by measuring its frequency cutoff and drawing a spectrogram.

Usage:
  GUI:  python3 funkcheck.py
  CLI:  python3 funkcheck.py /path/to/file_or_folder [more paths...]
        python3 funkcheck.py --cli ~/Music
"""
import os
import sys
import subprocess

import analyzer

AUDIO_EXTS = {".flac", ".mp3", ".wav", ".m4a", ".alac", ".aac", ".ogg",
              ".opus", ".wma", ".aiff", ".aif", ".ape", ".wv", ".tak", ".tta"}

TAG_COLORS = {
    "GENUINE": "#2e7d32",
    "SUSPECT": "#f9a825",
    "FAKE":    "#c62828",
    "LOSSY":   "#1565c0",
    "ERROR":   "#616161",
}
TAG_ICON = {"GENUINE": "\u2714", "SUSPECT": "?", "FAKE": "\u2716",
            "LOSSY": "\u25CF", "ERROR": "!"}


def collect_files(paths):
    """Expand folders recursively into a flat list of audio files."""
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in sorted(names):
                    if os.path.splitext(n)[1].lower() in AUDIO_EXTS:
                        files.append(os.path.join(root, n))
        elif os.path.isfile(p):
            files.append(p)
    return files


def fmt_bitrate(b):
    if not b:
        return "?"
    return f"{round(b/1000)} kbps"


def fmt_meta(m):
    if not m:
        return "?"
    parts = [m["codec"].upper()]
    if m["sample_rate"]:
        parts.append(f"{m['sample_rate']/1000:.1f}kHz")
    if m["bits"]:
        parts.append(f"{m['bits']}-bit")
    if m["channels"]:
        parts.append(f"{m['channels']}ch")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# CLI MODE
# ---------------------------------------------------------------------------
def run_cli(paths):
    files = collect_files(paths)
    if not files:
        print("No audio files found in:", ", ".join(paths))
        return 1
    print(f"Analyzing {len(files)} file(s)...\n")
    counts = {}
    width = min(50, max(len(os.path.basename(f)) for f in files))
    for f in files:
        r = analyzer.analyze(f)
        name = os.path.basename(f)
        if "error" in r:
            tag = "ERROR"
            line = f"{TAG_ICON[tag]} {name[:width]:<{width}}  [{tag}] {r['error']}"
        else:
            tag = r["tag"]
            meta = fmt_meta(r["meta"])
            line = (f"{TAG_ICON.get(tag,'?')} {name[:width]:<{width}}  "
                    f"[{tag:7}] {meta}\n     {r['message']}")
        counts[tag] = counts.get(tag, 0) + 1
        print(line)
    print("\n" + "-" * 40)
    summary = "  ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
    print("Summary:", summary)
    return 0


# ---------------------------------------------------------------------------
# GUI MODE
# ---------------------------------------------------------------------------
def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog
    except ImportError:
        print("Tkinter is not installed. Install it with:\n"
              "  sudo apt install python3-tk\n"
              "or use CLI mode:  python3 funkcheck.py <path>")
        return 1

    import threading
    import queue

    try:
        import numpy as np
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        HAVE_PLOT = True
    except ImportError:
        HAVE_PLOT = False

    root = tk.Tk()
    root.title("Funk Check — Fake FLAC Detector")
    root.geometry("1000x620")
    root.minsize(820, 520)

    BG = "#1e1e1e"
    FG = "#e0e0e0"
    ACCENT = "#3a3a3a"
    root.configure(bg=BG)

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Treeview", background="#252525", fieldbackground="#252525",
                    foreground=FG, rowheight=26, borderwidth=0)
    style.configure("Treeview.Heading", background=ACCENT, foreground=FG,
                    borderwidth=0, font=("Sans", 9, "bold"))
    style.map("Treeview", background=[("selected", "#37474f")])
    style.configure("TButton", padding=6)

    results = {}  # iid -> result dict
    work_q = queue.Queue()

    # --- top bar ---
    top = tk.Frame(root, bg=BG)
    top.pack(fill="x", padx=12, pady=(12, 6))
    title = tk.Label(top, text="Funk Check", bg=BG, fg=FG,
                     font=("Sans", 15, "bold"))
    title.pack(side="left")
    subtitle = tk.Label(top, text="  is your FLAC real?", bg=BG, fg="#888",
                        font=("Sans", 10))
    subtitle.pack(side="left")

    btns = tk.Frame(root, bg=BG)
    btns.pack(fill="x", padx=12, pady=(0, 6))

    status = tk.Label(root, text="Add files or a folder to begin.",
                     bg=BG, fg="#9e9e9e", anchor="w", font=("Sans", 9))
    status.pack(fill="x", padx=12)

    # --- main split ---
    main = tk.PanedWindow(root, orient="horizontal", bg=BG, sashwidth=6,
                          bd=0, relief="flat")
    main.pack(fill="both", expand=True, padx=12, pady=8)

    left = tk.Frame(main, bg=BG)
    cols = ("verdict", "format", "cutoff", "detail")
    tree = ttk.Treeview(left, columns=cols, show="tree headings",
                        selectmode="browse")
    tree.heading("#0", text="File")
    tree.heading("verdict", text="Verdict")
    tree.heading("format", text="Format")
    tree.heading("cutoff", text="Cutoff")
    tree.heading("detail", text="Notes")
    tree.column("#0", width=200, anchor="w")
    tree.column("verdict", width=90, anchor="center")
    tree.column("format", width=150, anchor="w")
    tree.column("cutoff", width=70, anchor="center")
    tree.column("detail", width=260, anchor="w")
    vsb = ttk.Scrollbar(left, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    tree.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    main.add(left, stretch="always", width=560)

    for tag, col in TAG_COLORS.items():
        tree.tag_configure(tag, foreground=col)

    # right panel: spectrogram + details
    right = tk.Frame(main, bg=BG)
    main.add(right, stretch="always", width=380)

    detail_lbl = tk.Label(right, text="Select a file to see its spectrum.",
                         bg=BG, fg="#bbb", wraplength=360, justify="left",
                         anchor="nw", font=("Sans", 9))
    detail_lbl.pack(fill="x", padx=6, pady=6)

    canvas_holder = tk.Frame(right, bg=BG)
    canvas_holder.pack(fill="both", expand=True, padx=6, pady=6)
    plot_state = {"canvas": None}

    def draw_spectrum(r):
        if not HAVE_PLOT:
            detail_lbl.config(
                text=detail_lbl.cget("text") +
                "\n\n(Install matplotlib for the spectrum graph:\n pip install matplotlib)")
            return
        if plot_state["canvas"]:
            plot_state["canvas"].get_tk_widget().destroy()
        fig = Figure(figsize=(4, 3), dpi=90, facecolor="#1e1e1e")
        ax = fig.add_subplot(111, facecolor="#161616")
        freqs = r["freqs"] / 1000.0
        ax.plot(freqs, r["psd_db"], color="#4fc3f7", linewidth=0.8)
        cut = r["cutoff"] / 1000.0
        ax.axvline(cut, color="#e57373", linestyle="--", linewidth=1)
        ax.text(cut, -3, f" {cut:.1f}kHz", color="#e57373", fontsize=8,
                va="top")
        ax.set_xlim(0, r["sr"] / 2000.0)
        ax.set_ylim(-120, 3)
        ax.set_xlabel("kHz", color="#aaa", fontsize=8)
        ax.set_ylabel("dB", color="#aaa", fontsize=8)
        ax.tick_params(colors="#888", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#444")
        ax.grid(True, color="#333", linewidth=0.4)
        fig.tight_layout()
        cv = FigureCanvasTkAgg(fig, master=canvas_holder)
        cv.draw()
        cv.get_tk_widget().pack(fill="both", expand=True)
        plot_state["canvas"] = cv

    def on_select(_evt=None):
        sel = tree.selection()
        if not sel:
            return
        r = results.get(sel[0])
        if not r or "error" in r:
            detail_lbl.config(text=r.get("error", "No data") if r else "No data")
            return
        m = r["meta"]
        txt = (f"{os.path.basename(r['path'])}\n\n"
               f"Container: {m['container']}\n"
               f"Codec: {m['codec'].upper()}   "
               f"{fmt_bitrate(m['bitrate'])}\n"
               f"Sample rate: {m['sample_rate']} Hz"
               + (f"   {m['bits']}-bit" if m['bits'] else "") + "\n"
               f"Measured cutoff: {r['cutoff']/1000:.1f} kHz\n"
               f"Rolloff sharpness: {r['sharpness']:.0f} dB\n\n"
               f"→ {r['message']}")
        detail_lbl.config(text=txt)
        draw_spectrum(r)

    tree.bind("<<TreeviewSelect>>", on_select)

    # --- worker ---
    def analyze_files(files):
        for f in files:
            r = analyzer.analyze(f)
            work_q.put(r)
        work_q.put({"__done__": True, "n": len(files)})

    def poll_queue():
        try:
            while True:
                r = work_q.get_nowait()
                if r.get("__done__"):
                    status.config(text=f"Done — {len(results)} file(s) analyzed.")
                    continue
                add_result(r)
        except queue.Empty:
            pass
        root.after(120, poll_queue)

    def add_result(r):
        name = os.path.basename(r["path"])
        if "error" in r:
            iid = tree.insert("", "end", text=name,
                              values=("ERROR", "-", "-", r["error"]),
                              tags=("ERROR",))
        else:
            tag = r["tag"]
            cut = f"{r['cutoff']/1000:.1f}k" if r.get("cutoff") else "-"
            iid = tree.insert("", "end", text=name,
                              values=(f"{TAG_ICON.get(tag,'')} {tag}",
                                      fmt_meta(r["meta"]), cut, r["message"]),
                              tags=(tag,))
        results[iid] = r
        status.config(text=f"Analyzing... {len(results)} done")

    def start(files):
        files = collect_files(files)
        if not files:
            status.config(text="No audio files found.")
            return
        status.config(text=f"Scanning {len(files)} file(s)...")
        threading.Thread(target=analyze_files, args=(files,),
                         daemon=True).start()

    def add_files():
        fs = filedialog.askopenfilenames(
            title="Choose audio files",
            filetypes=[("Audio", "*.flac *.mp3 *.wav *.m4a *.ogg *.opus "
                        "*.aac *.wma *.ape *.wv *.aiff"), ("All files", "*.*")])
        if fs:
            start(list(fs))

    def add_folder():
        d = filedialog.askdirectory(title="Choose a music folder")
        if d:
            start([d])

    def clear_all():
        for iid in tree.get_children():
            tree.delete(iid)
        results.clear()
        status.config(text="Cleared.")

    tk.Button(btns, text="＋ Add files", command=add_files, bg=ACCENT,
              fg=FG, relief="flat", padx=10, pady=4,
              activebackground="#4a4a4a").pack(side="left", padx=(0, 6))
    tk.Button(btns, text="📁 Add folder", command=add_folder, bg=ACCENT,
              fg=FG, relief="flat", padx=10, pady=4,
              activebackground="#4a4a4a").pack(side="left", padx=6)
    tk.Button(btns, text="Clear", command=clear_all, bg=ACCENT, fg=FG,
              relief="flat", padx=10, pady=4,
              activebackground="#4a4a4a").pack(side="left", padx=6)

    # accept paths passed on the command line into the GUI too
    if len(sys.argv) > 1:
        initial = [a for a in sys.argv[1:] if a != "--gui"]
        if initial:
            root.after(300, lambda: start(initial))

    poll_queue()
    root.mainloop()
    return 0


def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    # CLI if a real path is given (and not forced GUI)
    force_cli = "--cli" in args
    paths = [a for a in args if a not in ("--cli", "--gui")]
    if force_cli or (paths and "--gui" not in args and not os.environ.get("DISPLAY_FORCE_GUI")):
        # If paths exist on disk -> CLI batch. Otherwise fall through to GUI.
        if paths and all(os.path.exists(p) for p in paths):
            return run_cli(paths)
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
