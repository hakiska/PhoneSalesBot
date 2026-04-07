"""Каталог товаров — сопоставление коротких названий с полными для 1С."""

import json
import re
from pathlib import Path

from openpyxl import load_workbook

CATALOG_FILE = "catalog.json"


def load_catalog() -> dict[str, str]:
    """Загружает сохранённые маппинги short_name -> full_name."""
    path = Path(CATALOG_FILE)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_catalog(catalog: dict[str, str]):
    """Сохраняет маппинги."""
    Path(CATALOG_FILE).write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def load_products_from_excel(filepath: str) -> list[str]:
    """Загружает список полных названий из Excel (колонка B)."""
    wb = load_workbook(filepath, read_only=True)
    ws = wb.active
    products = []
    for row in range(2, ws.max_row + 1):
        val = ws.cell(row=row, column=2).value
        if val and isinstance(val, str) and val.strip():
            products.append(val.strip())
    wb.close()
    return products


def load_products_from_json(filepath: str = "products.json") -> list[str]:
    """Загружает список полных названий из JSON-файла."""
    path = Path(filepath)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def _normalize(text: str) -> str:
    """Приводит текст к нижнему регистру, убирает лишние пробелы."""
    return re.sub(r'\s+', ' ', text.lower().strip())


def find_product(short_name: str, products: list[str], catalog: dict[str, str]) -> list[str]:
    """Ищет товар по короткому названию.

    1. Сначала проверяет сохранённые маппинги (точное совпадение)
    2. Потом ищет по вхождению в полные названия

    Returns:
        Список подходящих полных названий (может быть 0, 1 или несколько).
    """
    key = _normalize(short_name)

    # Точное совпадение в каталоге
    if key in catalog:
        return [catalog[key]]

    # Поиск по вхождению ключевых слов
    matches = []
    for product in products:
        norm_product = _normalize(product)
        # Проверяем что все слова short_name входят в название товара
        words = key.split()
        if all(w in norm_product for w in words):
            matches.append(product)

    # Если одно совпадение — сохраняем в каталог автоматически
    if len(matches) == 1:
        catalog[key] = matches[0]
        save_catalog(catalog)

    return matches


def add_mapping(short_name: str, full_name: str, catalog: dict[str, str]):
    """Вручную добавляет маппинг."""
    key = _normalize(short_name)
    catalog[key] = full_name
    save_catalog(catalog)
