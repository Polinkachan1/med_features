import sqlite3
import json
import os

DB_PATH = 'medical_data.db'
JSON_PATH = 'side_e_dataset.json'  # путь к твоему файлу


def import_side_effects():
    """Импортирует препараты и их побочные эффекты из JSON в БД"""

    # Проверяем, существует ли файл
    if not os.path.exists(JSON_PATH):
        print(f"❌ Файл {JSON_PATH} не найден")
        return

    # Загружаем JSON
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"📖 Загружено записей: {len(data)}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    added = 0
    skipped = 0

    for item in data:
        drug_name = item.get('drug_name_ru', '').strip().lower()

        # Пропускаем пустые названия
        if not drug_name:
            skipped += 1
            continue

        # Собираем побочные эффекты из side_e_parts
        side_effects = []

        side_parts = item.get('side_e_parts', {})
        if side_parts:
            # Проходим по всем категориям
            for category, frequency_dict in side_parts.items():
                if isinstance(frequency_dict, dict):
                    for frequency, effects in frequency_dict.items():
                        if isinstance(effects, list):
                            for effect in effects:
                                if effect and isinstance(effect, str):
                                    side_effects.append(effect.strip())
                        elif isinstance(effects, str) and effects:
                            side_effects.append(effects.strip())
                elif isinstance(frequency_dict, list):
                    for effect in frequency_dict:
                        if effect and isinstance(effect, str):
                            side_effects.append(effect.strip())

        # Если нет side_e_parts, пробуем взять из текста (но это сложнее)
        if not side_effects and item.get('text'):
            # Простая эвристика: ищем маркеры побочек в тексте
            text = item.get('text', '')
            # Это грубый подход, но лучше чем ничего
            lines = text.split('\n')
            for line in lines:
                if ' - ' in line or '•' in line or '–' in line:
                    parts = line.replace('•', '').replace('–', '-').split('-')
                    for part in parts:
                        clean = part.strip()
                        if len(clean) > 5 and len(clean) < 100:
                            side_effects.append(clean)

        # Убираем дубликаты
        side_effects = list(set(side_effects))

        # Ограничиваем количество побочек (чтобы не было слишком много мусора)
        if len(side_effects) > 50:
            side_effects = side_effects[:50]

        # Проверяем, есть ли уже такой препарат в БД
        cursor.execute('SELECT id FROM medicines WHERE medicine_name = ?', (drug_name,))
        existing = cursor.fetchone()

        if existing:
            # Обновляем существующий
            cursor.execute('''
                UPDATE medicines 
                SET official_side_effects = ?
                WHERE medicine_name = ?
            ''', (json.dumps(side_effects, ensure_ascii=False), drug_name))
            print(f"🔄 Обновлён: {drug_name} ({len(side_effects)} побочек)")
        else:
            # Добавляем новый
            cursor.execute('''
                INSERT INTO medicines (medicine_name, official_side_effects)
                VALUES (?, ?)
            ''', (drug_name, json.dumps(side_effects, ensure_ascii=False)))
            print(f"✅ Добавлен: {drug_name} ({len(side_effects)} побочек)")

        added += 1

    conn.commit()
    conn.close()

    print(f"\n📊 ИТОГО:")
    print(f"   Добавлено/обновлено: {added}")
    print(f"   Пропущено (нет названия): {skipped}")


def check_database():
    """Проверяет содержимое базы после импорта"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM medicines')
    count = cursor.fetchone()[0]
    print(f"\n📊 В базе данных: {count} препаратов")

    # Показываем несколько примеров
    cursor.execute('SELECT medicine_name, official_side_effects FROM medicines LIMIT 10')
    samples = cursor.fetchall()
    print("\n📋 Примеры импортированных препаратов:")
    for name, effects_json in samples:
        effects = json.loads(effects_json) if effects_json else []
        print(f"   • {name}: {len(effects)} побочек")

    conn.close()


if __name__ == '__main__':
    import_side_effects()
    check_database()