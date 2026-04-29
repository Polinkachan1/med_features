import re
import sqlite3
import itertools
from collections import defaultdict

import pymorphy2
import networkx as nx

from working_with_text import STOP_WORDS, normalize_phrase
from medical_filter import is_medical_term

morph = pymorphy2.MorphAnalyzer()

BAD_ADJECTIVES = {
    'ужасный', 'жуткий', 'страшный', 'сильный', 'слабый',
    'большой', 'маленький', 'плохой', 'хороший', 'обычный',
    'постоянный'
}


def split_sentences(text):
    """Разбивает текст на предложения"""
    if not text:
        return []
    parts = re.split(r"[.!?\n;:]+", text.lower())
    return [p.strip() for p in parts if p.strip()]


def normalize_word(word):
    try:
        parsed = morph.parse(word)[0]
        return parsed.normal_form, parsed.tag.POS
    except Exception:
        return word, None


def extract_candidates_from_sentence(sentence, medicine_name=None):
    """
    Извлекает кандидатов из предложения
    Возвращает список кортежей (нормализованный, оригинальный)
    """
    original_sentence = sentence  # сохраняем оригинал
    sentence = re.sub(r"[^\w\s-]", " ", sentence.lower())
    raw_words = sentence.split()
    original_words = original_sentence.lower().split()  # оригинальные слова

    medicine_norm = normalize_phrase(medicine_name) if medicine_name else ""
    medicine_words = set(medicine_norm.split())

    words = []
    pos_tags = []
    original_forms = []

    for i, word in enumerate(raw_words):
        word = word.strip("-")
        orig_word = original_words[i].strip("-") if i < len(original_words) else word
        if len(word) < 3:
            continue
        if word in STOP_WORDS:
            continue

        normalized, pos = normalize_word(word)

        if len(normalized) < 3:
            continue
        if normalized in STOP_WORDS:
            continue
        if normalized in medicine_words:
            continue
        if pos not in {"NOUN", "ADJF", "ADJS"}:
            continue
        if pos in {"ADJF", "ADJS"} and normalized in BAD_ADJECTIVES:
            continue

        words.append(normalized)
        pos_tags.append(pos)
        original_forms.append(orig_word)

    candidates = []  # теперь список кортежей (норм, ориг)

    for i, (word, pos) in enumerate(zip(words, pos_tags)):
        # Одиночные существительные
        if pos == "NOUN":
            candidates.append((word, original_forms[i]))

        if i < len(words) - 1:
            w1, p1 = words[i], pos_tags[i]
            w2, p2 = words[i + 1], pos_tags[i + 1]
            orig1, orig2 = original_forms[i], original_forms[i + 1]

            # прилагательное + существительное
            if p1 in {"ADJF", "ADJS"} and p2 == "NOUN":
                candidates.append((f"{w1} {w2}", f"{orig1} {orig2}"))

            # существительное + существительное
            elif p1 == "NOUN" and p2 == "NOUN":
                candidates.append((f"{w1} {w2}", f"{orig1} {orig2}"))

    # Убираем дубликаты по нормализованной форме
    unique = {}
    for norm, orig in candidates:
        if norm not in unique:
            unique[norm] = orig
        else:
            # Если уже есть, оставляем более длинный оригинал
            if len(orig) > len(unique[norm]):
                unique[norm] = orig

    candidates= [(norm, orig) for norm, orig in unique.items()]
    filtered_candidates = []
    for norm, orig in candidates:
        if is_medical_term(norm):
            filtered_candidates.append((norm, orig))
            print(f" УРААА нашли медицинский: '{norm}' (ориг: '{orig}')")
        else:
            print(f"   🗑️ Отброшен (не медицинский): '{norm}' (ориг: '{orig}')")

    return filtered_candidates


def build_and_save_links(medicine, db_path='medical_data.db'):
    """
    Главная функция:
    1. Берёт отзывы из БД
    2. Разбивает на предложения
    3. Находит кандидатов вместе с предложениями
    4. Сохраняет в БД (связи + предложения)
    """
    print(f"🔍 Начало обработки для {medicine}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Таблица для связей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS drug_symptom_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            symptom TEXT,
            original_symptom TEXT,
            weight INTEGER DEFAULT 1,
            UNIQUE(medicine_id, symptom)
        )
    ''')

    try:
        cursor.execute("ALTER TABLE drug_symptom_links ADD COLUMN original_symptom TEXT")
    except:
        pass

    # Таблица для предложений
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS symptom_sentences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            symptom TEXT NOT NULL,
            original_symptom TEXT,
            sentence TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try:
        cursor.execute("ALTER TABLE symptom_sentences ADD COLUMN original_symptom TEXT")
    except:
        pass

    # Приводим поисковый запрос к нижнему регистру
    search_term = medicine.lower().strip()

    # Получаем отзывы через LIKE (частичное совпадение)
    cursor.execute('''
        SELECT reviews.review_text, reviews.medicine_id, medicines.medicine_name
        FROM reviews
        JOIN medicines ON medicines.id = reviews.medicine_id
        WHERE reviews.review_text != "" AND LOWER(medicines.medicine_name) LIKE ?
    ''', (f'%{search_term}%',))
    rows = cursor.fetchall()

    if not rows:
        conn.close()
        print(f"❌ Нет отзывов для '{medicine}'")
        return {}

    medicine_id = rows[0][1]

    cursor.execute('DELETE FROM drug_symptom_links WHERE medicine_id = ?', (medicine_id,))
    cursor.execute('DELETE FROM symptom_sentences WHERE medicine_id = ?', (medicine_id,))

    # Словари для сбора данных
    candidate_sentences = defaultdict(list)  # {кандидат: [предложения]}
    candidate_freq = defaultdict(int)        # {кандидат: частота}
    candidate_original = defaultdict(str)    # {кандидат: оригинальная фраза}

    for review_text, med_id, med_name in rows:
        if not review_text:
            continue

        sentences = split_sentences(review_text)

        for sentence in sentences:
            if len(sentence) < 10:
                continue

            candidates = extract_candidates_from_sentence(sentence, medicine_name=medicine)

            for norm, orig in candidates:
                candidate_freq[norm] += 1
                if sentence not in candidate_sentences[norm]:
                    candidate_sentences[norm].append(sentence)
                if candidate_original[norm] == "":
                    candidate_original[norm] = orig

    # Строим граф для TextRank
    G = nx.Graph()

    for candidate in candidate_freq:
        G.add_node(candidate)

    for review_text, med_id, med_name in rows:
        if not review_text:
            continue

        sentences = split_sentences(review_text)

        for sentence in sentences:
            if len(sentence) < 10:
                continue

            candidates = extract_candidates_from_sentence(sentence, medicine_name=medicine)
            norm_candidates = [norm for norm, orig in candidates]

            for a, b in itertools.combinations(set(norm_candidates), 2):
                if G.has_edge(a, b):
                    G[a][b]["weight"] += 1
                else:
                    G.add_edge(a, b, weight=1)

    # Запускаем PageRank
    if G.number_of_edges() > 0:
        pr_scores = nx.pagerank(G, weight="weight")
    else:
        pr_scores = {node: 1 / len(G.nodes()) for node in G.nodes()} if G.nodes() else {}

    max_freq = max(candidate_freq.values()) if candidate_freq else 1
    final_scores = {}
    for candidate in candidate_freq:
        pr = pr_scores.get(candidate, 0)
        freq_score = candidate_freq[candidate] / max_freq
        final_scores[candidate] = 0.7 * pr + 0.3 * freq_score

    ranked_candidates = dict(sorted(final_scores.items(), key=lambda x: x[1], reverse=True))

    # Сохраняем в БД
    for symptom, score in ranked_candidates.items():
        scaled_weight = max(1, int(score * 100000))
        original = candidate_original.get(symptom, symptom)

        cursor.execute('''
            INSERT INTO drug_symptom_links (medicine_id, symptom, original_symptom, weight)
            VALUES (?, ?, ?, ?)
        ''', (medicine_id, symptom, original, scaled_weight))

        for sentence in candidate_sentences.get(symptom, [])[:2]:
            cursor.execute('''
                INSERT INTO symptom_sentences (medicine_id, symptom, original_symptom, sentence)
                VALUES (?, ?, ?, ?)
            ''', (medicine_id, symptom, original, sentence))

    conn.commit()
    conn.close()

    print(f"✅ Сохранено {len(ranked_candidates)} кандидатов для '{medicine}'")
    return ranked_candidates