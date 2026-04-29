import json
import sqlite3
from random import randint
from time import sleep
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://protabletky.ru"
DB_PATH = "medical_data.db"
JSON_PATH = 'of_pobochki.json'

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)


def request_page(url, retries=3, timeout=30):
    """Загружает страницу."""
    for attempt in range(1, retries + 1):
        try:
            sleep(randint(3, 6))
            response = session.get(url, timeout=timeout)

            print(f"   HTTP {response.status_code}: {url}")

            if response.status_code == 200:
                return response.text

            if response.status_code in (403, 429, 521):
                print(f"   ❌ Сайт не дал доступ. Код: {response.status_code}")
                return None

        except requests.exceptions.RequestException as e:
            print(f"   ⚠️ Попытка {attempt}: {e}")

    return None


def init_db(db_path=DB_PATH):
    """Создаёт таблицы, если их нет."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS medicines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_name TEXT UNIQUE NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            review_text TEXT NOT NULL,
            source TEXT,
            url TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (medicine_id) REFERENCES medicines(id)
        )
    ''')

    conn.commit()
    conn.close()


def get_or_create_medicine(drug_name, db_path=DB_PATH):
    """Находит препарат в БД или создаёт его."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    medicine_name = drug_name.strip().lower()

    cursor.execute(
        "INSERT OR IGNORE INTO medicines (medicine_name) VALUES (?)",
        (medicine_name,)
    )
    conn.commit()

    cursor.execute(
        "SELECT id FROM medicines WHERE medicine_name = ?",
        (medicine_name,)
    )
    result = cursor.fetchone()
    conn.close()

    if result:
        return result[0]

    return None


def make_slug_from_name(drug_name):
    """
    Делает slug для ссылки.
    Для 'Атаракс' сайт использует /atarax/, поэтому для русского названия
    лучше передавать slug в JSON, если он есть.
    """
    return quote(drug_name.strip().lower().replace(" ", "-"))


def make_drug_url(drug):
    """
    Делает ссылку на ProTabletky из твоего JSON.

    Твой JSON выглядит так:
    {
        "drug_name_ru": "Апиксабан",
        "drug_name_en": "Apixaban"
    }

    ProTabletky обычно использует английское название в ссылке:
    Atarax -> https://protabletky.ru/atarax/
    """
    if isinstance(drug, dict):
        slug = (
            drug.get("slug")
            or drug.get("url")
            or drug.get("drug_name_en")
            or drug.get("drug_name_ru")
            or drug.get("name")
        )
    else:
        slug = drug

    slug = str(slug).strip()

    if slug.startswith("http"):
        return slug

    slug = slug.lower().replace(" ", "-").replace("+", "-")
    slug = quote(slug.strip("/"))

    return f"{BASE_URL}/{slug}/"


def get_drug_name_from_json_item(drug):
    """Берёт русское название из твоего JSON."""
    if isinstance(drug, dict):
        return (
            drug.get("drug_name_ru")
            or drug.get("name")
            or drug.get("medicine_name")
            or drug.get("title")
            or drug.get("drug_name_en")
            or drug.get("slug")
        )

    return str(drug)


def load_medicines_from_json(json_path=JSON_PATH):
    """Загружает список лекарств из JSON."""
    with open(json_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, dict):
        if "medicines" in data:
            return data["medicines"]
        if "drugs" in data:
            return data["drugs"]

    return data


def parse_rating(review):
    """Достаёт рейтинг отзыва."""
    rating_meta = review.select_one('[itemprop="reviewRating"] meta[itemprop="ratingValue"]')
    if rating_meta:
        return rating_meta.get("content", "").strip()

    return ""


def parse_doctor_info(review):
    """Достаёт имя врача и специальность."""
    doctor_name = ""
    specialty = ""
    experience = ""

    name_elem = review.select_one('[itemprop="author"] [itemprop="name"]')
    if name_elem:
        doctor_name = name_elem.get_text(" ", strip=True)

    author_td = review.select_one('[itemprop="author"]')
    if author_td:
        lines = list(author_td.stripped_strings)

        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line and line not in cleaned_lines:
                cleaned_lines.append(line)

        if doctor_name in cleaned_lines:
            index = cleaned_lines.index(doctor_name)
            if index + 1 < len(cleaned_lines):
                specialty = cleaned_lines[index + 1]

        for line in cleaned_lines:
            if "стаж" in line.lower():
                experience = line
                break

    return doctor_name, specialty, experience


def parse_reviews_from_html(html, page_url):
    """Парсит отзывы с HTML страницы ProTabletky."""
    soup = BeautifulSoup(html, "lxml")

    reviews = []
    review_blocks = soup.select('tr[itemprop="review"]')

    for review in review_blocks:
        doctor_name, specialty, experience = parse_doctor_info(review)

        date = ""
        date_elem = review.select_one('[itemprop="datePublished"]')
        if date_elem:
            date = date_elem.get("content") or date_elem.get_text(" ", strip=True)

        rating = parse_rating(review)

        plus = ""
        plus_elem = review.select_one(".comment_plus")
        if plus_elem:
            plus = plus_elem.get_text(" ", strip=True)

        minus = ""
        minus_elem = review.select_one(".comment_minus")
        if minus_elem:
            minus = minus_elem.get_text(" ", strip=True)

        comment = ""
        comment_elem = review.select_one(".comment")
        if comment_elem:
            comment = comment_elem.get_text(" ", strip=True)

        review_id = ""
        anchor = review.select_one('a[id^="rate-"]')
        if anchor:
            review_id = anchor.get("id", "")

        if not plus and not minus and not comment:
            continue

        review_text = f"""Врач: {doctor_name}
Специальность: {specialty}
Опыт: {experience}
Дата: {date}
Рейтинг: {rating}

Плюсы: {plus}

Минусы: {minus}

Комментарий: {comment}"""

        if review_id:
            review_url = f"{page_url.rstrip('/')}/#{review_id}"
        else:
            review_url = page_url

        reviews.append({
            "doctor_name": doctor_name,
            "specialty": specialty,
            "experience": experience,
            "date": date,
            "rating": rating,
            "plus": plus,
            "minus": minus,
            "comment": comment,
            "review_text": review_text,
            "url": review_url,
        })

    return reviews


def save_review_to_db(drug_name, review_data, db_path=DB_PATH):
    """Сохраняет отзыв в БД."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM medicines WHERE medicine_name = ?",
        (drug_name.strip().lower(),)
    )
    result = cursor.fetchone()

    if not result:
        conn.close()
        return False

    medicine_id = result[0]
    review_url = review_data.get("url")
    review_text = review_data.get("review_text", "")[:5000]

    try:
        cursor.execute('''
            INSERT INTO reviews (medicine_id, review_text, source, url)
            VALUES (?, ?, ?, ?)
        ''', (medicine_id, review_text, "protabletky", review_url))
        conn.commit()
        conn.close()
        return True

    except sqlite3.IntegrityError:
        conn.close()
        return False

    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")
        conn.close()
        return False


def parse_drug_reviews(drug, max_reviews=20):
    """Парсит один препарат."""
    drug_name = get_drug_name_from_json_item(drug)
    page_url = make_drug_url(drug)

    print(f"\n{'=' * 60}")
    print(f"🔍 Парсинг: {drug_name}")
    print(f"🔗 URL: {page_url}")
    print(f"{'=' * 60}")

    get_or_create_medicine(drug_name)

    html = request_page(page_url)
    if not html:
        print("❌ Не удалось загрузить страницу")
        return 0

    reviews = parse_reviews_from_html(html, page_url)

    if not reviews:
        print("❌ Отзывы не найдены")
        return 0

    print(f"📊 Найдено отзывов на странице: {len(reviews)}")

    saved = 0
    for i, review_data in enumerate(reviews[:max_reviews], start=1):
        print(f"   [{i}/{min(max_reviews, len(reviews))}]", end=" ")

        if save_review_to_db(drug_name, review_data):
            saved += 1
            print("✅ сохранён")
        else:
            print("⚠️ уже есть или не сохранён")

    print(f"📊 ИТОГО сохранено: {saved}")
    return saved


def parse_all_medicines(json_path=JSON_PATH, max_reviews_per_drug=20):
    """Парсит все препараты из JSON."""
    init_db()

    medicines = load_medicines_from_json(json_path)
    total_saved = 0

    for drug in medicines:
        saved = parse_drug_reviews(drug, max_reviews=max_reviews_per_drug)
        total_saved += saved

    print(f"\n✅ ВСЕГО сохранено отзывов: {total_saved}")
    return total_saved


if __name__ == "__main__":
    # Для твоего файла side_e_dataset.json:
    parse_all_medicines('of_pobochki.json', max_reviews_per_drug=20)

    # Один препарат напрямую для теста:
    # parse_drug_reviews({"drug_name_ru": "Атаракс", "drug_name_en": "Atarax"}, max_reviews=20)
