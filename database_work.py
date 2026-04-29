import sqlite3
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'medical_data.db')


def init_db():
    conn = sqlite3.connect(DB_PATH)

    # Таблица препаратов
    conn.execute('''
        CREATE TABLE IF NOT EXISTS medicines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_name TEXT NOT NULL UNIQUE,
            official_side_effects TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица отзывов
    conn.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            review_text TEXT NOT NULL,
            source TEXT DEFAULT 'irecommend',
            url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (medicine_id) REFERENCES medicines (id) ON DELETE CASCADE
        )
    ''')

    # Таблица для хранения обработанных предложений
    conn.execute('''
        CREATE TABLE IF NOT EXISTS processed_sentences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            sentence TEXT NOT NULL,
            original_sentence TEXT,
            normalized_sentence TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (medicine_id) REFERENCES medicines (id) ON DELETE CASCADE
        )
    ''')

    # Таблица для хранения кандидатов (медицинских терминов) из предложений
    conn.execute('''
        CREATE TABLE IF NOT EXISTS candidate_symptoms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            sentence_id INTEGER NOT NULL,
            candidate_norm TEXT NOT NULL,
            candidate_original TEXT NOT NULL,
            is_medical BOOLEAN DEFAULT 0,
            frequency INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (medicine_id) REFERENCES medicines (id) ON DELETE CASCADE,
            FOREIGN KEY (sentence_id) REFERENCES processed_sentences (id) ON DELETE CASCADE
        )
    ''')

    # Индексы для быстрого поиска
    conn.execute('CREATE INDEX IF NOT EXISTS idx_candidate_medicine ON candidate_symptoms(medicine_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_candidate_norm ON candidate_symptoms(candidate_norm)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sentences_medicine ON processed_sentences(medicine_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_reviews_medicine ON reviews(medicine_id)')

    # Миграция для старой таблицы reviews, если она уже была создана без url
    columns = [row[1] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()]
    if 'url' not in columns:
        conn.execute("ALTER TABLE reviews ADD COLUMN url TEXT")

    conn.commit()
    conn.close()


def get_from_db(entry_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    result = conn.execute('''
        SELECT input_type, content
        FROM entries
        WHERE id = ?
    ''', (entry_id,)).fetchone()
    conn.close()

    if result:
        return dict(result)
    return None


def add_medicine(medicine, official_side_effects):
    conn = sqlite3.connect(DB_PATH)
    pobochki_json = json.dumps(official_side_effects, ensure_ascii=False)

    conn.execute('''
        INSERT INTO medicines (medicine_name, official_side_effects)
        VALUES (?, ?)
    ''', (medicine, pobochki_json))

    conn.commit()
    medicine_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return medicine_id


def get_medicine(medicine):
    """Ищет препарат, отдавая приоритет записям с официальными побочками"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    search_term = medicine.lower().strip()

    result = conn.execute('''
        SELECT * 
        FROM medicines 
        WHERE LOWER(medicine_name) LIKE ? 
        AND official_side_effects IS NOT NULL
        AND official_side_effects != '[]'
        AND official_side_effects != ''
        LIMIT 1
    ''', (f'%{search_term}%',)).fetchone()

    if not result:
        result = conn.execute('''
            SELECT * 
            FROM medicines 
            WHERE LOWER(medicine_name) LIKE ? 
            LIMIT 1
        ''', (f'%{search_term}%',)).fetchone()

    conn.close()

    if result:
        return dict(result)
    return None


def get_medicines_by_name(search_term):
    """
    Возвращает ВСЕ совпадения препаратов по названию.
    Сортировка: сначала те, у которых есть официальные побочки.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    search_lower = search_term.lower().strip()

    results = conn.execute('''
        SELECT id, medicine_name, official_side_effects
        FROM medicines 
        WHERE LOWER(medicine_name) LIKE ? 
        ORDER BY 
            CASE 
                WHEN official_side_effects IS NOT NULL 
                 AND official_side_effects != '[]' 
                 AND official_side_effects != '' 
                THEN 0 
                ELSE 1 
            END,
            medicine_name
    ''', (f'%{search_lower}%',)).fetchall()

    conn.close()
    return [dict(row) for row in results]


def add_review(medicine_id, review_text, source='irecommend', url=None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        INSERT INTO reviews (medicine_id, review_text, source, url)
        VALUES (?, ?, ?, ?)
    ''', (medicine_id, review_text, source, url))
    conn.commit()
    conn.close()


def get_reviews(medicine_id):
    conn = sqlite3.connect(DB_PATH)
    results = conn.execute('''
        SELECT review_text
        FROM reviews
        WHERE medicine_id = ?
    ''', (medicine_id,)).fetchall()
    conn.close()
    return [row[0] for row in results]


def save_into_db(input_type, user_input):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        INSERT INTO entries (input_type, content)
        VALUES (?, ?)
    ''', (input_type, user_input))
    conn.commit()
    entry_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return entry_id


# ========== НОВЫЕ ФУНКЦИИ ДЛЯ ПРЕДОБРАБОТКИ ==========

def save_processed_sentence(medicine_id, sentence, original_sentence, normalized_sentence):
    """Сохраняет обработанное предложение"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO processed_sentences (medicine_id, sentence, original_sentence, normalized_sentence)
        VALUES (?, ?, ?, ?)
    ''', (medicine_id, sentence, original_sentence, normalized_sentence))
    sentence_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return sentence_id


def save_candidate_symptom(medicine_id, sentence_id, candidate_norm, candidate_original, is_medical):
    """Сохраняет кандидата (симптом)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, frequency FROM candidate_symptoms 
        WHERE medicine_id = ? AND candidate_norm = ? AND sentence_id = ?
    ''', (medicine_id, candidate_norm, sentence_id))
    existing = cursor.fetchone()

    if existing:
        cursor.execute('''
            UPDATE candidate_symptoms 
            SET frequency = frequency + 1
            WHERE id = ?
        ''', (existing[0],))
    else:
        cursor.execute('''
            INSERT INTO candidate_symptoms (medicine_id, sentence_id, candidate_norm, candidate_original, is_medical)
            VALUES (?, ?, ?, ?, ?)
        ''', (medicine_id, sentence_id, candidate_norm, candidate_original, is_medical))

    conn.commit()
    conn.close()


def get_candidates_for_drug(medicine_name):
    """Получает всех кандидатов для препарата"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT cs.candidate_norm, cs.candidate_original, SUM(cs.frequency) as total_frequency
        FROM candidate_symptoms cs
        JOIN medicines m ON cs.medicine_id = m.id
        WHERE LOWER(m.medicine_name) = ?
        GROUP BY cs.candidate_norm, cs.candidate_original
        ORDER BY total_frequency DESC
    ''', (medicine_name.lower(),))

    results = cursor.fetchall()
    conn.close()
    return [dict(row) for row in results]


def get_sentences_for_drug(medicine_name):
    """Получает предложения для препарата"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT ps.id, ps.sentence, ps.original_sentence, ps.normalized_sentence
        FROM processed_sentences ps
        JOIN medicines m ON ps.medicine_id = m.id
        WHERE LOWER(m.medicine_name) = ?
    ''', (medicine_name.lower(),))

    results = cursor.fetchall()
    conn.close()
    return [dict(row) for row in results]