#!/usr/bin/env python3
"""Shared subtitle-studio logic: probing, ASS/SRT building, whisper decode,
Gemini translation, yt-dlp download. Used by both the FastAPI app and the
Streamlit app."""
import json
import re
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
FONT_FILE = ASSETS_DIR / "NotoSansMyanmar.ttf"

MAX_VIDEO_SECONDS = 600


# ------------------------------------------------------------------ probing

def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=width,height,codec_type",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60)
    info = json.loads(out.stdout or "{}")
    duration, width, height = 0.0, 0, 0
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            width, height = s.get("width", 0), s.get("height", 0)
    try:
        duration = float(info.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        pass
    return {"duration": duration, "width": width, "height": height}


def ffmpeg_bin() -> str:
    """System ffmpeg, falling back to the imageio-ffmpeg static binary."""
    import shutil
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return sys_ff
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def ffprobe_bin() -> str:
    import shutil
    return shutil.which("ffprobe") or "ffprobe"


# ------------------------------------------------------------------ download

def download_youtube(url: str, target: Path) -> dict:
    """Download best <=1080p mp4 via yt-dlp. Returns info dict."""
    import yt_dlp
    ydl_opts = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(target),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url.strip(), download=True)
    if not target.exists():
        cands = sorted(target.parent.glob(target.stem + ".*"))
        if cands:
            cands[0].rename(target)
    return info or {}


def normalize_video(src: Path, dst: Path):
    """Re-encode to browser-friendly h264/aac mp4."""
    r = subprocess.run(
        [ffmpeg_bin(), "-y", "-v", "error", "-i", str(src),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-c:a", "aac", "-movflags", "+faststart", str(dst)],
        capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"video convert မရပါ: {r.stderr[:200]}")


# ------------------------------------------------------------------ whisper

def decode_audio_16k(path: Path):
    """Decode any audio/video to 16kHz mono float32 numpy array via ffmpeg."""
    import numpy as np
    r = subprocess.run(
        [ffmpeg_bin(), "-v", "error", "-i", str(path),
         "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True, timeout=600)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("audio decode မရပါ")
    return np.frombuffer(r.stdout, dtype=np.float32)


def transcribe_file(path: Path, model_name: str = "base",
                    language: str | None = None) -> tuple[list, str, float]:
    """Returns (segments, detected_language, language_probability)."""
    import gc
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    try:
        audio = decode_audio_16k(path)
        seg_iter, info = model.transcribe(
            audio, language=language, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500})
        segs = []
        for i, s in enumerate(seg_iter):
            text = s.text.strip()
            if text:
                segs.append({"start": round(s.start, 2),
                             "end": round(s.end, 2),
                             "text": text, "mm": ""})
        return segs, info.language, round(info.language_probability, 3)
    finally:
        del model
        gc.collect()


# ------------------------------------------------------------------ translate

def build_translate_prompt(segments: list) -> str:
    numbered = "\n".join(f"{i+1}. {s['text']}" for i, s in enumerate(segments))
    return (
        "Translate each numbered subtitle line below into natural, casual "
        "spoken Myanmar (Burmese) as used in Myanmar-dubbed movies. Keep the "
        "same numbering, one translation per line, no extra commentary. "
        "Keep names as-is. Keep it short enough to read as a subtitle.\n\n"
        f"{numbered}"
    )


def parse_translate_response(text: str, n: int) -> list:
    out = [""] * n
    for line in text.strip().splitlines():
        m = re.match(r"\s*(\d+)\s*[.\):\-]\s*(.*)", line)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < n:
                out[idx] = m.group(2).strip()
    return out


def gemini_translate(api_key: str, segments: list) -> list:
    import requests
    if not segments:
        return []
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "gemini-2.0-flash:generateContent")
    results: list = []
    for b in range(0, len(segments), 60):
        chunk = segments[b:b + 60]
        body = {"contents": [{"parts": [{"text": build_translate_prompt(chunk)}]}],
                "generationConfig": {"temperature": 0.3}}
        r = requests.post(url, params={"key": api_key}, json=body, timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"Gemini error {r.status_code}: {r.text[:200]}")
        data = r.json()
        try:
            txt = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise RuntimeError(f"Gemini unexpected response: {str(data)[:200]}")
        results.extend(parse_translate_response(txt, len(chunk)))
    return results


# ------------------------------------------------------------------ subtitles

def fmt_ass_time(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def fmt_srt_time(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_escape(t: str) -> str:
    return t.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def wrap_mm(text: str, per_line: int = 26) -> str:
    text = " ".join(text.split())
    if len(text) <= per_line:
        return text
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if len(trial) > per_line and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        while len(ln) > per_line * 2:
            out.append(ln[:per_line])
            ln = ln[per_line:]
        out.append(ln)
    return "\\N".join(out)


def build_ass_file(ass_path: Path, segments: list, width: int, height: int,
                   font_size: int = 64, position: str = "bottom"):
    align = 2 if position == "bottom" else 8
    margin_v = max(60, int(height * 0.06))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: MM,Noto Sans Myanmar,{font_size},&H00FFFFFF,&H000019FF,&H80000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,{align},40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for s in segments:
        txt = (s.get("mm") or s.get("text") or "").strip()
        if not txt:
            continue
        try:
            start, end = float(s["start"]), float(s["end"])
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        events.append(
            f"Dialogue: 0,{fmt_ass_time(start)},{fmt_ass_time(end)},"
            f"MM,,0,0,0,,{ass_escape(wrap_mm(txt))}")
    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def build_srt(segments: list, use_mm: bool = True) -> str:
    lines = []
    n = 0
    for s in segments:
        txt = ((s.get("mm") or s.get("text", "")) if use_mm
               else s.get("text", "")).strip()
        if not txt:
            continue
        n += 1
        lines.append(f"{n}\n{fmt_srt_time(float(s['start']))} --> "
                     f"{fmt_srt_time(float(s['end']))}\n{txt}\n")
    return "\n".join(lines)


FONT_URL = ("https://raw.githubusercontent.com/google/fonts/main/"
            "ofl/notosansmyanmar/NotoSansMyanmar%5Bwdth%2Cwght%5D.ttf")


def ensure_font():
    """Download Noto Sans Myanmar on first run if not bundled."""
    if FONT_FILE.exists():
        return
    import requests
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    r = requests.get(FONT_URL, timeout=120)
    r.raise_for_status()
    if len(r.content) < 100_000:
        raise RuntimeError("font download မအောင်မြင်ပါ")
    FONT_FILE.write_bytes(r.content)


def burn_subtitles(src: Path, ass_path: Path, out_path: Path):
    ensure_font()
    if not FONT_FILE.exists():
        raise RuntimeError("Myanmar font မတွေ့ပါ")
    vf = f"ass={ass_path}:fontsdir={ASSETS_DIR}"
    r = subprocess.run(
        [ffmpeg_bin(), "-y", "-v", "error", "-i", str(src),
         "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-c:a", "copy", "-movflags", "+faststart", str(out_path)],
        capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"render မအောင်မြင်ပါ: {r.stderr[:300]}")
