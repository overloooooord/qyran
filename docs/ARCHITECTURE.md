# QYRAN Architecture

**QYRAN** is an on-premise AI layer over existing radio and phone communications that turns live **Kazakh (`kk`)** and **Russian (`ru`)** voice reports into a real-time **3D operational map**, prioritized incident feed, and commander action log.

---

## 1. End-to-End Pipeline

```text
Radio / Phone Audio (kk · ru)
   │  300–3400 Hz analog/digital channel via Hardware Gateway (Almaty FabLab)
   ▼
Local Speech Recognition (On-Premise)
   │  kazakh-whisper-turbo (4 CPU cores offline; 3.40–4.37 s per ~4 s clip)
   ▼
Contextual LLM Repair & Spatial Entity Extraction
   │  Fixes radio ASR artifacts (e.g. "дұран" -> "дрон", "Сумкар" -> "Сұңқар")
   │  Extracts: caller, recipient, incident type, grid/address, floor, count, altitude, heading, action
   ▼
3D Operational Map & Command Console (MapLibre GL + OpenFreeMap)
   ├── City-scale 3D map markers, drone tracks, perimeter zones, unit routing
   ├── Multi-floor indoor 3D schematic (floor threats, evacuees, response forces)
   ├── Commander decision queue + one-click response & auto-report export
   └── Telegram P1 alerts & full audit log
```

---

## 2. Core Components in This Repository

| Component | Path | Description |
|---|---|---|
| **AI Command Console** | [`index.html`](../index.html) | Self-contained dark command console with 10 embedded Kazakh/Russian radio WAV transmissions, real-time audio waveform, Whisper-kk ASR + LLM diff highlight, MapLibre GL 3D map (`Zenkova 24` scenario), multi-floor building viewer, task tracking (`ПРИНЯЛ → В ПУТИ → НА МЕСТЕ → ВЫПОЛНЕНО`), and one-click report export. |
| **Live Voice-to-Map Demo** | [`demo/live.html`](../demo/live.html) | Lightweight interactive console supporting browser mic / text input for instant Almaty grid/landmark incident plotting. |
| **Interactive 3D Pitch** | [`demo/pitch.html`](../demo/pitch.html) | 13-slide interactive web pitch deck with live MapLibre 3D backgrounds and interactive command demo. |
| **Operator Manual** | [`demo/manual.html`](../demo/manual.html) | Bilingual Russian + Kazakh operator walkthrough covering radio feed, map layers, 3D building view, and report generation. |
| **Radio Audio Dataset** | [`data/radio_kk/`](../data/radio_kk/) | 10 mono 16 kHz WAV radio clips (`t01.wav`–`t10.wav`) and [`transcripts.txt`](../data/radio_kk/transcripts.txt) with ground truth, raw `kazakh-whisper-turbo` ASR output, and CPU timings. |
| **Pitch Deck PDF** | [`docs/QYRAN_pitch.pdf`](QYRAN_pitch.pdf) | Full 14-page presentation prepared for Defense Tech Hub x MOST Property Pitch Competition. |

---

## 3. ASR Benchmark (`kazakh-whisper-turbo`)

Audio samples in [`data/radio_kk/`](../data/radio_kk/) simulate noisy radio transmissions (Kazakh/Russian speech filtered to 300–3400 Hz with channel noise, squelch clicks, and call tones). Speech recognition runs **offline on 4 CPU cores** using `kazakh-whisper-turbo`:

- **Clip duration:** ~3.4–4.4 seconds per transmission (`t01.wav`–`t10.wav`)
- **Offline CPU inference time:** `3.40 s` to `4.37 s` (documented in `data/radio_kk/transcripts.txt`)
- **Contextual LLM corrections:** Domain post-processing repairs common radio distortion errors before spatial plotting:
  - `дұран` → `дрон` (`t06.wav`)
  - `дүркіт` → `Бүркіт` (`t03.wav`)
  - `қосшаңыз` → `қоршаңыз` (`t04.wav`)
  - `сумкар` → `Сункар`, `вижу дом на крыше` → `дым на крыше` (`t07.wav`)

---

## 4. Deployment & Roadmap

- **Current Stage (Working MVP):** Real-time voice-to-3D-map UI, bilingual `kk`/`ru` offline ASR pipeline, entity extraction, and operator workflow simulation.
- **1–3 Months:** Production on-premise AI bundle, Telegram P1 alert integration, and hardware radio gateway prototype built with **Almaty FabLab**.
- **3–6 Months:** Single-facility customer pilot + multimodal ingestion (YOLO / Frigate NVR cameras, GPS/Meshtastic trackers, and ESP32 Wi-Fi CSI indoor sensing).

> **Demo Transparency:** In this standalone browser demo, radio transmissions are pre-recorded synthetic training clips processed through local `kazakh-whisper-turbo` ASR, while camera detection, ESP32 Wi-Fi CSI indoor localization, and external dispatch calls are UI integration previews for the pilot phase.
