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
    delete_last_sale,
    delete_sale_by_id,
    get_today_sales,
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
        "🏪 Бот учёта продаж\n\n"
        "Просто пишите продажи как в тетрадь:\n"
        "  Note 9s 1 * 9500 нал\n"
        "  11 Pro GX original 1 * 11000 К\n\n"
        "Можно несколько строк в одном сообщении.\n\n"
        "Оплата:\n"
        "  нал — наличные\n"
        "  К — Каспи Камиль\n"
        "  Д — Каспи Диана\n"
        "  Р — Каспи Рауф\n"
        "  Ра — Каспи Разия\n"
        "  ИП — Каспи ИП\n\n"
        "Команды:\n"
        "  /report — продажи за сегодня\n"
        "  /excel — скачать Excel за сегодня\n"
        "  /excel 2026-04-07 — за конкретную дату\n"
        "  /cancel — удалить последнюю запись\n"
        "  /ret — возврат товара (список с кнопками)\n"
        "  /help — эта справка"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Текстовый отчёт за сегодня."""
    seller = update.effective_user.first_name
    sales = get_today_sales()

    if not sales:
        await update.message.reply_text("Сегодня продаж пока нет.")
        return

    lines = [f"📊 Продажи за {datetime.now().strftime('%d.%m.%Y')}:\n"]
    total = 0
    cash = 0
    kaspi_by_recipient = {}

    for i, s in enumerate(sales, 1):
        payment_info = s["payment_type"]
        if s["recipient"]:
            payment_info += f" ({s['recipient']})"

        lines.append(
            f"{i}. {s['product']} — {s['qty']}×{s['price']:,} = {s['total']:,} тг [{payment_info}] ({s['seller']})"
        )
        total += s["total"]

        if s["payment_type"] == "Наличные":
            cash += s["total"]
        elif s["recipient"]:
            kaspi_by_recipient[s["recipient"]] = kaspi_by_recipient.get(s["recipient"], 0) + s["total"]

    lines.append(f"\n💰 Итого: {total:,} тг")
    lines.append(f"  Наличные: {cash:,} тг")
    for name, amount in sorted(kaspi_by_recipient.items()):
        lines.append(f"  Каспи ({name}): {amount:,} тг")

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
        caption=f"📋 Отчёт за {date_str} — {len(sales)} продаж, итого {sum(s['total'] for s in sales):,} тг"
    )


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Удалить последнюю запись продавца."""
    seller = update.effective_user.first_name
    if delete_last_sale(seller):
        await update.message.reply_text("✅ Последняя запись удалена.")
    else:
        await update.message.reply_text("Нечего удалять.")


async def cmd_return(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать список продаж за сегодня с кнопками возврата."""
    sales = get_today_sales()

    if not sales:
        await update.message.reply_text("Сегодня продаж нет.")
        return

    lines = [f"Выберите продажу для возврата:\n"]
    buttons = []

    for i, s in enumerate(sales, 1):
        payment_info = s["payment_type"]
        if s["recipient"]:
            payment_info += f" ({s['recipient']})"

        lines.append(
            f"{i}. {s['product']} — {s['qty']}x{s['price']:,} = {s['total']:,} тг [{payment_info}]"
        )
        buttons.append([
            InlineKeyboardButton(
                f"{i}. {s['product']} — {s['total']:,} тг",
                callback_data=f"return_{s['id']}"
            )
        ])

    buttons.append([InlineKeyboardButton("Отмена", callback_data="return_cancel")])

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_return_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки возврата."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "return_cancel":
        await query.edit_message_text("Возврат отменён.")
        return

    if data.startswith("return_"):
        sale_id = int(data.replace("return_", ""))
        sale = delete_sale_by_id(sale_id)

        if sale:
            payment_info = sale["payment_type"]
            if sale["recipient"]:
                payment_info += f" ({sale['recipient']})"

            await query.edit_message_text(
                f"Возврат выполнен:\n"
                f"{sale['product']} — {sale['qty']}x{sale['price']:,} = {sale['total']:,} тг [{payment_info}]"
            )
        else:
            await query.edit_message_text("Запись уже была удалена.")


# ---------- Обработка сообщений ----------

async def handle_sale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка текстового сообщения как записи о продаже."""
    text = update.message.text

    # Игнорируем команды
    if text.startswith("/"):
        return

    seller = update.effective_user.first_name
    sales = parse_sale_message(text)

    if not sales:
        await update.message.reply_text(
            "Не понял формат. Пример:\n"
            "Note 9s 1 * 9500 нал\n"
            "11 Pro 1 * 11000 К"
        )
        return

    for sale in sales:
        # Ищем полное название в каталоге
        matches = find_product(sale["product"], PRODUCTS, CATALOG)

        if len(matches) == 1:
            # Точное совпадение — сразу записываем
            full_name = matches[0]
            sale_id = _save_sale(seller, sale, full_name)

            payment_info = _payment_info(sale)
            await update.message.reply_text(
                f"#{sale_id} {full_name}\n"
                f"{sale['qty']}x{sale['price']:,} = {sale['total']:,} тг [{payment_info}]"
            )

        elif len(matches) > 1:
            # Несколько вариантов — показываем кнопки
            # Сохраняем данные продажи во временное хранилище
            pending_key = f"pending_{update.effective_user.id}_{id(sale)}"
            ctx.bot_data[pending_key] = {"seller": seller, "sale": sale}

            buttons = []
            for i, m in enumerate(matches[:10]):  # макс 10 кнопок
                buttons.append([
                    InlineKeyboardButton(
                        m[:60],  # обрезаем длинные названия для кнопки
                        callback_data=f"pick_{pending_key}_{i}"
                    )
                ])
            # Кнопка "записать как есть"
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
            # Не найдено — записываем как есть
            sale_id = _save_sale(seller, sale, sale["product"])

            payment_info = _payment_info(sale)
            await update.message.reply_text(
                f"#{sale_id} {sale['product']} (нет в каталоге)\n"
                f"{sale['qty']}x{sale['price']:,} = {sale['total']:,} тг [{payment_info}]"
            )


async def handle_pick_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора товара из каталога."""
    query = update.callback_query
    await query.answer()

    data = query.data  # pick_pending_123_456_0 or pick_pending_123_456_asis
    parts = data.split("_")
    # Восстанавливаем pending_key (всё между первым _ и последним _)
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
        # Запоминаем маппинг на будущее
        add_mapping(sale["product"], full_name, CATALOG)

    sale_id = _save_sale(seller, sale, full_name)
    payment_info = _payment_info(sale)

    await query.edit_message_text(
        f"#{sale_id} {full_name}\n"
        f"{sale['qty']}x{sale['price']:,} = {sale['total']:,} тг [{payment_info}]"
    )

    # Чистим временные данные
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
        BotCommand("cancel", "Удалить последнюю запись"),
        BotCommand("help", "Справка"),
    ])


# ---------- Запуск ----------

def main():
    if BOT_TOKEN == "СЮДА_ВСТАВЬ_ТОКЕН":
        print("⚠️  Вставь токен бота в config.py!")
        print("   Получить токен: напиши /newbot в @BotFather в Telegram")
        return

    app = Application.builder().token(BOT_TOKEN).post_init(set_bot_commands).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("excel", cmd_excel))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("ret", cmd_return))
    app.add_handler(CallbackQueryHandler(handle_return_callback, pattern=r"^return_"))
    app.add_handler(CallbackQueryHandler(handle_pick_callback, pattern=r"^pick_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sale))

    print("Bot started! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
