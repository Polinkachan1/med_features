import sqlite3
import json
import os
import re
import time
from random import randint
from time import sleep
from typing import List, Dict, Tuple, Optional

import pymorphy2
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

from working_with_text import normalize_phrase, STOP_WORDS

DB_PATH = 'medical_data.db'
JSON_PATH = 'side_e_dataset.json'
MODEL_PATH = "./rubioroberta_side_effect_classifier"

# Загружаем модель один раз
print("🔄 Загрузка модели rubioroberta...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)
print("✅ Модель загружена")

morph = pymorphy2.MorphAnalyzer()

BAD_ADJECTIVES = {
    'ужасный', 'жуткий', 'страшный', 'сильный', 'слабый',
    'большой', 'маленький', 'плохой', 'хороший', 'обычный',
    'постоянный', 'временный', 'редкий', 'частый'
}


def is_medical_term(text: str) -> bool:
    """Проверка медицинского термина моделью rubioroberta"""
    if not text or len(text) < 3:
        return False

    try:
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=128)
        with torch.no_grad():
            outputs = model(**inputs)
        return torch.argmax(outputs.logits, dim=1).item() == 1
    except Exception as e:
        print(f"      ⚠️ Ошибка модели: {e}")
        return False


def split_sentences(text: str) -> List[str]:
    """Разбивает текст на предложения"""
    if not text:
        return []
    parts = re.split(r"[.!?\n;:]+", text)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 15]


def normalize_word(word: str) -> Tuple[str, str]:
    """Нормализует слово"""
    try:
        parsed = morph.parse(word)[0]
        return parsed.normal_form, parsed.tag.POS
    except Exception:
        return word, None


def extract_candidates_from_sentence(sentence: str, medicine_name: str = None) -> List[Tuple[str, str]]:
    """Извлекает кандидатов из предложения"""
    try:
        original_sentence = sentence
        sentence = re.sub(r"[^\w\s-]", " ", sentence.lower())
        raw_words = sentence.split()
        original_words = original_sentence.lower().split()

        medicine_norm = normalize_phrase(medicine_name) if medicine_name else ""
        medicine_words = set(medicine_norm.split())

        words = []
        pos_tags = []
        original_forms = []

        for i, word in enumerate(raw_words):
            word = word.strip("-")
            orig_word = original_words[i].strip("-") if i < len(original_words) else word

            if len(word) < 3 or word in STOP_WORDS:
                continue

            normalized, pos = normalize_word(word)

            if len(normalized) < 3 or normalized in STOP_WORDS:
                continue
            if medicine_words and normalized in medicine_words:
                continue
            if pos not in {"NOUN", "ADJF", "ADJS"}:
                continue
            if pos in {"ADJF", "ADJS"} and normalized in BAD_ADJECTIVES:
                continue

            words.append(normalized)
            pos_tags.append(pos)
            original_forms.append(orig_word)

        candidates = []

        for i, (word, pos) in enumerate(zip(words, pos_tags)):
            if pos == "NOUN":
                candidates.append((word, original_forms[i]))

            if i < len(words) - 1:
                w1, p1 = words[i], pos_tags[i]
                w2, p2 = words[i + 1], pos_tags[i + 1]
                orig1, orig2 = original_forms[i], original_forms[i + 1]

                if p1 in {"ADJF", "ADJS"} and p2 == "NOUN":
                    candidates.append((f"{w1} {w2}", f"{orig1} {orig2}"))
                elif p1 == "NOUN" and p2 == "NOUN":
                    candidates.append((f"{w1} {w2}", f"{orig1} {orig2}"))

        unique = {}
        for norm, orig in candidates:
            if norm not in unique or len(orig) > len(unique[norm]):
                unique[norm] = orig

        return [(norm, orig) for norm, orig in unique.items()]
    except Exception as e:
        return []


def save_processed_sentence(medicine_id, sentence, original_sentence, normalized_sentence):
    """Сохраняет обработанное предложение в БД"""
    try:
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
    except Exception as e:
        return None


def save_candidate_symptom(medicine_id, sentence_id, candidate_norm, candidate_original, is_medical):
    """Сохраняет кандидата в БД"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, frequency FROM candidate_symptoms 
            WHERE medicine_id = ? AND candidate_norm = ? AND sentence_id = ?
        ''', (medicine_id, candidate_norm, sentence_id))
        existing = cursor.fetchone()

        if existing:
            cursor.execute('UPDATE candidate_symptoms SET frequency = frequency + 1 WHERE id = ?', (existing[0],))
        else:
            cursor.execute('''
                INSERT INTO candidate_symptoms (medicine_id, sentence_id, candidate_norm, candidate_original, is_medical)
                VALUES (?, ?, ?, ?, ?)
            ''', (medicine_id, sentence_id, candidate_norm, candidate_original, is_medical))

        conn.commit()
        conn.close()
    except Exception as e:
        pass


def process_single_review(medicine_id: int, medicine_name: str, review_text: str):
    """Обрабатывает один отзыв"""
    if not review_text or len(review_text) < 50:
        return 0

    sentences = split_sentences(review_text)
    sentence_count = 0

    for sentence in sentences:
        try:
            normalized = normalize_phrase(sentence)
            sentence_id = save_processed_sentence(medicine_id, sentence, sentence, normalized)

            if sentence_id is None:
                continue

            candidates = extract_candidates_from_sentence(sentence, medicine_name)

            for candidate_norm, candidate_orig in candidates:
                is_medical = is_medical_term(candidate_norm)
                if is_medical:
                    save_candidate_symptom(medicine_id, sentence_id, candidate_norm, candidate_orig, is_medical)

            sentence_count += 1
        except Exception as e:
            continue

    return sentence_count


def get_drug_id_from_db(drug_name: str) -> Optional[int]:
    """Получает ID препарата из БД"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM medicines WHERE medicine_name = ?', (drug_name,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        return None


def get_all_drugs_from_json() -> List[str]:
    """Загружает список препаратов из JSON"""
    if not os.path.exists(JSON_PATH):
        print(f"❌ Файл {JSON_PATH} не найден")
        return []

    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    drugs = []
    for item in data:
        drug_name = item.get('drug_name_ru', '').strip().lower()
        if drug_name and len(drug_name) > 2:
            drugs.append(drug_name)

    return drugs


def process_drug_from_db(drug_name: str):
    """
    Обрабатывает препарат из БД (без парсинга, только извлечение симптомов из отзывов)
    """
    print("=" * 70)
    print(f"🔍 ОБРАБОТКА ПРЕПАРАТА ИЗ БД: {drug_name}")
    print("=" * 70)

    drug_name_lower = drug_name.lower().strip()

    # Получаем ID препарата
    drug_id = get_drug_id_from_db(drug_name_lower)
    if not drug_id:
        print(f"❌ Препарат '{drug_name}' не найден в БД!")
        return

    print(f"✅ Препарат найден, ID: {drug_id}")

    # Получаем все отзывы из БД
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, review_text FROM reviews WHERE medicine_id = ?', (drug_id,))
    reviews = cursor.fetchall()
    conn.close()

    if not reviews:
        print(f"⚠️ Нет отзывов для препарата '{drug_name}'")
        print(f"   Сначала добавь отзывы через парсер")
        return

    print(f"📊 Найдено отзывов: {len(reviews)}")
    print(f"🔍 Извлечение симптомов из отзывов...")

    sentence_count = 0
    for review_idx, (review_id, review_text) in enumerate(reviews):
        print(f"\n   Отзыв {review_idx + 1}/{len(reviews)} (ID: {review_id})")
        if not review_text or len(review_text) < 50:
            print(f"      ⚠️ Отзыв слишком короткий, пропускаем")
            continue

        sentences_before = len(split_sentences(review_text))
        print(f"      Предложений в отзыве: {sentences_before}")

        processed = process_single_review(drug_id, drug_name_lower, review_text)
        sentence_count += processed
        print(f"      ✅ Обработано предложений: {processed}")

    print(f"\n✅ Готово! Обработано предложений: {sentence_count}")

    # Считаем результат
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM candidate_symptoms WHERE medicine_id = ?', (drug_id,))
    candidate_count = cursor.fetchone()[0]
    conn.close()

    print(f"✅ Найдено медицинских терминов: {candidate_count}")


def process_all_drugs_from_json():
    """
    Обрабатывает ВСЕ препараты из side_e_dataset.json, у которых есть отзывы в БД
    """
    print("=" * 70)
    print("🚀 ОБРАБОТКА ВСЕХ ПРЕПАРАТОВ ИЗ side_e_dataset.json")
    print("=" * 70)

    # 1. Загружаем препараты из JSON
    drugs_from_json = get_all_drugs_from_json()

    if not drugs_from_json:
        print("❌ Нет препаратов для обработки")
        return

    print(f"📖 Загружено {len(drugs_from_json)} препаратов из JSON")

    # 2. Обрабатываем каждый препарат
    total_processed = 0
    total_with_reviews = 0
    total_sentences = 0
    total_candidates = 0

    for i, drug_name in enumerate(drugs_from_json):
        print(f"\n{'=' * 50}")
        print(f"[{i + 1}/{len(drugs_from_json)}] {drug_name}")
        print(f"{'=' * 50}")

        # Проверяем, есть ли препарат в БД
        drug_id = get_drug_id_from_db(drug_name)
        if not drug_id:
            print(f"   ⚠️ Препарат не найден в БД, пропускаем")
            continue

        # Проверяем, есть ли отзывы
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM reviews WHERE medicine_id = ?', (drug_id,))
        reviews_count = cursor.fetchone()[0]
        conn.close()

        if reviews_count == 0:
            print(f"   ⚠️ Нет отзывов для '{drug_name}', пропускаем")
            continue

        print(f"   📊 Отзывов: {reviews_count}")

        # Очищаем старые данные
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM candidate_symptoms WHERE medicine_id = ?', (drug_id,))
            cursor.execute('DELETE FROM processed_sentences WHERE medicine_id = ?', (drug_id,))
            conn.commit()
            conn.close()
            print(f"   🗑️ Старые данные очищены")
        except:
            pass

        # Получаем все отзывы
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id, review_text FROM reviews WHERE medicine_id = ?', (drug_id,))
        reviews = cursor.fetchall()
        conn.close()

        print(f"   🔍 Начинаем обработку {len(reviews)} отзывов...")

        # Обрабатываем каждый отзыв
        drug_sentences = 0
        for review_idx, (review_id, review_text) in enumerate(reviews):
            if review_idx % 5 == 0:
                print(f"      Прогресс: {review_idx + 1}/{len(reviews)} отзывов")

            if not review_text or len(review_text) < 50:
                continue

            drug_sentences += process_single_review(drug_id, drug_name, review_text)

        # Считаем результат
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM candidate_symptoms WHERE medicine_id = ?', (drug_id,))
        candidate_count = cursor.fetchone()[0]
        conn.close()

        total_processed += 1
        total_with_reviews += reviews_count
        total_sentences += drug_sentences
        total_candidates += candidate_count

        print(f"   ✅ Предложений: {drug_sentences}, Медтерминов: {candidate_count}")

        time.sleep(0.5)

    # Итог
    print("\n" + "=" * 70)
    print("📊 ИТОГОВАЯ СТАТИСТИКА:")
    print(f"   ✅ Обработано препаратов: {total_processed}")
    print(f"   📝 Всего отзывов: {total_with_reviews}")
    print(f"   📖 Всего предложений: {total_sentences}")
    print(f"   🔗 Всего медтерминов: {total_candidates}")
    print("=" * 70)


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        # Если запускаем с аргументом - обрабатываем один препарат
        drug_name = ' '.join(sys.argv[1:])
        process_drug_from_db(drug_name)
    else:
        # Иначе обрабатываем все препараты из side_e_dataset.json
        process_all_drugs_from_json()