"""Получение текущей погоды по городам из файла через wttr.in и вывод сводки."""

import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

INPUT_FILE = "Cities.txt"
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3
RETRY_DELAY = 1.0
MAX_WORKERS = 8
USER_AGENT = "curl/8.0"


@dataclass
class WeatherData:
    """Снимок погоды по одному городу."""

    city: str
    temp_c: int
    country: str


def load_cities(path: str) -> List[str]:
    """Читает города из файла в кодировке UTF-8.

    Убирает пробелы по краям и пустые строки; дубликаты определяет
    без учёта регистра; сохраняет порядок первого появления.

    Args:
        path: Путь к файлу со списком городов.

    Returns:
        Список уникальных городов в порядке появления.
    """
    cities: List[str] = []
    seen = set()
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            city = line.strip()
            if not city:
                continue
            key = city.casefold()
            if key not in seen:
                seen.add(key)
                cities.append(city)
    return cities


def fetch_weather(city: str) -> WeatherData:
    """Запрашивает погоду для города через wttr.in (format=j1).

    Повторяет запрос до MAX_RETRIES раз с паузой при сетевой ошибке.

    Args:
        city: Название города из исходного списка.

    Returns:
        Объект WeatherData с городом, температурой (°C) и страной.

    Raises:
        RuntimeError: Если все попытки запроса завершились ошибкой.
    """
    url = f"https://wttr.in/{quote(city)}?format=j1"
    last_exc: Optional[BaseException] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return WeatherData(
                city=city,
                temp_c=int(data["current_condition"][0]["temp_C"]),
                country=str(data["nearest_area"][0]["country"][0]["value"]),
            )
        except HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}") from e
        except (URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    raise RuntimeError(f"{type(last_exc).__name__}: {last_exc}")


def fetch_weather_safe(city: str) -> Optional[WeatherData]:
    """Безопасно получает погоду для одного города.

    Args:
        city: Название города из исходного списка.

    Returns:
        Объект WeatherData при успехе, иначе None.
    """
    try:
        return fetch_weather(city)
    except Exception as e:
        print(f"{city}: error ({e})", file=sys.stderr)
        return None


def group_by_country(rows: List[WeatherData]) -> Dict[str, List[WeatherData]]:
    """Группирует данные о погоде по странам.

    Args:
        rows: Список объектов WeatherData.

    Returns:
        Словарь: страна -> список объектов WeatherData этой страны.
    """
    groups: Dict[str, List[WeatherData]] = defaultdict(list)
    for row in rows:
        groups[row.country].append(row)
    return dict(groups)


def format_temp(temp_c: int) -> str:
    """Форматирует температуру с обязательным знаком.

    Args:
        temp_c: Температура в градусах Цельсия.

    Returns:
        Строка вида '+18', '-5' или '+0'.
    """
    return f"+{temp_c}" if temp_c >= 0 else str(temp_c)


def main() -> int:
    """Точка входа: читает города, параллельно получает погоду, печатает сводку.

    Города с ошибкой запроса выводятся в stderr и не попадают в статистику.

    Returns:
        Код завершения: 0 при успехе, 1 при ошибке чтения файла.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    try:
        cities = load_cities(INPUT_FILE)
    except OSError as e:
        print(f"Failed to read {INPUT_FILE}: {e}", file=sys.stderr)
        return 1
    if not cities:
        print(f"No cities found in {INPUT_FILE}", file=sys.stderr)
        return 1

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(fetch_weather_safe, cities))

    rows: List[WeatherData] = [r for r in results if r is not None]

    print("=== Weather by city ===")
    for row in rows:
        print(f"{row.city}, {row.country} {format_temp(row.temp_c)} °C")

    print("\n=== Summary by country ===")
    groups = group_by_country(rows)
    for country in sorted(groups):
        group = groups[country]
        temps = [row.temp_c for row in group]
        count = len(group)
        noun = "city" if count == 1 else "cities"
        avg = round(sum(temps) / count)
        print(
            f"{country} — {count} {noun}, avg: {format_temp(avg)} °C, "
            f"min: {format_temp(min(temps))} °C, max: {format_temp(max(temps))} °C"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
