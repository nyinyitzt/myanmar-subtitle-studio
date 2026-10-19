# စာတန်းထိုး စတူဒီယို (Subtitle Studio)

Short film တွေကို မြန်မာစာတန်းထိုးနဲ့ ပြန်ထုတ်ဖို့ website (အလကား hosting).

**Flow:** YouTube link / ဖိုင်တင် → 🎙 အသံကနေ စာသားထုတ် (Whisper)
→ 🌐 မြန်မာလို ပြန်ဆို (Gemini) → ဇယားထဲမှာ စာသားပြင်/အချိန်ညှိ
→ 🔍 နမူနာ frame ကြည့် → 🎬 စာတန်းပါ MP4 ထုတ်

## Deploy (Streamlit Community Cloud — အလကား, ကတ် မလို)

1. **github.com** မှာ account အလကား ဖွင့်
2. GitHub → Settings → Developer settings → Personal access tokens
   → Tokens (classic) → Generate new → scope `repo` ရွေး → token copy
   (code တင်ပြီးရင် token ကို ပြန် delete လုပ်လို့ရတယ်)
3. ဒီ repo ရဲ့ root files တွေကို GitHub repo အသစ် (`myanmar-subtitle-studio`)
   ထဲ push:
   `streamlit_app.py`, `subutils.py`, `requirements.txt`, `packages.txt`,
   `assets/`, `README.md`, `.gitignore`
4. **share.streamlit.io** → Sign in with GitHub → New app
   → repo/branch/`streamlit_app.py` ရွေး → Deploy
5. `https://<app-name>.streamlit.app` မှာ public သုံးလို့ရပြီ.
   Code push�ိုင်း auto redeploy ဖြစ်တယ်.

`packages.txt` က cloud မှာ `ffmpeg` install လုပ်ပေးတယ်
(`subutils.ffmpeg_bin()` က system ffmpeg မတွေ့ရင်
imageio-ffmpeg static binary ကို fallback သုံးတယ်).

## API keys

- **Gemini API key** (ဘာသာပြန်ဖို့): https://aistudio.google.com/apikey — အလကား.
  Website ထဲမှာပဲ ထည့်သုံးတာ (browser session ထဲပဲ ရှိတယ်, server မသိမ်းဘူး).
- တခြား key မလိုဘူး.

## Notes

- YouTube link နဲ့ ဆွဲတာ bot-check မိရင် error ပြမယ် — အဲဒီအခါ ဖိုင်ကို
  တခြားနည်းနဲ့ download လုပ်ပြီး upload တင်ပါ.
- ဗီဒီယို ကန့်သတ်ချက်: ၁၀ မိနစ်အထိ.
- Streamlit Cloud free: 1GB RAM / 1 CPU — transcribe လုပ်ပြီးတိုင်း model ကို
  memory ကနေ လွှတ်ပေးတယ် (`transcribe_file` in subutils.py).
- `docker/` folder ထဲမှာ FastAPI + Docker version (HF PRO / VPS hosting အတွက်).

## Local run (Streamlit)

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/streamlit run streamlit_app.py
```
