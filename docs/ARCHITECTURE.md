# Архитектура QYRAN 2.0

```text
[Радиостанция / Микрофон PTT / Аудиофайл WAV, MP3]
        |  16 kHz mono (ffmpeg), опционально полосовой фильтр 300-3400 Гц (scipy Butterworth)
        v
[Обработка сигнала: backend/audio_dsp.py]
        |  Расчет SNR (дБ), RMS, доли речевой активности (VAD), огибающей сигнала
        v
[Локальное распознавание речи: backend/asr_engine.py]
        |  openai/whisper-large-v3-turbo (CUDA fp16 / CPU, local_files_only=True)
        |  + перехват галлюцинаций и повторная оценка по языкам kk / ru
        |  + оценка уверенности по вероятностям токенов (softmax)
        v
[Коррекция текста и пространственный разбор: backend/nlp_engine.py]
        |  Опционально локальная LLM (localhost) + правила ремонта радиоискажений
        |  + пословный diff (исходный ASR -> исправленный текст)
        |  + извлечение: позывные, тип, приоритет P1-P4, адрес/квадрат, этаж, кол-во, высота, курс
        |  + сверка с датчиками (CAM / SCADA / IoT) и пояснения (XAI)
        v
[Контроль и аудит: backend/compliance.py, backend/audit.py]
        |  Закон РК № 230-VIII: ст. 17-19 (высокий риск, HITL), ст. 21 (JSON-LD маркировка)
        |  SQLite WAL + хеш-цепь SHA-256 (контроль неизменяемости записей)
        |  Маскирование ПДн (ИИН, телефоны, госномера, ФИО по Закону РК № 94-V)
        v
[Передача данных и экспорт: backend/app.py, backend/exporters.py]
        |-- WebSocket /ws -> консоль оператора (MapLibre GL + OSRM + 3D-схема здания)
        |-- TAK / CoT 2.0 XML (совместимость с ATAK и ГИС-системами)
        |-- GeoJSON + метаданные JSON-LD
        |-- Отчет смены (PDF/печать HTML и Markdown с редакцией ПДн)
        +-- Telegram Bot API для P1-уведомлений (или локальный dry-run)
```

## Основные HTTP и WebSocket маршруты

| Метод | Маршрут | Назначение |
|---|---|---|
| `GET` | `/api/health` | Состояние GPU/CPU, загрузка Whisper, статус локальной LLM и цепи SHA-256 |
| `GET` | `/api/state` | Текущее состояние обстановки, очереди HITL, задач и проверок соответствия |
| `POST` | `/api/scenarios/{id}/activate` | Переключение активного сценария (`astana_expo` или `almaty_zenkova`) |
| `POST` | `/api/scenarios/{id}/clip/{cid}` | Прогон WAV-записи сценария через локальный Whisper и NLP |
| `POST` | `/api/scenarios/{id}/stress-burst` | Параллельная обработка 5 разноязычных докладов для стресс-теста |
| `POST` | `/api/ingest/audio` | Прием записи с микрофона (PTT) или загруженного аудиофайла |
| `POST` | `/api/ingest/text` | Обработка текстового доклада на казахском или русском языке |
| `POST` | `/api/ingest/image` | Локальный анализ кадра камеры на наличие очага огня и задымления |
| `POST` | `/api/copilot/ask` | Ответ по текущей оперативной обстановке со ссылками на ID событий |
| `POST` | `/api/recommendations/{id}/decide` | Решение оператора по рекомендации HITL (`APPROVED` или `REJECTED`) |
| `POST` | `/api/benchmark/run` | Запуск замера WER/CER, RTF и средней задержки по клипам сценария |
| `GET` | `/api/audit/verify` | Полная проверка криптографической цепи SHA-256 в SQLite |
| `POST` | `/api/audit/simulate-tamper` | Изолированная проверка обнаружения подмены записи в копии БД |
| `POST` | `/api/compliance/redact-preview` | Проверка алгоритма маскирования ПДн (ИИН, телефоны, госномера) |
| `GET` | `/api/export/report.html` | Версия отчета смены для печати и сохранения в PDF |
| `GET` | `/api/export/report.md` | Выгрузка отчета смены в Markdown с блоком JSON-LD |
| `GET` | `/api/export/cot.xml` | Выгрузка событий и подразделений в формате TAK / CoT 2.0 XML |
| `GET` | `/api/export/geojson` | Выгрузка слоя обстановки в формате GeoJSON |
| `WS` | `/ws` | Поток обновлений состояния в реальном времени |
