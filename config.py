"""Конфигурация бота."""

import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token — берём из переменной окружения, или из .env для локалки
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Получатели Каспи-переводов
KASPI_RECIPIENTS = {
    "к":   "Камиль",
    "д":   "Диана",
    "р":   "Рауф",
    "ра":  "Разия",
    "ип":  "Каспи ИП",
}

# Типы оплаты
PAYMENT_CASH = "Наличные"
PAYMENT_KASPI = "Каспи"

# Файл базы данных
DB_PATH = "sales.db"
