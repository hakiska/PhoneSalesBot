"""Парсер сообщений о продажах."""

import re
from config import KASPI_RECIPIENTS, PAYMENT_CASH, PAYMENT_KASPI

# Все допустимые коды оплаты (нижний регистр)
VALID_PAYMENT_CODES = {"нал", "наличные", "н"} | set(KASPI_RECIPIENTS.keys())


def has_cyrillic_in_model(text: str) -> bool:
    """Проверяет есть ли кириллица в названии модели."""
    for ch in text:
        if '\u0400' <= ch <= '\u04FF':
            return True
    return False


def parse_payment_code(code: str) -> tuple[str, str] | None:
    """Определяет тип оплаты и получателя.

    Returns:
        (тип_оплаты, получатель) или None если код невалидный.
    """
    code_lower = code.lower().strip()

    if code_lower in ("нал", "наличные", "н"):
        return PAYMENT_CASH, ""

    for key in sorted(KASPI_RECIPIENTS.keys(), key=len, reverse=True):
        if code_lower == key:
            return PAYMENT_KASPI, KASPI_RECIPIENTS[key]

    return None


def is_valid_payment(code: str) -> bool:
    """Проверяет является ли слово допустимым кодом оплаты."""
    return code.lower().strip() in VALID_PAYMENT_CODES


def parse_sale_message(text: str) -> list | dict | None:
    """Парсит одно или несколько сообщений о продаже.

    Форматы:
        A53 1*5000 нал Малик              — обычная продажа
        A53 1*5000 Малик Долг             — полный долг
        A53 1*5000 нал 3000 Малик Долг    — внёс 3000, долг 2000

    Returns:
        list[dict] — если всё ок
        dict с ключами errors/sales — если есть ошибки
        None — не удалось распарсить
    """
    results = []
    errors = []

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        parsed = _parse_single_line(line)
        if isinstance(parsed, str):
            errors.append(parsed)
        elif parsed:
            results.append(parsed)

    if errors:
        return {"errors": errors, "sales": results}

    return results if results else None


def _parse_single_line(line: str) -> dict | str | None:
    """Парсит одну строку продажи."""

    # Паттерн: <товар> <кол-во> * <цена> <остаток...>
    match = re.match(
        r'^(.+?)\s+(\d+)\s*\*\s*([\d\s]+?)\s+(.+)$',
        line
    )

    if not match:
        match = re.match(
            r'^(.+?)\s+(\d+)\s+([\d\s]+?)\s+(.+)$',
            line
        )

    if not match:
        return None

    product = match.group(1).strip()
    qty = int(match.group(2))
    price_str = match.group(3).replace(" ", "")
    tail = match.group(4).strip()

    try:
        price = int(price_str)
    except ValueError:
        return None

    # Проверяем кириллицу в названии модели
    if has_cyrillic_in_model(product):
        return f"Модель \"{product}\" написана кириллицей. Напишите латиницей."

    # Разбираем хвост: оплата, сумма внесения, имя клиента, долг
    tail_words = tail.split()

    payment_code = None
    paid_amount = 0
    is_debt = False
    remaining = []

    i = 0
    while i < len(tail_words):
        word = tail_words[i]

        if word.lower() == "долг":
            is_debt = True
        elif payment_code is None and is_valid_payment(word):
            payment_code = word
            # Проверяем: следующее слово — сумма внесения? (число после оплаты)
            if i + 1 < len(tail_words) and tail_words[i + 1].replace(" ", "").isdigit():
                paid_amount = int(tail_words[i + 1].replace(" ", ""))
                i += 1  # пропускаем число
        else:
            remaining.append(word)

        i += 1

    # Если долг — оплата не обязательна
    if not is_debt and payment_code is None:
        return f"Не указан вид оплаты для \"{product}\". Допустимые: нал, К, Д, Р, Ра, ИП"

    # Имя клиента обязательно при долге
    client_name = " ".join(remaining)
    if is_debt and not client_name:
        return f"Для долга укажите имя клиента. Пример: {product} {qty}*{price} Имя Долг"

    # Определяем оплату
    payment_type = ""
    recipient = ""
    if payment_code:
        payment_result = parse_payment_code(payment_code)
        if payment_result is None:
            return f"Неизвестный вид оплаты \"{payment_code}\""
        payment_type, recipient = payment_result

    total = qty * price

    # Считаем долг
    if is_debt and paid_amount > 0:
        debt_amount = total - paid_amount
    elif is_debt:
        debt_amount = total
        paid_amount = 0
    else:
        debt_amount = 0
        paid_amount = total

    return {
        "product": product,
        "qty": qty,
        "price": price,
        "total": total,
        "payment_type": payment_type,
        "recipient": recipient,
        "is_debt": is_debt,
        "client": client_name,
        "paid_amount": paid_amount,
        "debt_amount": debt_amount,
    }
