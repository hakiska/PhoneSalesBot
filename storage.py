"""Хранение продаж в SQLite и экспорт в Excel."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

from config import DB_PATH


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            seller TEXT NOT NULL,
            product TEXT NOT NULL,
            qty INTEGER NOT NULL,
            price INTEGER NOT NULL,
            total INTEGER NOT NULL,
            payment_type TEXT NOT NULL,
            recipient TEXT DEFAULT ''
        )
    """)
    conn.commit()
    return conn


def add_sale(seller: str, product: str, qty: int, price: int,
             total: int, payment_type: str, recipient: str) -> int:
    """Добавляет продажу. Возвращает ID записи."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO sales (timestamp, seller, product, qty, price, total, payment_type, recipient)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), seller, product, qty, price, total, payment_type, recipient)
    )
    conn.commit()
    sale_id = cur.lastrowid
    conn.close()
    return sale_id


def delete_last_sale(seller: str) -> bool:
    """Удаляет последнюю продажу продавца. Возвращает True если удалено."""
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM sales WHERE seller = ? ORDER BY id DESC LIMIT 1",
        (seller,)
    ).fetchone()
    if row:
        conn.execute("DELETE FROM sales WHERE id = ?", (row[0],))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


def delete_sale_by_id(sale_id: int) -> dict | None:
    """Удаляет продажу по ID. Возвращает удалённую запись или None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if row:
        sale = dict(zip(
            ["id", "timestamp", "seller", "product", "qty", "price", "total", "payment_type", "recipient"],
            row
        ))
        conn.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
        conn.commit()
        conn.close()
        return sale
    conn.close()
    return None


def get_today_sales(seller: str = None) -> list[dict]:
    """Продажи за сегодня. Если seller указан — только его."""
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")

    if seller:
        rows = conn.execute(
            "SELECT * FROM sales WHERE timestamp LIKE ? AND seller = ? ORDER BY id",
            (f"{today}%", seller)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sales WHERE timestamp LIKE ? ORDER BY id",
            (f"{today}%",)
        ).fetchall()

    conn.close()
    return _rows_to_dicts(rows)


def get_sales_by_date(date_str: str) -> list[dict]:
    """Продажи за конкретную дату (формат YYYY-MM-DD)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sales WHERE timestamp LIKE ? ORDER BY id",
        (f"{date_str}%",)
    ).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def _rows_to_dicts(rows) -> list[dict]:
    columns = ["id", "timestamp", "seller", "product", "qty", "price", "total", "payment_type", "recipient"]
    return [dict(zip(columns, row)) for row in rows]


def export_to_excel(sales: list[dict], filename: str = None) -> str:
    """Экспортирует продажи в Excel. Возвращает путь к файлу."""
    if not filename:
        today = datetime.now().strftime("%Y-%m-%d")
        filename = f"sales_{today}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Продажи"

    # Заголовки
    headers = ["№", "Время", "Продавец", "Товар", "Кол-во", "Цена", "Сумма", "Оплата", "Получатель"]
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    # Данные
    for i, sale in enumerate(sales, 1):
        ts = datetime.fromisoformat(sale["timestamp"])
        row_data = [
            i,
            ts.strftime("%H:%M"),
            sale["seller"],
            sale["product"],
            sale["qty"],
            sale["price"],
            sale["total"],
            sale["payment_type"],
            sale["recipient"],
        ]
        for col, value in enumerate(row_data, 1):
            cell = ws.cell(row=i + 1, column=col, value=value)
            cell.border = thin_border
            if col in (5, 6, 7):  # числовые колонки
                cell.number_format = "#,##0"
                cell.alignment = Alignment(horizontal="right")

    # Итоговая строка
    total_row = len(sales) + 2
    ws.cell(row=total_row, column=6, value="ИТОГО:").font = Font(bold=True)
    ws.cell(row=total_row, column=7, value=sum(s["total"] for s in sales)).font = Font(bold=True)
    ws.cell(row=total_row, column=7).number_format = "#,##0"

    # Итоги по типам оплаты
    summary_row = total_row + 2
    ws.cell(row=summary_row, column=1, value="Сводка по оплате:").font = Font(bold=True, size=11)

    cash_total = sum(s["total"] for s in sales if s["payment_type"] == "Наличные")
    kaspi_total = sum(s["total"] for s in sales if s["payment_type"] == "Каспи")

    ws.cell(row=summary_row + 1, column=1, value="Наличные:")
    ws.cell(row=summary_row + 1, column=2, value=cash_total).number_format = "#,##0"

    # Разбивка по получателям Каспи
    recipients = {}
    for s in sales:
        if s["payment_type"] == "Каспи" and s["recipient"]:
            recipients[s["recipient"]] = recipients.get(s["recipient"], 0) + s["total"]

    row = summary_row + 2
    for name, amount in sorted(recipients.items()):
        ws.cell(row=row, column=1, value=f"Каспи ({name}):")
        ws.cell(row=row, column=2, value=amount).number_format = "#,##0"
        row += 1

    # Ширина колонок
    widths = [5, 8, 12, 30, 8, 12, 12, 12, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    filepath = str(Path(filename).resolve())
    wb.save(filepath)
    return filepath
