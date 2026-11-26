# QYRAN 2.0

Система перевода голосовой радиосвязи на казахском и русском языках в оперативную 3D-карту для служб ЧС/112, ситуационных центров и объектов критической инфраструктуры. Работает полностью локально (on-premise), без отправки данных во внешние облачные сервисы.

![QYRAN Cover](assets/cover-1920x1080.png)

[![Live Demo](https://img.shields.io/badge/Web%20Demo-GitHub%20Pages-ef4444)](https://overloooooord.github.io/qyran/)
[![Pitch IT FEST 2026](https://img.shields.io/badge/Pitch%20Deck-IT%20FEST%202026-38bdf8)](https://overloooooord.github.io/qyran/demo/pitch-itfest2026.html)
[![Stack](https://img.shields.io/badge/Backend-FastAPI%20%2B%20WebSocket%20%2B%20SQLite-0ea5e9)]()
[![ASR](https://img.shields.io/badge/ASR-Local%20Whisper%20(GPU%2FCPU)-22c55e)]()
[![Law](https://img.shields.io/badge/Law-KZ%20No.%20230--VIII-f59e0b)]()

## Ссылки и материалы (IT FEST 2026)

- Локальный full-stack сервер (Whisper GPU/CPU + OSRM + аудит): `./run.sh` -> `http://localhost:8000` (презентация: `http://localhost:8000/pitch`)
- Веб-презентация IT FEST 2026: [overloooooord.github.io/qyran/demo/pitch-itfest2026.html](https://overloooooord.github.io/qyran/demo/pitch-itfest2026.html)
- Статическое веб-демо (без установки бэкенда): [overloooooord.github.io/qyran](https://overloooooord.github.io/qyran/) · [Живой микрофон](https://overloooooord.github.io/qyran/demo/live.html) · [Руководство RU/KZ](https://overloooooord.github.io/qyran/demo/manual.html)
- Документация: [`docs/QYRAN_ITFEST2026_Pitch.pdf`](docs/QYRAN_ITFEST2026_Pitch.pdf) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/RESPONSIBLE_AI_KZ_230.md`](docs/RESPONSIBLE_AI_KZ_230.md) · [`docs/FINALIST_PITCH_SCRIPT.md`](docs/FINALIST_PITCH_SCRIPT.md)

---

## Что реализовано в MVP

1. **Локальное распознавание речи (`backend/asr_engine.py`)**
   - Используется `openai/whisper-large-v3-turbo` локально на GPU (`CUDA fp16`, в среднем 0.4-0.9 с на 10-секундный фрагмент) с автоматическим переключением на CPU.
   - Автоматическое определение языка (`kk` / `ru`) без ручного переключения (100% на 18 тестовых клипах).
   - Фильтр галлюцинаций Whisper на шумном радиоканале с повторным прогоном по двум языкам (`kk`/`ru`).

2. **Исправление радиоискажений и извлечение сущностей (`backend/nlp_engine.py`)**
   - Восстановление слов, искаженных узкой полосой рации 300-3400 Гц (позывные, номера квадратов, термины ЧС: `дұром -> дрон`, `дом на крыше -> дым на крыше`, `қосшаңыз -> қоршаңыз`, `мүрт оқшауыланды -> өрт оқшауланды`) с подсветкой изменений в интерфейсе.
   - Опциональное подключение локальной LLM через LM Studio или Ollama (`QYRAN_LLM_URL=http://localhost:1234/v1`). Внешние облачные адреса заблокированы.
   - Извлечение адреса/квадрата, координат, этажа, высоты, направления, числа пострадавших, приоритета (`P1-P4`), проверка по датчикам и вывод пояснений (XAI).

3. **Соответствие Закону РК № 230-VIII «Об искусственном интеллекте» (`backend/compliance.py`, `backend/audit.py`)**
   - Классификация системы как высокорисковой (ст. 17-19: реагирование на ЧС и критическая инфраструктура).
   - Обязательное подтверждение оператором (Human-in-the-Loop, ст. 19): критические рекомендации P1/P2 не выполняются автоматически, требуется явное подтверждение или отклонение.
   - Двойная маркировка (ст. 21): пометка в интерфейсе и машиночитаемый блок `kz_ai_law_provenance` (JSON-LD + SHA-256) в отчетах, GeoJSON и CoT XML.
   - Неизменяемый журнал аудита в SQLite на основе хеш-цепи SHA-256 с проверкой целостности и изолированным тестом на подмену записи.
   - Автоматическое маскирование персональных данных при экспорте отчетов (ИИН, номера телефонов `+7 7XX`, госномера, email, ФИО по Закону РК № 94-V).

4. **Два сценария, живой микрофон, маршруты OSRM и аналитика (`backend/scenarios.py`, `backend/routing.py`, `backend/vision_engine.py`, `backend/copilot.py`)**
   - **Астана (МВЦ EXPO / ЧС-112):** 8 радиозаписей `a01.wav-a08.wav`, 18 ориентиров города, маршруты OSRM, 3-этажная схема павильона C2.
   - **Алматы (Зенкова 24):** 10 радиозаписей `t01.wav-t10.wav`, 14 ориентиров, маршруты OSRM, 5-этажная схема здания.
   - Поддержка записи с микрофона (PTT), загрузки аудиофайлов, имитации радиофильтра 300-3400 Гц, стресс-теста параллельной подачи 5 докладов, локального анализа кадров на огонь/дым (`PIL + NumPy`), текстовых запросов к оперативной базе (Co-Pilot) и экспорта в PDF/печать, Markdown, TAK/CoT XML, GeoJSON и JSON-аудит.
   - Библиотека `maplibre-gl` сохранена локально в `frontend/vendor/`, при отсутствии сети карта автоматически переходит в офлайн-режим.

---

## Замеры точности и скорости (RTX 4050 GPU, локально)

Метрики получены встроенным скриптом `backend/benchmark.py` (доступен в интерфейсе на вкладке `WER`):

| Сценарий | Клипов | Авто-язык | Перехвачено срывов ASR | WER сырой Whisper | WER после коррекции | Снижение WER | CER | Скорость |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Астана · МВЦ EXPO** | 8 (`75% kk / 25% ru`) | **100.0%** | 2 (`a02`, `a07`) | `28.2%` | **`3.1%`** | **`-89.0%`** | `6.1% -> 0.6%` | `11-16x RT` |
| **Алматы · Зенкова 24** | 10 (`90% kk / 10% ru`) | **100.0%** | 0 | `28.7%` | **`3.9%`** | **`-86.4%`** | `7.7% -> 1.1%` | `10-18x RT` |

---

## Запуск локально

```bash
cd /home/caterinw/Downloads/qyran
./run.sh
```

Открыть в браузере: `http://localhost:8000` (презентация: `http://localhost:8000/pitch`).

### Проверка автотестами

```bash
python3 -m unittest discover -s tests -v
```

### Основные переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `PORT` | `8000` | Порт HTTP/WebSocket сервера |
| `QYRAN_WHISPER_MODEL` | `openai/whisper-large-v3-turbo` | Идентификатор локальной модели Whisper |
| `QYRAN_LOCAL_ONLY` | `1` | Работа только из локального кэша (`local_files_only=True`) |
| `QYRAN_LLM_URL` | `http://localhost:1234/v1` | Адрес локальной LLM (LM Studio / Ollama) |
| `QYRAN_TG_BOT_TOKEN` / `QYRAN_TG_CHAT_ID` | *(пусто)* | Отправка P1-уведомлений в Telegram (без токена работает dry-run) |

---

## Структура репозитория

```text
qyran/
├── run.sh                              # Запуск сервера
├── requirements.txt                    # Зависимости Python
├── backend/
│   ├── app.py                          # FastAPI REST + WebSocket сервер
│   ├── asr_engine.py                   # Локальный Whisper + фильтр галлюцинаций
│   ├── audio_dsp.py                    # Декодирование 16 kHz, фильтр 300-3400 Гц, SNR
│   ├── nlp_engine.py                   # Коррекция текста, извлечение сущностей, XAI
│   ├── routing.py                      # Подбор ближайшего экипажа и маршрутизация OSRM
│   ├── vision_engine.py                # Локальный анализ кадров на очаг огня и дым
│   ├── copilot.py                      # Ответы по текущему состоянию сессии с ссылками на ID
│   ├── compliance.py                   # Проверки по Закону РК № 230-VIII и маскирование ПДн
│   ├── audit.py                        # SQLite WAL + хеш-цепь SHA-256
│   ├── exporters.py                    # Экспорт: PDF/HTML, Markdown, TAK/CoT XML, GeoJSON
│   ├── benchmark.py                    # Замер WER/CER и задержки на WAV-датасетах
│   ├── scenarios.py                    # Конфигурация сценариев Астаны и Алматы
│   └── state.py                        # Оперативное состояние, задачи и очередь HITL
├── frontend/
│   ├── index.html                      # Веб-консоль оператора
│   ├── pitch.html                      # Интерактивная презентация (8 слайдов)
│   ├── styles.css                      # Стили интерфейса
│   ├── app.js                          # Логика карты, микрофона, WebSocket и вкладок
│   └── vendor/                         # Локальные копии maplibre-gl.js и maplibre-gl.css
├── data/scenarios/
│   ├── astana_expo/                    # a01.wav..a08.wav + routes.json + transcripts.txt
│   └── almaty_zenkova/                 # t01.wav..t10.wav + routes.json + transcripts.txt
├── docs/
│   ├── QYRAN_ITFEST2026_Pitch.pdf      # Презентация PDF (16:9)
│   ├── ARCHITECTURE.md                 # Описание архитектуры и API
│   ├── RESPONSIBLE_AI_KZ_230.md        # Соответствие Закону РК № 230-VIII
│   └── FINALIST_PITCH_SCRIPT.md        # План выступления и ответы на вопросы жюри
└── tests/
    └── test_qyran_mvp.py               # Набор модульных и интеграционных тестов
```

## Команда

- **Ералы Абуталифулы** (ML Engineer, Backend, Project Lead)
- **Аделия** (ML Engineer, Backend, Data Visualization)

## Лицензия

[MIT](LICENSE)
