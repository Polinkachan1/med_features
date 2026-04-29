import sqlite3
import pandas as pd
import os
import json

DB_PATH = 'medical_data.db'
EXCEL_PATH = 'unnececasy/grls2026_03_25_1_Выдано_по_правилам_ЕАЭС.xlsx'


def init_db():
    """Создает таблицы"""
    conn = sqlite3.connect(DB_PATH)

    conn.execute('''
        CREATE TABLE IF NOT EXISTS medicines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_name TEXT NOT NULL UNIQUE,
            official_side_effects TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            review_text TEXT NOT NULL,
            source TEXT DEFAULT 'irecommend',
            url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print("✅ База данных создана")


def read_drugs_from_excel():
    """
    Читает торговые названия из Excel:
    - Столбец I (индекс 8) - торговое название
    Данные начинаются с 7 строки Excel (индекс 6 в pandas)
    """

    if not os.path.exists(EXCEL_PATH):
        print(f"❌ Файл не найден: {EXCEL_PATH}")
        print(f"   Текущая папка: {os.getcwd()}")
        return []

    print(f"📖 Чтение файла: {EXCEL_PATH}")

    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name="Выдано по правилам ЕАЭС", header=None)
        print(f"✅ Файл прочитан, строк: {len(df)}")
    except Exception as e:
        print(f"❌ Ошибка чтения: {e}")
        return []

    # Столбец I (индекс 8) - торговое название
    TRADE_NAME_COL = 8
    START_ROW = 6  # 7 строка Excel (индекс 6)

    drugs = []

    for idx in range(START_ROW, len(df)):
        row = df.iloc[idx]

        trade_name = row[TRADE_NAME_COL] if len(row) > TRADE_NAME_COL else None

        if pd.notna(trade_name) and isinstance(trade_name, str):
            trade_name = trade_name.strip()
        else:
            continue

        # Пропускаем пустые и служебные строки
        if not trade_name or len(trade_name) < 2:
            continue

        skip_words = ['торговое наименование', 'nothing', 'nan']
        if any(skip in trade_name.lower() for skip in skip_words):
            continue

        # Приводим к нижнему регистру
        trade_name = trade_name.lower()

        if trade_name not in drugs:
            drugs.append(trade_name)

    print(f"✅ Найдено торговых названий: {len(drugs)}")

    # Показываем первые 30
    print("\n📋 Первые 30 торговых названий:")
    for i, name in enumerate(drugs[:30], 1):
        print(f"   {i}. {name}")

    return drugs


def save_to_database(drugs):
    """Сохраняет названия в базу"""

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Очищаем старые данные
    cursor.execute("DELETE FROM medicines")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name='medicines'")

    added = 0
    for drug in drugs:
        try:
            cursor.execute('''
                INSERT INTO medicines (medicine_name, official_side_effects)
                VALUES (?, ?)
            ''', (drug, json.dumps([])))
            added += 1
            if added % 100 == 0:
                print(f"   Добавлено: {added}")
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    conn.close()

    print(f"\n✅ Добавлено в базу: {added} препаратов")
    return added


def check_database():
    """Проверяет содержимое базы"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM medicines")
    count = cursor.fetchone()[0]

    print(f"\n📊 В базе данных: {count} препаратов")

    if count > 0:
        cursor.execute("SELECT medicine_name FROM medicines LIMIT 30")
        samples = cursor.fetchall()
        print("\n📋 Примеры (первые 30):")
        for i, s in enumerate(samples, 1):
            print(f"   {i}. {s[0]}")

    conn.close()
    return count


def search_test(drug_name):
    """Тест поиска"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    drug_lower = drug_name.lower()
    cursor.execute("SELECT id, medicine_name FROM medicines WHERE medicine_name = ?", (drug_lower,))
    result = cursor.fetchone()

    conn.close()

    if result:
        print(f"✅ Найден: {drug_name} (ID: {result[0]})")
        return True
    else:
        print(f"❌ Не найден: {drug_name}")
        return False


if __name__ == "__main__":

    # 1. Создаем базу
    init_db()

    # 2. Читаем названия из Excel
    drugs = read_drugs_from_excel()

    if not drugs:
        print("❌ Не удалось прочитать данные")
        exit()

    # 3. Сохраняем в базу
    save_to_database(drugs)