#!/usr/bin/env python3
"""Subtitle Studio — Streamlit version (Streamlit Community Cloud, free).

Flow: YouTube URL / file upload -> transcribe (faster-whisper)
-> translate to Myanmar (Gemini) -> edit in table -> burn into MP4 (ffmpeg).
"""
import gc
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from subutils import (  # noqa: E402
    ASSETS_DIR, FONT_FILE, MAX_VIDEO_SECONDS, build_ass_file, build_srt,
    burn_subtitles, download_youtube, ffmpeg_bin, gemini_translate,
    normalize_video, probe, transcribe_file,
)

st.set_page_config(page_title="စာတန်းထိုး စတူဒီယို", layout="centered")

# ------------------------------------------------------------------ state

def ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]

workdir = ss("workdir", None)
if workdir is None:
    workdir = tempfile.mkdtemp(prefix="sstudio_")
    st.session_state.workdir = workdir
WORK = Path(workdir)

ss("video_path", None)
ss("video_meta", None)
ss("segments", [])
ss("output_path", None)
ss("api_key", "")

# ------------------------------------------------------------------ header

st.title("🎬 စာတန်းထိုး စတူဒီယို")
st.caption("Short film တွေကို မြန်မာစာတန်းထိုးနဲ့ ပြန်ထုတ်ဖို့ — "
           "link ထည့် / ဖိုင်တင် → စာသားထုတ် → ပြန်ဆို → ဗီဒီယိုထုတ်")

if st.button("＋ အသစ်စ", key="reset"):
    shutil.rmtree(WORK, ignore_errors=True)
    for k in ("video_path", "video_meta", "segments", "output_path"):
        st.session_state[k] = [] if k == "segments" else None
    st.session_state.workdir = tempfile.mkdtemp(prefix="sstudio_")
    st.rerun()

# ------------------------------------------------------------------ step 1

st.header("၁။ ဗီဒီယို ထည့်ပါ")

url = st.text_input("YouTube link", placeholder="https://youtube.com/shorts/…")
if st.button("ဗီဒီယို ရယူမယ်", disabled=not url.strip()):
    with st.spinner("ဗီဒီယို ရယူနေပါတယ်…"):
        try:
            target = WORK / "source.mp4"
            if target.exists():
                target.unlink()
            info = download_youtube(url, target)
            pr = probe(target)
            if pr["duration"] > MAX_VIDEO_SECONDS:
                st.error(f"ဗီဒီယိုက {int(pr['duration'])} စက္ကန့်ရှိပြီး "
                         f"ကန့်သတ်ချက် ({MAX_VIDEO_SECONDS}) ကျော်နေပါတယ်")
            else:
                norm = WORK / "source_norm.mp4"
                try:
                    normalize_video(target, norm)
                    norm.replace(target)
                    pr = probe(target)
                except RuntimeError:
                    pass
                st.session_state.video_path = str(target)
                st.session_state.video_meta = {
                    "title": (info or {}).get("title", "video"),
                    "duration": pr["duration"],
                    "width": pr["width"], "height": pr["height"]}
                st.session_state.segments = []
                st.session_state.output_path = None
                st.success("ရပါပြီ ✅")
                st.rerun()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if ("403" in msg or "bot" in msg.lower()
                    or "Sign in to confirm" in msg):
                st.error("⚠️ YouTube က ဒီ server ကနေ တိုက်ရိုက်ဆွဲတာ "
                         "ပိတ်ထားလို့ မရပါ။\n\nအလွယ်နည်း: Safari မှာ "
                         "**ssyoutube.com** ဖွင့် → link paste → Download လုပ် → "
                         "အောက်က **Upload** နဲ့ ဖိုင်တင်ပေးပါ။ "
                         "ကျန်အဆင့်တွေ အကုန်အလုပ်လုပ်ပါတယ် ✅")
            else:
                st.error(f"ဗီဒီယို ဒေါင်းလုဒ် မရပါ: {msg[:200]}")

st.divider()
up = st.file_uploader("သို့မဟုတ် ဖိုင်တင်မယ်", type=["mp4", "mov", "mkv", "webm"])
if up is not None and st.button("ဖိုင်ကို သုံးမယ်"):
    with st.spinner("ဖိုင် တင်နေပါတယ်…"):
        target = WORK / "source.mp4"
        with open(target, "wb") as f:
            f.write(up.getbuffer())
        pr = probe(target)
        if pr["duration"] <= 0 or pr["width"] <= 0:
            st.error("ဗီဒီယိုဖိုင် ဖတ်မရပါ")
        elif pr["duration"] > MAX_VIDEO_SECONDS:
            st.error("ဗီဒီယို ကြာချိန် ကန့်သတ်ချက် ကျော်နေပါတယ်")
        else:
            norm = WORK / "source_norm.mp4"
            try:
                normalize_video(target, norm)
                norm.replace(target)
                pr = probe(target)
            except RuntimeError:
                pass
            st.session_state.video_path = str(target)
            st.session_state.video_meta = {
                "title": up.name, "duration": pr["duration"],
                "width": pr["width"], "height": pr["height"]}
            st.session_state.segments = []
            st.session_state.output_path = None
            st.success("ရပါပြီ ✅")
            st.rerun()

st.caption("⚠️ YouTube က bot-check တောင်းတတ်လို့ link နဲ့ မရရင် "
           "ဖိုင်ကို တခြားနည်းနဲ့ download လုပ်ပြီး တင်ပေးပါ။")

# ------------------------------------------------------------------ step 2

if st.session_state.video_path:
    meta = st.session_state.video_meta or {}
    st.header(f"၂။ ဗီဒီယို — {meta.get('title', '')}")
    st.video(st.session_state.video_path)
    st.caption(f"ကြာချိန် {meta.get('duration', 0):.0f} စက္ကန့် · "
               f"{meta.get('width', 0)}×{meta.get('height', 0)}")

    model = st.selectbox("Transcribe model",
                         ["base", "small"],
                         format_func=lambda m: "base — မြန်တယ်"
                         if m == "base" else "small — ပိုမှန်တယ် (ကြာမယ်)")
    if st.button("🎙 အသံကနေ စာသားထုတ်မယ်"):
        with st.spinner("စာသားထုတ်နေပါတယ်… (ဗီဒီယိုအရှည်ပေါ် မူတည်ပြီး ကြာနိုင်တယ်)"):
            try:
                t0 = time.time()
                segs, lang, prob = transcribe_file(
                    Path(st.session_state.video_path), model)
                gc.collect()
                st.session_state.segments = segs
                st.success(f"စာကြောင်း {len(segs)} ကြောင်း ရပါပြီ ✅ "
                           f"(တွေ့တဲ့ဘာသာ: {lang}, {time.time()-t0:.0f} စက္ကန့်)")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"စာသားထုတ်မရပါ: {e}")

# ------------------------------------------------------------------ step 3

if st.session_state.segments:
    st.header("၃။ မြန်မာလို ပြန်ဆိုမယ်")
    key = st.text_input("Gemini API key", type="password",
                        value=st.session_state.api_key,
                        help="aistudio.google.com/apikey မှာ အလကားရယူနိုင်တယ်")
    st.session_state.api_key = key
    if st.button("🌐 အကုန် မြန်မာလို ပြန်ဆိုမယ်", disabled=not key.strip()):
        with st.spinner("မြန်မာလို ပြန်ဆိုနေပါတယ်…"):
            try:
                mm = gemini_translate(key.strip(), st.session_state.segments)
                for s, t in zip(st.session_state.segments, mm):
                    if t:
                        s["mm"] = t
                st.success("ပြန်ဆိုပြီးပါပြီ ✅ — လိုအပ်တာ အောက်မှာ ပြင်လို့ရတယ်")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"ပြန်ဆိုမရပါ: {e}")

    st.subheader("စာသားပြင်မယ်")
    st.caption("ဇယားထဲမှာ တိုက်ရိုက်ပြင် / အတန်းအသစ်ထည့် / ဖျက်လို့ရတယ်")
    df = pd.DataFrame(st.session_state.segments,
                      columns=["start", "end", "text", "mm"])
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "start": st.column_config.NumberColumn("စ (စက္ကန့်)", format="%.2f"),
            "end": st.column_config.NumberColumn("ဆုံး (စက္ကန့်)", format="%.2f"),
            "text": st.column_config.TextColumn("မူရင်းစာသား", width="medium"),
            "mm": st.column_config.TextColumn("မြန်မာစာတန်း", width="large"),
        },
        key="seg_editor",
    )
    clean = []
    for _, r in edited.iterrows():
        try:
            s_, e_ = float(r["start"]), float(r["end"])
        except (TypeError, ValueError):
            continue
        if e_ <= s_ or s_ < 0:
            continue
        clean.append({"start": round(s_, 2), "end": round(e_, 2),
                      "text": str(r["text"] or "")[:500],
                      "mm": str(r["mm"] or "")[:500]})
    st.session_state.segments = clean

    # ---------------------------------------------------------- step 4
    st.header("၄။ စာတန်းပုံစံ & ဗီဒီယိုထုတ်")
    c1, c2 = st.columns(2)
    with c1:
        font_size = st.slider("စာလုံးအရွယ်", 40, 110, 64)
    with c2:
        position = st.selectbox("စာတန်းနေရာ", ["bottom", "top"],
                                format_func=lambda p: "အောက်ခြေ"
                                if p == "bottom" else "အပေါ်")

    # style preview: burn subtitle onto one frame
    if st.button("🔍 နမူနာ frame ကြည့်မယ်"):
        meta = st.session_state.video_meta or {}
        segs = st.session_state.segments
        if segs:
            t = float(segs[0]["start"]) + 0.5
            ass = WORK / "preview.ass"
            build_ass_file(ass, segs, meta.get("width") or 1080,
                           meta.get("height") or 1920, font_size, position)
            frame = WORK / "preview.png"
            r = subprocess.run(
                [ffmpeg_bin(), "-y", "-v", "error", "-ss", str(t),
                 "-i", st.session_state.video_path,
                 "-vf", f"ass={ass}:fontsdir={ASSETS_DIR}",
                 "-frames:v", "1", str(frame)],
                capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and frame.exists():
                st.image(str(frame), caption="စာတန်းပုံ နမူနာ")
            else:
                st.error("နမူနာ ထုတ်မရပါ")

    if st.button("🎬 စာတန်းထိုး ဗီဒီယို ထုတ်မယ်", type="primary"):
        with st.spinner("ဗီဒီယို ထုတ်နေပါတယ်… (ခဏစောင့်ပါ)"):
            try:
                meta = st.session_state.video_meta or {}
                ass = WORK / "subs.ass"
                build_ass_file(ass, st.session_state.segments,
                               meta.get("width") or 1080,
                               meta.get("height") or 1920, font_size, position)
                out = WORK / "myanmar_subtitled.mp4"
                burn_subtitles(Path(st.session_state.video_path), ass, out)
                gc.collect()
                st.session_state.output_path = str(out)
                st.success(f"ပြီးပါပြီ ✅ ({out.stat().st_size/1048576:.1f} MB)")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"render မအောင်မြင်ပါ: {e}")

    if st.session_state.output_path and Path(st.session_state.output_path).exists():
        st.video(st.session_state.output_path)
        with open(st.session_state.output_path, "rb") as f:
            st.download_button("⬇ ဗီဒီယို ဒေါင်းလုဒ်", f,
                               file_name="myanmar_subtitled.mp4",
                               mime="video/mp4")
        srt = build_srt(st.session_state.segments, use_mm=True)
        st.download_button("📄 SRT ယူမယ်", srt.encode("utf-8"),
                           file_name="subtitles_mm.srt", mime="text/plain")

st.divider()
st.caption("စာတန်းထိုး စတူဒီယို — short films with Myanmar subtitles")
