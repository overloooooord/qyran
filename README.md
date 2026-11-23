# QYRAN

**Voice-to-3D Operational Map for Emergency Response, Critical Infrastructure, and Situation Centers.**  
*Ты говоришь, карта видит — голос на казахском и русском превращается в оперативную 3D-карту за секунды, полностью on-premise.*

[![Live Demo](https://img.shields.io/badge/Live%20Demo-GitHub%20Pages-ef4444)](https://overloooooord.github.io/qyran/)
![Languages](https://img.shields.io/badge/ASR-Kazakh%20%2B%20Russian-0ea5e9)
![Deployment](https://img.shields.io/badge/Deployment-100%25%20On--Premise-22c55e)
![License: MIT](https://img.shields.io/badge/License-MIT-slate)

![QYRAN Cover](assets/cover-1920x1080.png)

---

## Live Interactive Demos

Open directly in **Chrome / Edge / Firefox** (zero backend setup required):

- **AI Command Console (Full Scenario + Audio):** [overloooooord.github.io/qyran](https://overloooooord.github.io/qyran/)  
  Press **«▶ Запустить эфир»** to run the 10-message **Zenkova 24 (Almaty)** scenario with live radio audio, waveform, raw `kazakh-whisper-turbo` ASR vs LLM entity repair, 3D MapLibre map, multi-floor building view, unit routing, and one-click report generation.
- **Live Voice / Text Map Console:** [overloooooord.github.io/qyran/demo/live.html](https://overloooooord.github.io/qyran/demo/live.html)
- **Interactive 3D Pitch Deck:** [overloooooord.github.io/qyran/demo/pitch.html](https://overloooooord.github.io/qyran/demo/pitch.html)
- **Operator Manual (RU / KZ):** [overloooooord.github.io/qyran/demo/manual.html](https://overloooooord.github.io/qyran/demo/manual.html)
- **Pitch Deck PDF:** [`docs/QYRAN_pitch.pdf`](docs/QYRAN_pitch.pdf) · **Architecture:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## Why QYRAN?

During simultaneous emergencies—fires, earthquakes, drone incidents, or facility breaches—human dispatchers sit as a manual bottleneck between voice radios and GIS screens. When 10+ reports arrive in parallel, operators write notes by hand, search map squares, and relay updates late.

**QYRAN removes the manual step:**
1. **Works Over Existing Radios & Phones:** Plugs into current analog/digital radios via a hardware gateway (prototyped with **Almaty FabLab**) without replacing legacy comms fleets.
2. **Bilingual Radio-Grade ASR (`kk` + `ru`):** Tuned for Kazakh and Russian radio traffic (`kazakh-whisper-turbo` offline on CPU) with contextual LLM correction for noisy transmissions.
3. **3D City & Multi-Floor Mapping:** Automatically extracts *who, what, where, floor, count, altitude, and heading*, plots 3D markers and trajectory forecasts, ranks alerts by severity, and logs every decision.
4. **100% On-Premise & Sovereign:** Zero external cloud calls; designed for government situation centers, emergency services (MES/MChS), and critical infrastructure (energy, oil & gas, transport).

---

## Repository Contents

```text
qyran/
├── index.html                 # Main AI Command Console (embedded 10x WAV audio + 3D MapLibre)
├── demo/
│   ├── live.html              # Live mic / text voice-to-3D-map demo
│   ├── pitch.html             # Interactive 3D web pitch presentation
│   └── manual.html            # Bilingual RU/KZ operator guide
├── docs/
│   ├── ARCHITECTURE.md        # Pipeline, ASR/LLM repair, and deployment roadmap
│   └── QYRAN_pitch.pdf        # 14-slide pitch deck PDF
└── data/
    └── radio_kk/
        ├── t01.wav ... t10.wav # 10 radio-filtered WAV transmissions (16 kHz mono)
        └── transcripts.txt    # Ground truth, raw kazakh-whisper-turbo ASR, and timings
```

---

## Run Locally

Clone the repository and serve it via any static HTTP server (or open `index.html` directly in Chrome):

```bash
git clone https://github.com/overloooooord/qyran.git
cd qyran
python3 -m http.server 8080
```

Then open **http://localhost:8080** in your browser.

---

## Radio ASR Sample Benchmarks

All 10 test clips in [`data/radio_kk/`](data/radio_kk/) are synthetic training transmissions filtered to a 300–3400 Hz radio passband with channel noise and squelch effects, transcribed offline on 4 CPU cores using `kazakh-whisper-turbo` (`3.40 s – 4.37 s` per clip):

| Clip | Route | Lang | Raw `kazakh-whisper-turbo` Time | Example LLM Context Repair |
|---|---|---|---|---|
| `t01.wav` | `Бүркіт-2 -> Сұңқар` | `kk` | `4.19 s` | Drone grid 7, ~300 m, north |
| `t03.wav` | `Бүркіт-1 -> Сұңқар` | `kk` | `4.02 s` | `дүркіт` → `Бүркіт` |
| `t04.wav` | `Сұңқар -> Барыс-1` | `kk` | `4.37 s` | `қосшаңыз` → `қоршаңыз` |
| `t06.wav` | `Бүркіт-2 -> Сұңқар` | `kk` | `4.08 s` | `дұран` → `дрон` |
| `t07.wav` | `Арлан-3 -> Сұңқар` | `ru` | `3.40 s` | `сумкар` → `Сункар`, `дом` → `дым` |

See [`data/radio_kk/transcripts.txt`](data/radio_kk/transcripts.txt) for all 10 transcripts.

> **Note:** In this web demo, audio clips are pre-recorded synthetic exercises while ASR transcripts reflect actual offline `kazakh-whisper-turbo` runs. Camera object detection (`YOLO` / `Frigate NVR`), ESP32 Wi-Fi CSI indoor sensing (`esp-csi`), GPS/Meshtastic tracking, and Telegram P1 dispatch integrations are included as interactive previews on the 1–6 month pilot roadmap.

---

## Roadmap & Business Model

- **Now:** Working MVP (voice-to-3D-map console, `kk`/`ru` ASR + entity parsing, multi-floor indoor mode)
- **1–3 Months:** On-premise AI server package, Telegram alerts, FabLab hardware radio gateway
- **3–6 Months:** First 1–2 month single-facility pilot → annual per-console / per-facility license + gateway integration

---

## Team

- **Yeraly Abutalifuly** — ML Engineer · Backend · Project Lead (Python, FastAPI, Django, ML/NLP, Telegram bots)
- **Adelia** — ML Engineer · Backend (Python, ML, Backend, Data visualization)

## License

[MIT](LICENSE)
