# QYRAN 2.0 — Архитектура системы (IT FEST 2026)

```text
[Аналоговая/цифровая рация · Живой микрофон PTT · WAV/MP3 загрузка]
        │  16 kHz mono (ffmpeg) · опц. радиофильтр 300–3400 Гц (scipy Butterworth)
        ▼
[Audio DSP & Telemetry — backend/audio_dsp.py]
        │  Расчёт SNR (дБ), RMS, Voice Activity Ratio, 64-bin waveform
        ▼
[On-Premise Bilingual ASR — backend/asr_engine.py]
        │  openai/whisper-large-v3-turbo (CUDA fp16 / CPU, local_files_only=True)
        │  + Анти-галлюцинационный детектор и двуязычный рескоринг KK / RU
        │  + Калиброванная уверенность по softmax-логитам токенов
        ▼
[Contextual Repair + Spatial NER + XAI — backend/nlp_engine.py]
        │  Опц. локальный LLM (LM Studio/Ollama на localhost) + доменная радио-коррекция
        │  + Пословный Diff (сырой ASR → исправленный текст)
        │  + Извлечение: позывные, класс, P1–P4, квадрат/ориентир, этаж, кол-во, высота, курс
        │  + Сверка с датчиками (CAM / SCADA / IoT) + XAI-факторы
        ▼
[Responsible AI Gate — backend/compliance.py & backend/audit.py]
        │  Закон РК № 230-VIII: ст. 17–19 (Высокий риск + строгий HITL), ст. 21 (JSON-LD)
        │  SQLite WAL + SHA-256 Hash Chain (неизменяемый криптографический журнал)
        │  Маскирование ПДн (ИИН, телефоны, госномера, ФИО — Закон РК № 94-V)
        ▼
[Real-Time Broadcast & Interoperability — backend/app.py & backend/exporters.py]
        ├── WebSocket /ws → 3D Оперативная консоль (MapLibre GL + OSRM + 3D-объект)
        ├── TAK / CoT 2.0 XML (интеграция с ATAK / ЦОУ / ГИС)
        ├── GeoJSON + JSON-LD Provenance
        ├── Отчёт смены Markdown (ст. 21 + ПДн-редакция + SHA-256 Head)
        └── Опц. Telegram Bot P1 Alert (или air-gapped dry-run)
```

## Основные API-эндпоинты

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/health` | Статус GPU/CPU, локального Whisper, локального LLM и цепи SHA-256 |
| `GET` | `/api/state` | Полный снимок оперативной обстановки, HITL-очереди и compliance-паспорта |
| `POST` | `/api/scenarios/{id}/activate` | Переключение сценария (`astana_expo` / `almaty_zenkova`) |
| `POST` | `/api/scenarios/{id}/clip/{cid}` | Живое распознавание радиозаписи через локальный Whisper GPU |
| `POST` | `/api/ingest/audio` | Приём живого микрофона (PTT) или WAV/MP3 файла (с опц. радиофильтром) |
| `POST` | `/api/ingest/text` | Текстовый ввод радиодоклада (kk/ru) |
| `POST` | `/api/recommendations/{id}/decide` | Обязательное решение оператора HITL (`APPROVED` / `REJECTED`) |
| `POST` | `/api/benchmark/run` | Живой прогон WER/CER + latency + RTF бенчмарка на локальном Whisper |
| `GET` | `/api/audit/verify` | Полная криптографическая верификация SHA-256 цепи в SQLite |
| `POST` | `/api/compliance/redact-preview` | Живая проверка маскирования казахстанских ПДн (ИИН, тел., госномера) |
| `GET` | `/api/export/report.md` | Официальный отчёт смены с двойной маркировкой ст. 21 и ПДн-редакцией |
| `GET` | `/api/export/cot.xml` | Экспорт обстановки и подразделений в стандарт TAK / CoT 2.0 XML |
| `GET` | `/api/export/geojson` | Экспорт ГИС-слоя GeoJSON с JSON-LD provenance |
| `WS` | `/ws` | Поток событий в реальном времени для синхронизации пультов |
