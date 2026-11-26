"""Operational Scenarios Registry: Astana EXPO 2026 (Default) & Almaty Zenkova 24."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import SCENARIOS_DIR


def _load_routes(scenario_id: str) -> dict[str, Any]:
    path = SCENARIOS_DIR / scenario_id / "routes.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def parse_ground_truth(scenario_id: str) -> dict[str, dict[str, str]]:
    """Parse transcripts.txt ground truth entries for live WER/CER benchmarking."""
    path = SCENARIOS_DIR / scenario_id / "transcripts.txt"
    if not path.exists():
        return {}
    entries: dict[str, dict[str, str]] = {}
    current_id: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\w+)\.wav\s*\|\s*([\d:]+)\s*\|\s*(.+?)\s*->\s*(.+?)\s*\|\s*(kk|ru)", line.strip())
        if m:
            current_id = m.group(1)
            entries[current_id] = {
                "id": current_id,
                "time": m.group(2),
                "from": m.group(3).strip(),
                "to": m.group(4).strip(),
                "lang": m.group(5).strip(),
                "reference": "",
            }
        elif current_id and "эталон:" in line:
            entries[current_id]["reference"] = line.split("эталон:", 1)[1].strip()
    return entries


def build_scenarios() -> dict[str, dict[str, Any]]:
    astana_routes = _load_routes("astana_expo")
    almaty_routes = _load_routes("almaty_zenkova")
    astana_gt = parse_ground_truth("astana_expo")
    almaty_gt = parse_ground_truth("almaty_zenkova")

    return {
        "astana_expo": {
            "id": "astana_expo",
            "badge": "IT FEST 2026 · ASTANA EXPO · МЧС / 112",
            "title_ru": "Астана · МВЦ EXPO / Нұр-Әлем · ЧС-112 и критическая инфраструктура",
            "title_kk": "Астана · EXPO ХКО / Нұр-Әлем · ТЖ-112 және сыни инфрақұрылым",
            "subtitle_ru": "Гражданская безопасность, реагирование МЧС/112 и защита объектов EXPO",
            "subtitle_kk": "Азаматтық қауіпсіздік, ТЖМ/112 әрекет ету және EXPO нысандарын қорғау",
            "center": [71.4180, 51.0902],
            "zoom": 14.1,
            "pitch": 48,
            "bearing": -18,
            "start_time": "14:10:00",
            "grid": {
                "lon0": 71.388,
                "lat1": 51.106,
                "dlon": 0.015,
                "dlat": 0.010,
                "cols": 4,
                "rows": 3,
            },
            "places": {
                "expo_c2": {
                    "label": "МВЦ EXPO · Павильон C2 / Нұр-Әлем",
                    "coords": [71.4180, 51.0902],
                    "keys": ["экспо", "expo", "нұр әлем", "нур алем", "сфера", "павильон", "с 2", "с2", "с-2", "сиекі", "с екі"],
                },
                "expo_south": {
                    "label": "Южный вход МВЦ EXPO",
                    "coords": [71.4165, 51.0875],
                    "keys": ["южный вход", "южного входа", "оңтүстік есік", "южного выхода", "оңтүстік кіреберіс"],
                },
                "mega_silk_way": {
                    "label": "ТРЦ MEGA Silk Way",
                    "coords": [71.4075, 51.0888],
                    "keys": ["мега силк", "mega silk", "мегасилк", "силк вей", "силк вэй", "мега"],
                },
                "substation_lb": {
                    "label": "Подстанция «Левобережье» (110 кВ)",
                    "coords": [71.4010, 51.0940],
                    "keys": ["подстанц", "левобереж", "энергоузел", "қосалқы станция", "тэц"],
                },
                "mangilik_el": {
                    "label": "Пр. Мәңгілік Ел",
                    "coords": [71.4255, 51.0955],
                    "keys": ["мангилик", "мәңгілік ел", "улы дала", "ұлы дала"],
                },
                "nu_campus": {
                    "label": "Назарбаев Университет",
                    "coords": [71.3980, 51.0906],
                    "keys": ["назарбаев", "университет", "кабанбай"],
                },
                "baiterek": {
                    "label": "Монумент Байтерек",
                    "coords": [71.4305, 51.1283],
                    "keys": ["байтерек", "бәйтерек"],
                },
                "akorda": {
                    "label": "Акорда / Дом Министерств",
                    "coords": [71.4462, 51.1257],
                    "keys": ["акорда", "ақорда", "министерств"],
                },
                "khan_shatyr": {
                    "label": "ТРЦ Хан Шатыр",
                    "coords": [71.4038, 51.1325],
                    "keys": ["хан шатыр", "ханшатыр"],
                },
                "astana_arena": {
                    "label": "Стадион Астана Арена",
                    "coords": [71.4024, 51.1082],
                    "keys": ["астана арена", "стадион", "барыс арена"],
                },
                "botanical_garden": {
                    "label": "Ботанический сад Астаны",
                    "coords": [71.4125, 51.1060],
                    "keys": ["ботаническ", "ботаникалық"],
                },
                "triumph_arch": {
                    "label": "Триумфальная арка Мәңгілік Ел",
                    "coords": [71.4301, 51.1024],
                    "keys": ["триумфальн", "арка"],
                },
                "airport_nqz": {
                    "label": "Аэропорт Нурсултан Назарбаев (NQZ)",
                    "coords": [71.4669, 51.0222],
                    "keys": ["аэропорт", "әуежай", "аэродром"],
                },
                "nurly_zhol": {
                    "label": "ЖД Вокзал Нұрлы Жол",
                    "coords": [71.5318, 51.1117],
                    "keys": ["нұрлы жол", "нурлы жол", "вокзал"],
                },
                "tec2_astana": {
                    "label": "ТЭЦ-2 Астана",
                    "coords": [71.4820, 51.1745],
                    "keys": ["тэц 2", "тэц-2", "тэц"],
                },
                "hospital_udp": {
                    "label": "Больница МЦ УДП / Госпиталь",
                    "coords": [71.4192, 51.0762],
                    "keys": ["больниц", "аурухана", "госпитал"],
                },
                "sq7": {
                    "label": "Квадрат 7 (Восточный сектор EXPO)",
                    "coords": [71.4280, 51.0910],
                    "keys": [],
                },
                "sq8": {
                    "label": "Квадрат 8 (Зона посадки БПЛА)",
                    "coords": [71.4385, 51.0935],
                    "keys": [],
                },
            },
            "routes": astana_routes,
            "units": {
                "Өрт-2": {
                    "role": "Пожарный расчёт ДЧС-101",
                    "cls": "fire",
                    "pos": astana_routes.get("fire2", {}).get("coords", [[71.4045, 51.0840]])[0],
                    "route": "fire2",
                    "status": "дежурство",
                    "battery": 96,
                    "crew": 6,
                },
                "Патруль-4": {
                    "role": "Полиция 102 / Кордон",
                    "cls": "pol",
                    "pos": astana_routes.get("pol4", {}).get("coords", [[71.4255, 51.0955]])[0],
                    "route": "pol4",
                    "status": "патруль",
                    "battery": 91,
                    "crew": 4,
                },
                "Жедел-103": {
                    "role": "Бригада СМП-103",
                    "cls": "med",
                    "pos": astana_routes.get("amb103", {}).get("coords", [[71.3990, 51.0975]])[0],
                    "route": "amb103",
                    "status": "готовность",
                    "battery": 98,
                    "crew": 3,
                },
                "Энерго-7": {
                    "role": "Аварийная бригада Астана-РЭК",
                    "cls": "grid",
                    "pos": astana_routes.get("grid7", {}).get("coords", [[71.4240, 51.0835]])[0],
                    "route": "grid7",
                    "status": "дежурство",
                    "battery": 89,
                    "crew": 4,
                },
                "Қыран-1": {
                    "role": "Пост мониторинга воздуха / БПЛА",
                    "cls": "own",
                    "pos": [71.4290, 51.0920],
                    "route": "uav1",
                    "status": "наблюдение",
                    "battery": 84,
                    "crew": 2,
                },
                "Бекет-3": {
                    "role": "Мобильный пост EXPO",
                    "cls": "own",
                    "pos": [71.4110, 51.0885],
                    "route": None,
                    "status": "наблюдение",
                    "battery": 79,
                    "crew": 2,
                },
            },
            "callsigns": [
                "Орталық-112", "Центр", "Қыран-1", "Өрт-2", "Патруль-4",
                "Техник-7", "Бекет-3", "Жедел-103", "Энерго-7",
            ],
            "building": {
                "name": "МВЦ EXPO · Павильон C2",
                "floors": 3,
                "hot_floor": 2,
                "evac_floor": 2,
                "initial_people": 45,
                "sensors": ["Термокамера C2-2F", "Датчик дыма IoT-04", "Счётчик потока Юг"],
            },
            "sensors_catalog": {
                "drone": ("ok", "Радар + Камера CAM-04 (Сфера EXPO)"),
                "fire_smoke": ("ok", "Датчик дыма IoT-04 + Термокамера C2-2F"),
                "crowd": ("ok", "CAM-02 Южный вход (~118 чел. по CV)"),
                "infrastructure": ("ok", "SCADA Подстанция-110кВ (скачок 14.2%)"),
                "casualties": ("unverified", None),
                "evacuated": ("ok", "Счётчик турникетов Южный выход (45 чел.)"),
                "neutralized": ("ok", "CAM-04 + Телеметрия БПЛА (посадка кв.8)"),
            },
            "clips": [
                {
                    "id": cid,
                    "filename": f"{cid}.wav",
                    "time": astana_gt.get(cid, {}).get("time", "14:10:00"),
                    "from": astana_gt.get(cid, {}).get("from", "Борт"),
                    "to": astana_gt.get(cid, {}).get("to", "Орталық-112"),
                    "lang": astana_gt.get(cid, {}).get("lang", "kk"),
                    "reference": astana_gt.get(cid, {}).get("reference", ""),
                }
                for cid in ["a01", "a02", "a03", "a04", "a05", "a06", "a07", "a08"]
            ],
            "sample_commands": [
                "Квадрат 7, рұқсатсыз дрон, биіктігі 200 метр, ЭКСПО сферасына қарай",
                "ЭКСПО павильон С2, 2 этаж, сильное задымление электрощита, нужна 101",
                "На подстанции Левобережье утечка хладагента и скачок напряжения",
                "Мега Силк Вэй маңында 2 адам зардап шекті, жедел жәрдем 103 керек",
                "Дрон в квадрате 8 безопасно посажен, пожар локализован",
            ],
        },
        "almaty_zenkova": {
            "id": "almaty_zenkova",
            "badge": "ALMATY BENCHMARK · ЗЕНКОВА 24 · 10 CLIPS",
            "title_ru": "Алматы · Зенкова 24 · Межведомственный радиоэфир (10 клипов)",
            "title_kk": "Алматы · Зенков 24 · Ведомствоаралық радиоэфир (10 клип)",
            "subtitle_ru": "Исторический бенчмарк на 10 радиозаписях kk/ru (90% казахский язык)",
            "subtitle_kk": "10 kk/ru радиожазбадағы тарихи бенчмарк (90% қазақ тілі)",
            "center": [76.9600, 43.2605],
            "zoom": 13.7,
            "pitch": 42,
            "bearing": -15,
            "start_time": "18:42:00",
            "grid": {
                "lon0": 76.930,
                "lat1": 43.275,
                "dlon": 0.015,
                "dlat": 0.010,
                "cols": 4,
                "rows": 3,
            },
            "places": {
                "zenkova24": {
                    "label": "ул. Зенкова, 24",
                    "coords": [76.9572729, 43.2591339],
                    "keys": ["зенков", "ғимарат", "здани", "крыш", "шатыр"],
                },
                "kokbazar": {
                    "label": "Көк базар (Зелёный базар)",
                    "coords": [76.9551971, 43.2636756],
                    "keys": ["көк базар", "кок базар", "зеленый базар", "зелёный базар"],
                },
                "zhibekzholy": {
                    "label": "Пр. Жібек Жолы",
                    "coords": [76.9440, 43.2617],
                    "keys": ["жібек жолы", "жибек жолы"],
                },
                "kbtu": {
                    "label": "КБТУ / ул. Толе би",
                    "coords": [76.9440, 43.2555],
                    "keys": ["кбту", "толе би"],
                },
                "koktobe": {
                    "label": "Кок-Тобе",
                    "coords": [76.9765, 43.2330],
                    "keys": ["кок тобе", "көктөбе", "коктобе"],
                },
                "republic_sq": {
                    "label": "Площадь Республики",
                    "coords": [76.9455, 43.2385],
                    "keys": ["площадь республик", "республик"],
                },
                "esentai": {
                    "label": "Esentai Mall",
                    "coords": [76.9275, 43.2180],
                    "keys": ["есентай", "esentai"],
                },
                "airport_ala": {
                    "label": "Аэропорт Алматы (ALA)",
                    "coords": [77.0405, 43.3520],
                    "keys": ["аэропорт", "әуежай"],
                },
                "medeu": {
                    "label": "Медеу",
                    "coords": [77.0590, 43.1575],
                    "keys": ["медеу"],
                },
                "tec_ala": {
                    "label": "ТЭЦ-2 Алматы",
                    "coords": [76.8450, 43.3000],
                    "keys": ["тэц", "электростанц"],
                },
                "mega_ala": {
                    "label": "MEGA Alma-Ata",
                    "coords": [76.9280, 43.2025],
                    "keys": ["мега"],
                },
                "sq7": {
                    "label": "Квадрат 7",
                    "coords": [76.9675, 43.2575],
                    "keys": [],
                },
                "sq8": {
                    "label": "Квадрат 8",
                    "coords": [76.9810, 43.2605],
                    "keys": [],
                },
            },
            "routes": almaty_routes,
            "units": {
                "Барыс-1": {
                    "role": "Оперативная группа",
                    "cls": "own",
                    "pos": almaty_routes.get("bar1", {}).get("coords", [[76.9505, 43.2530]])[0],
                    "route": "bar1",
                    "status": "патруль",
                    "battery": 92,
                    "crew": 6,
                },
                "Арлан-3": {
                    "role": "Резервная группа",
                    "cls": "own",
                    "pos": almaty_routes.get("arl3", {}).get("coords", [[76.9640, 43.2561]])[0],
                    "route": "arl3",
                    "status": "резерв",
                    "battery": 88,
                    "crew": 8,
                },
                "Бүркіт-1": {
                    "role": "Пост наблюдения",
                    "cls": "own",
                    "pos": [76.9505, 43.2650],
                    "route": None,
                    "status": "наблюдение",
                    "battery": 74,
                    "crew": 2,
                },
                "Бүркіт-2": {
                    "role": "Пост мониторинга БПЛА",
                    "cls": "own",
                    "pos": [76.9720, 43.2650],
                    "route": None,
                    "status": "наблюдение",
                    "battery": 81,
                    "crew": 3,
                },
                "Полиция-5": {
                    "role": "Полиция 102",
                    "cls": "pol",
                    "pos": almaty_routes.get("pol5", {}).get("coords", [[76.9620, 43.2699]])[0],
                    "route": "pol5",
                    "status": "дежурство",
                    "battery": 95,
                    "crew": 4,
                },
                "Скорая-12": {
                    "role": "Бригада СМП-103",
                    "cls": "med",
                    "pos": almaty_routes.get("amb12", {}).get("coords", [[76.9600, 43.2531]])[0],
                    "route": "amb12",
                    "status": "готовность",
                    "battery": 97,
                    "crew": 3,
                },
                "Сапёры-2": {
                    "role": "Инженерно-технический расчёт",
                    "cls": "grid",
                    "pos": almaty_routes.get("sap2", {}).get("coords", [[76.9416, 43.2540]])[0],
                    "route": "sap2",
                    "status": "готовность",
                    "battery": 90,
                    "crew": 4,
                },
            },
            "callsigns": [
                "Сұңқар", "Бүркіт-1", "Бүркіт-2", "Барыс-1", "Арлан-3",
                "Полиция-5", "Скорая-12", "Сапёры-2",
            ],
            "building": {
                "name": "Алматы · ул. Зенкова, 24",
                "floors": 5,
                "hot_floor": 3,
                "evac_floor": 1,
                "initial_people": 12,
                "sensors": ["CAM-01 Вход", "CAM-04 Крыша", "Wi-Fi CSI ESP32 (3 этаж)"],
            },
            "sensors_catalog": {
                "drone": ("ok", "CAM-04 (небо) + Радиопеленг"),
                "armed": ("ok", "CAM-01 + Wi-Fi CSI 3 этаж"),
                "crowd": ("ok", "CAM-03 Көк базар"),
                "fire_smoke": ("ok", "CAM-04 (крыша СВ угол)"),
                "evacuated": ("ok", "Wi-Fi CSI: 1 этаж свободен"),
                "casualties": ("unverified", None),
                "neutralized": ("ok", "CAM-04 + Пост мониторинга БПЛА"),
            },
            "clips": [
                {
                    "id": cid,
                    "filename": f"{cid}.wav",
                    "time": almaty_gt.get(cid, {}).get("time", "18:42:00"),
                    "from": almaty_gt.get(cid, {}).get("from", "Бүркіт-1"),
                    "to": almaty_gt.get(cid, {}).get("to", "Сұңқар"),
                    "lang": almaty_gt.get(cid, {}).get("lang", "kk"),
                    "reference": almaty_gt.get(cid, {}).get("reference", ""),
                }
                for cid in [f"t{i:02d}" for i in range(1, 11)]
            ],
            "sample_commands": [
                "Жетінші шаршыда дрон байқадым, биіктігі 300 метр, солтүстікке қарай",
                "Зенков көшесі 24, үшінші қабатта екі күдікті адам бар",
                "Көк базар маңында шамамен 50 адам жиналды, полиция керек",
                "Вижу дым на крыше Зенкова 24, северо-восточный угол",
                "Жібек жолы даңғылы, 2 адам жараланды, жедел жәрдем шұғыл керек",
            ],
        },
    }
