"""Парсер сообщений о продажах."""

import re
from config import KASPI_RECIPIENTS, PAYMENT_CASH, PAYMENT_KASPI


def parse_payment_code(code: str) -> tuple[str, str]:
    """Определяет тип оплаты и получателя.

    Returns:
        (тип_оплаты, получатель)
    """
    code_lower = code.lower().strip()

    if code_lower in ("нал", "наличные", "н"):
        return PAYMENT_CASH, ""

    # Сначала проверяем длинные коды (ра, ип), потом короткие (р, к, д)
    for key in sorted(KASPI_RECIPIENTS.keys(), key=len, reverse=True):
        if code_lower == key:
            return PAYMENT_KASPI, KASPI_RECIPIENTS[key]

    return PAYMENT_KASPI, code  # неизвестный код — сохраняем как есть


def parse_sale_message(text: str) -> list[dict] | None:
    """Парсит одно или несколько сообщений о продаже.

    Формат строки: <товар> <кол-во> * <цена> <оплата>
    Примеры:
        Note 9s 1 * 9500 нал
        11 Pro GX original 1 * 11 000 K
        A54 2 * 8000 Д

    Returns:
        Список словарей с полями: product, qty, price, payment_type, recipient
        или None если не удалось распарсить.
    """
    results = []

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        parsed = _parse_single_line(line)
        if parsed:
            results.append(parsed)

    return results if results else None


def _parse_single_line(line: str) -> dict | None:
    """Парсит одну строку продажи."""

    # Паттерн: <товар> <кол-во> * <цена> <оплата>
    # Цена может содержать пробелы (11 000)
    match = re.match(
        r'^(.+?)\s+(\d+)\s*\*\s*([\d\s]+?)\s+([a-zA-Zа-яА-ЯёЁ]+)$',
        line
    )

    if not match:
        # Попробуем без * : <товар> <кол-во> <цена> <оплата>
        match = re.match(
            r'^(.+?)\s+(\d+)\s+([\d\s]+?)\s+([a-zA-Zа-яА-ЯёЁ]+)$',
            line
        )

    if not match:
        return None

    product = match.group(1).strip()
    qty = int(match.group(2))
    price_str = match.group(3).replace(" ", "")
    payment_code = match.group(4)

    try:
        price = int(price_str)
    except ValueError:
        return None

    payment_type, recipient = parse_payment_code(payment_code)

    return {
        "product": product,
        "qty": qty,
        "price": price,
        "total": qty * price,
        "payment_type": payment_type,
        "recipient": recipient,
    }
