import sqlite3
import json
import os

DB_PATH = 'medical_data.db'
JSON_PATH = 'of_pobochki.json'


def import_drugs_from_json():
    """Импортирует препараты из JSON в БД"""

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
    updated = 0

    for item in data:
        drug_name = item.get('drug_name_ru', '').strip().lower()

        if not drug_name:
            print(f"⚠️ Пропущен: нет названия")
            continue

        # Собираем побочные эффекты из side_e_parts
        side_effects = []
        side_parts = item.get('side_e_parts', {})

        if side_parts:
            for category, freq_dict in side_parts.items():
                if isinstance(freq_dict, dict):
                    for frequency, effects in freq_dict.items():
                        if isinstance(effects, list):
                            for effect in effects:
                                if effect and isinstance(effect, str):
                                    side_effects.append(effect.strip())
                        elif isinstance(effects, str) and effects:
                            side_effects.append(effects.strip())
                elif isinstance(freq_dict, list):
                    for effect in freq_dict:
                        if effect and isinstance(effect, str):
                            side_effects.append(effect.strip())

        # Убираем дубликаты
        side_effects = list(set(side_effects))

        # Проверяем, есть ли уже такой препарат
        cursor.execute('SELECT id FROM medicines WHERE medicine_name = ?', (drug_name,))
        existing = cursor.fetchone()

        if existing:
            # Обновляем существующий
            cursor.execute('''
                UPDATE medicines 
                SET official_side_effects = ?
                WHERE medicine_name = ?
            ''', (json.dumps(side_effects, ensure_ascii=False), drug_name))
            print(f"   🔄 Обновлён: {drug_name} ({len(side_effects)} побочек)")
            updated += 1
        else:
            # Добавляем новый
            cursor.execute('''
                INSERT INTO medicines (medicine_name, official_side_effects)
                VALUES (?, ?)
            ''', (drug_name, json.dumps(side_effects, ensure_ascii=False)))
            print(f"   ✅ Добавлен: {drug_name} ({len(side_effects)} побочек)")
            added += 1

    conn.commit()
    conn.close()

    print(f"\n📊 ИТОГО:")
    print(f"   ✅ Добавлено: {added}")
    print(f"   🔄 Обновлено: {updated}")


def check_database():
    """Проверяет содержимое базы после импорта"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM medicines')
    count = cursor.fetchone()[0]
    print(f"\n📊 В базе данных: {count} препаратов")

    # Показываем последние 10 добавленных
    cursor.execute('SELECT medicine_name, official_side_effects FROM medicines ORDER BY id DESC LIMIT 10')
    samples = cursor.fetchall()
    print("\n📋 Последние добавленные препараты:")
    for name, effects_json in samples:
        effects = json.loads(effects_json) if effects_json else []
        print(f"   • {name}: {len(effects)} побочек")

    conn.close()


if __name__ == '__main__':
    import_drugs_from_json()
    check_database()