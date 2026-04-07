"""Telegram-бот для учёта продаж запчастей телефонов.

Использование:
    1. Получи токен у @BotFather в Telegram
    2. Вставь токен в config.py
    3. pip install python-telegram-bot openpyxl
    4. python bot.py
"""

import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN
from parser import parse_sale_message
from catalog import load_catalog, load_products_from_json, find_product, add_mapping
from storage import (
    add_sale,
    add_exchange,
    delete_sale_by_id,
    get_sale_by_id,
    partial_return,
    get_today_sales,
    get_today_debts,
    get_today_exchanges,
    get_sales_by_date,
    export_to_excel,
)

# Загружаем каталог товаров при старте
PRODUCTS = load_products_from_json()
CATALOG = load_catalog()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------- Команды ----------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Приветствие и инструкция."""
    await update.message.reply_text(
        "Бот учёта продаж\n\n"
        "Просто пишите продажи как в тетрадь:\n"
        "  Note 9s 1 * 9500 нал\n"
        "  11 Pro GX original 1 * 11000 К\n"
        "  A54 1 * 8000 Д Долг\n"
        "  11 pro ori 1 * 7500 нал Азамат\n\n"
        "Можно несколько строк в одном сообщении.\n\n"
        "Оплата:\n"
        "  нал — наличные\n"
        "  К — Каспи Камиль\n"
        "  Д — Каспи Диана\n"
        "  Р — Каспи Рауф\n"
        "  Ра — Каспи Разия\n"
        "  ИП — Каспи ИП\n\n"
        "После оплаты можно написать имя клиента\n"
        "В конце можно добавить Долг\n\n"
        "Команды:\n"
        "  /report — продажи за сегодня\n"
        "  /excel — скачать Excel за сегодня\n"
        "  /ret — возврат товара\n"
        "  /exchange — обмен товара\n"
        "  /debts — список долгов\n"
        "  /help — эта справка"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Текстовый отчёт за сегодня."""
    sales = get_today_sales()

    if not sales:
        await update.message.reply_text("Сегодня продаж пока нет.")
        return

    lines = [f"Продажи за {datetime.now().strftime('%d.%m.%Y')}:\n"]
    total = 0
    cash = 0
    debt_total = 0
    kaspi_by_recipient = {}

    for i, s in enumerate(sales, 1):
        payment_info = s["payment_type"]
        if s["recipient"]:
            payment_info += f" ({s['recipient']})"
        debt_mark = " [ДОЛГ]" if s.get("is_debt") else ""
        client_mark = f" | {s['client']}" if s.get("client") else ""

        lines.append(
            f"{i}. {s['product']} — {s['qty']}x{s['price']:,} = {s['total']:,} тг [{payment_info}]{client_mark}{debt_mark}"
        )
        total += s["total"]

        if s.get("is_debt"):
            debt_total += s["total"]
        elif s["payment_type"] == "Наличные":
            cash += s["total"]
        elif s["recipient"]:
            kaspi_by_recipient[s["recipient"]] = kaspi_by_recipient.get(s["recipient"], 0) + s["total"]

    lines.append(f"\nИтого: {total:,} тг")
    lines.append(f"  Наличные: {cash:,} тг")
    for name, amount in sorted(kaspi_by_recipient.items()):
        lines.append(f"  Каспи ({name}): {amount:,} тг")
    if debt_total:
        lines.append(f"  В долг: {debt_total:,} тг")

    # Обмены
    exchanges = get_today_exchanges()
    if exchanges:
        lines.append(f"\nОбмены ({len(exchanges)}):")
        for ex in exchanges:
            diff = ex["difference"]
            diff_text = f"возврат клиенту {diff:,}" if diff > 0 else f"доплата {abs(diff):,}"
            lines.append(f"  {ex['product_out']} ({ex['price_out']:,}) -> {ex['product_in']} ({ex['price_in']:,}) | {diff_text} тг")

    await update.message.reply_text("\n".join(lines))


async def cmd_excel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Выгрузка в Excel."""
    args = ctx.args
    if args:
        date_str = args[0]
        sales = get_sales_by_date(date_str)
        filename = f"sales_{date_str}.xlsx"
    else:
        sales = get_today_sales()
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"sales_{date_str}.xlsx"

    if not sales:
        await update.message.reply_text(f"Нет продаж за {date_str}.")
        return

    filepath = export_to_excel(sales, filename)

    await update.message.reply_document(
        document=open(filepath, "rb"),
        filename=filename,
        caption=f"Отчёт за {date_str} — {len(sales)} продаж, итого {sum(s['total'] for s in sales):,} тг"
    )


async def cmd_debts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Список долгов за сегодня."""
    debts = get_today_debts()
    if not debts:
        await update.message.reply_text("Долгов за сегодня нет.")
        return

    lines = ["Долги за сегодня:\n"]
    total = 0
    for i, d in enumerate(debts, 1):
        payment_info = d["payment_type"]
        if d["recipient"]:
            payment_info += f" ({d['recipient']})"
        lines.append(f"{i}. {d['product']} — {d['qty']}x{d['price']:,} = {d['total']:,} тг [{payment_info}]")
        total += d["total"]

    lines.append(f"\nИтого в долг: {total:,} тг")
    await update.message.reply_text("\n".join(lines))


# ---------- Возврат ----------

async def cmd_return(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать список продаж за сегодня с кнопками возврата."""
    sales = get_today_sales()

    if not sales:
        await update.message.reply_text("Сегодня продаж нет.")
        return

    lines = ["Выберите продажу для возврата:\n"]
    buttons = []

    for i, s in enumerate(sales, 1):
        payment_info = s["payment_type"]
        if s["recipient"]:
            payment_info += f" ({s['recipient']})"
        debt_mark = " [ДОЛГ]" if s.get("is_debt") else ""

        lines.append(
            f"{i}. {s['product']} — {s['qty']}x{s['price']:,} = {s['total']:,} тг{debt_mark}"
        )

        label = f"{i}. {s['product'][:30]} — {s['qty']}шт"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"ret_{s['id']}")
        ])

    buttons.append([InlineKeyboardButton("Отмена", callback_data="ret_cancel")])

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_return_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки возврата — показываем выбор кол-ва."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ret_cancel":
        await query.edit_message_text("Возврат отменён.")
        return

    if data.startswith("ret_") and not data.startswith("ret_qty_"):
        sale_id = int(data.replace("ret_", ""))
        sale = get_sale_by_id(sale_id)

        if not sale:
            await query.edit_message_text("Запись не найдена.")
            return

        if sale["qty"] == 1:
            # Одна штука — сразу возвращаем
            partial_return(sale_id, 1)
            payment_info = sale["payment_type"]
            if sale["recipient"]:
                payment_info += f" ({sale['recipient']})"
            await query.edit_message_text(
                f"Возврат выполнен:\n"
                f"{sale['product']} — 1x{sale['price']:,} = {sale['price']:,} тг [{payment_info}]"
            )
        else:
            # Несколько штук — спрашиваем сколько вернуть
            buttons = []
            row_buttons = []
            for n in range(1, sale["qty"] + 1):
                row_buttons.append(
                    InlineKeyboardButton(str(n), callback_data=f"ret_qty_{sale_id}_{n}")
                )
                if len(row_buttons) == 5:
                    buttons.append(row_buttons)
                    row_buttons = []
            if row_buttons:
                buttons.append(row_buttons)
            buttons.append([InlineKeyboardButton("Отмена", callback_data="ret_cancel")])

            await query.edit_message_text(
                f"{sale['product']} — {sale['qty']} шт по {sale['price']:,} тг\n"
                f"Сколько штук вернуть?",
                reply_markup=InlineKeyboardMarkup(buttons)
            )


async def handle_return_qty_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора кол-ва для возврата."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # ret_qty_<sale_id>_<qty>
    parts = data.split("_")
    sale_id = int(parts[2])
    return_qty = int(parts[3])

    sale = partial_return(sale_id, return_qty)

    if not sale:
        await query.edit_message_text("Запись не найдена.")
        return

    returned_total = return_qty * sale["price"]
    remaining = sale["qty"] - return_qty

    if remaining > 0:
        await query.edit_message_text(
            f"Возврат: {sale['product']} — {return_qty} шт на {returned_total:,} тг\n"
            f"Осталось: {remaining} шт на {remaining * sale['price']:,} тг"
        )
    else:
        await query.edit_message_text(
            f"Полный возврат: {sale['product']} — {return_qty} шт на {returned_total:,} тг"
        )


# ---------- Обмен ----------

async def cmd_exchange(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Начать обмен — показать список продаж для выбора."""
    sales = get_today_sales()

    if not sales:
        await update.message.reply_text("Сегодня продаж нет.")
        return

    lines = ["Какой товар клиент хочет обменять?\n"]
    buttons = []

    for i, s in enumerate(sales, 1):
        lines.append(f"{i}. {s['product']} — {s['price']:,} тг")
        label = f"{i}. {s['product'][:30]} — {s['price']:,}"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"exch_{s['id']}")
        ])

    buttons.append([InlineKeyboardButton("Отмена", callback_data="exch_cancel")])

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_exchange_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора товара для обмена."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "exch_cancel":
        await query.edit_message_text("Обмен отменён.")
        return

    if data.startswith("exch_"):
        sale_id = int(data.replace("exch_", ""))
        sale = get_sale_by_id(sale_id)

        if not sale:
            await query.edit_message_text("Запись не найдена.")
            return

        # Сохраняем в bot_data и просим написать новый товар
        user_id = update.effective_user.id
        ctx.bot_data[f"exchange_{user_id}"] = {
            "sale_id": sale_id,
            "product_out": sale["product"],
            "price_out": sale["price"],
            "seller": query.from_user.first_name,
        }

        await query.edit_message_text(
            f"Обмен: {sale['product']} ({sale['price']:,} тг)\n\n"
            f"Напишите новый товар в формате:\n"
            f"<название> <цена> <оплата>\n\n"
            f"Пример: Note 12 pro 5g inc 4500 нал\n"
            f"(оплата = как клиент получает разницу)"
        )


# ---------- Обработка сообщений ----------

async def handle_sale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка текстового сообщения как записи о продаже."""
    text = update.message.text

    if text.startswith("/"):
        return

    user_id = update.effective_user.id
    seller = update.effective_user.first_name

    # Проверяем: может это ответ на обмен?
    exchange_data = ctx.bot_data.get(f"exchange_{user_id}")
    if exchange_data:
        await _handle_exchange_input(update, ctx, exchange_data, text)
        return

    sales = parse_sale_message(text)

    if not sales:
        await update.message.reply_text(
            "Не понял формат. Пример:\n"
            "Note 9s 1 * 9500 нал\n"
            "11 Pro 1 * 11000 К\n"
            "A54 1 * 8000 Д Долг"
        )
        return

    for sale in sales:
        # Ищем полное название в каталоге
        matches = find_product(sale["product"], PRODUCTS, CATALOG)

        if len(matches) == 1:
            full_name = matches[0]
            sale_id = _save_sale(seller, sale, full_name)
            payment_info = _payment_info(sale)
            debt_mark = " [ДОЛГ]" if sale["is_debt"] else ""
            client_mark = f" | {sale['client']}" if sale.get("client") else ""
            await update.message.reply_text(
                f"#{sale_id} {full_name}\n"
                f"{sale['qty']}x{sale['price']:,} = {sale['total']:,} тг [{payment_info}]{client_mark}{debt_mark}"
            )

        elif len(matches) > 1:
            pending_key = f"pending_{user_id}_{id(sale)}"
            ctx.bot_data[pending_key] = {"seller": seller, "sale": sale}

            buttons = []
            for i, m in enumerate(matches[:10]):
                buttons.append([
                    InlineKeyboardButton(
                        m[:60],
                        callback_data=f"pick_{pending_key}_{i}"
                    )
                ])
            buttons.append([
                InlineKeyboardButton(
                    f"Оставить: {sale['product']}",
                    callback_data=f"pick_{pending_key}_asis"
                )
            ])

            ctx.bot_data[f"{pending_key}_matches"] = matches[:10]

            await update.message.reply_text(
                f"Найдено несколько товаров для \"{sale['product']}\".\n"
                f"Выберите правильный:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        else:
            sale_id = _save_sale(seller, sale, sale["product"])
            payment_info = _payment_info(sale)
            debt_mark = " [ДОЛГ]" if sale["is_debt"] else ""
            client_mark = f" | {sale['client']}" if sale.get("client") else ""
            await update.message.reply_text(
                f"#{sale_id} {sale['product']} (нет в каталоге)\n"
                f"{sale['qty']}x{sale['price']:,} = {sale['total']:,} тг [{payment_info}]{client_mark}{debt_mark}"
            )


async def _handle_exchange_input(update, ctx, exchange_data, text):
    """Обработка ввода нового товара для обмена."""
    user_id = update.effective_user.id

    # Парсим: <название> <цена> <оплата>
    import re
    match = re.match(r'^(.+?)\s+(\d[\d\s]*)\s+([a-zA-Zа-яА-ЯёЁ]+)$', text.strip())

    if not match:
        await update.message.reply_text(
            "Не понял. Напишите:\n<название> <цена> <оплата>\n\nПример: Note 12 pro 4500 нал"
        )
        return

    product_in = match.group(1).strip()
    price_in = int(match.group(2).replace(" ", ""))
    payment_code = match.group(3)

    from parser import parse_payment_code
    payment_type, recipient = parse_payment_code(payment_code)

    # Ищем полное название
    matches = find_product(product_in, PRODUCTS, CATALOG)
    if len(matches) == 1:
        product_in = matches[0]

    product_out = exchange_data["product_out"]
    price_out = exchange_data["price_out"]
    seller = exchange_data["seller"]
    sale_id = exchange_data["sale_id"]

    # Удаляем старую продажу
    delete_sale_by_id(sale_id)

    # Записываем обмен
    ex_id = add_exchange(
        seller=seller,
        product_out=product_out,
        price_out=price_out,
        product_in=product_in,
        price_in=price_in,
        payment_type=payment_type,
        recipient=recipient,
    )

    # Записываем новую продажу (новый товар)
    add_sale(
        seller=seller,
        product=product_in,
        qty=1,
        price=price_in,
        total=price_in,
        payment_type=payment_type,
        recipient=recipient,
    )

    difference = price_out - price_in

    if difference > 0:
        diff_text = f"Возврат клиенту: {difference:,} тг"
    elif difference < 0:
        diff_text = f"Доплата от клиента: {abs(difference):,} тг"
    else:
        diff_text = "Без доплаты"

    payment_info = payment_type
    if recipient:
        payment_info += f" ({recipient})"

    await update.message.reply_text(
        f"Обмен #{ex_id}:\n"
        f"{product_out} ({price_out:,} тг)\n"
        f"  -> {product_in} ({price_in:,} тг)\n\n"
        f"{diff_text} [{payment_info}]"
    )

    # Чистим
    ctx.bot_data.pop(f"exchange_{user_id}", None)


async def handle_pick_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора товара из каталога."""
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split("_")
    choice = parts[-1]
    pending_key = "_".join(parts[1:-1])

    pending = ctx.bot_data.get(pending_key)
    if not pending:
        await query.edit_message_text("Данные устарели, повторите продажу.")
        return

    sale = pending["sale"]
    seller = pending["seller"]

    if choice == "asis":
        full_name = sale["product"]
    else:
        idx = int(choice)
        matches = ctx.bot_data.get(f"{pending_key}_matches", [])
        full_name = matches[idx]
        add_mapping(sale["product"], full_name, CATALOG)

    sale_id = _save_sale(seller, sale, full_name)
    payment_info = _payment_info(sale)
    debt_mark = " [ДОЛГ]" if sale["is_debt"] else ""
    client_mark = f" | {sale['client']}" if sale.get("client") else ""

    await query.edit_message_text(
        f"#{sale_id} {full_name}\n"
        f"{sale['qty']}x{sale['price']:,} = {sale['total']:,} тг [{payment_info}]{client_mark}{debt_mark}"
    )

    ctx.bot_data.pop(pending_key, None)
    ctx.bot_data.pop(f"{pending_key}_matches", None)


def _save_sale(seller: str, sale: dict, full_name: str) -> int:
    """Сохраняет продажу с полным названием."""
    return add_sale(
        seller=seller,
        product=full_name,
        qty=sale["qty"],
        price=sale["price"],
        total=sale["total"],
        payment_type=sale["payment_type"],
        recipient=sale["recipient"],
        is_debt=sale.get("is_debt", False),
        client=sale.get("client", ""),
    )


def _payment_info(sale: dict) -> str:
    info = sale["payment_type"]
    if sale["recipient"]:
        info += f" ({sale['recipient']})"
    return info


# ---------- Меню команд ----------

async def set_bot_commands(app):
    """Устанавливает кнопку меню с командами."""
    await app.bot.set_my_commands([
        BotCommand("report", "Продажи за сегодня"),
        BotCommand("excel", "Скачать Excel"),
        BotCommand("ret", "Возврат товара"),
        BotCommand("exchange", "Обмен товара"),
        BotCommand("debts", "Список долгов"),
        BotCommand("help", "Справка"),
    ])


# ---------- Запуск ----------

def main():
    if not BOT_TOKEN:
        print("Set BOT_TOKEN in .env file!")
        return

    app = Application.builder().token(BOT_TOKEN).post_init(set_bot_commands).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("excel", cmd_excel))
    app.add_handler(CommandHandler("debts", cmd_debts))
    app.add_handler(CommandHandler("ret", cmd_return))
    app.add_handler(CommandHandler("exchange", cmd_exchange))
    app.add_handler(CallbackQueryHandler(handle_return_qty_callback, pattern=r"^ret_qty_"))
    app.add_handler(CallbackQueryHandler(handle_return_callback, pattern=r"^ret_"))
    app.add_handler(CallbackQueryHandler(handle_exchange_callback, pattern=r"^exch_"))
    app.add_handler(CallbackQueryHandler(handle_pick_callback, pattern=r"^pick_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sale))

    print("Bot started! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
