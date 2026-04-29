import time
import sqlite3
from random import randint
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup


def get_driver():
    """Настраивает драйвер Chrome"""
    options = Options()
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument('--window-size=1920,1080')
    # Если хочешь без окна браузера, раскомментируй:
    # options.add_argument('--headless')

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def search_drug_on_irecommend(driver, drug_name):
    """Ищет препарат и возвращает URL страницы с отзывами (первый результат)"""
    search_url = f"https://irecommend.ru/srch?query={drug_name}"
    print(f"🔍 Поиск: {search_url}")

    driver.get(search_url)
    time.sleep(5)

    # Ищем первый результат (как в твоём коде)
    try:
        product_tizer = driver.find_element(By.CSS_SELECTOR, '.srch-result-nodes .ProductTizer')
        title_link = product_tizer.find_element(By.CSS_SELECTOR, '.title a')
        product_url = title_link.get_attribute('href')

        if not product_url.startswith('http'):
            product_url = f"https://irecommend.ru{product_url}"

        print(f"✅ Найдена страница препарата: {product_url}")
        return product_url
    except:
        print("❌ Результаты не найдены")
        return None


def get_review_links_from_page(driver, page_url):
    """Собирает ссылки на отзывы со страницы препарата"""
    print(f"\n📄 Сбор ссылок на отзывы...")
    driver.get(page_url)
    time.sleep(5)

    review_links = []
    all_links = driver.find_elements(By.TAG_NAME, "a")

    for link in all_links:
        href = link.get_attribute('href')
        if href and '/content/' in href and 'page=' not in href:
            if href == page_url or href == page_url.rstrip('/'):
                continue
            if href not in review_links and 'reviews' not in href:
                review_links.append(href)

    print(f"📊 Найдено ссылок на отзывы: {len(review_links)}")
    return review_links


def parse_review_page(driver, review_url):
    """Парсит страницу отзыва"""
    driver.get(review_url)
    time.sleep(4)

    try:
        # Заголовок
        title = ""
        try:
            title_elem = driver.find_element(By.CSS_SELECTOR, '.reviewTitle')
            title = title_elem.text.strip()
        except:
            pass

        # Текст отзыва
        review_text = ""
        try:
            text_elem = driver.find_element(By.CSS_SELECTOR, '.description[itemprop="reviewBody"]')
            review_text = text_elem.text.strip()
        except:
            pass

        # Достоинства
        plus = ""
        try:
            plus_items = driver.find_elements(By.CSS_SELECTOR, '.plus ul li span[itemprop="name"]')
            plus = "\n".join([item.text.strip() for item in plus_items])
        except:
            pass

        # Недостатки (важны для побочек)
        minus = ""
        try:
            minus_items = driver.find_elements(By.CSS_SELECTOR, '.minus ul li span[itemprop="name"]')
            minus = "\n".join([item.text.strip() for item in minus_items])
        except:
            pass

        # Вердикт
        verdict = ""
        try:
            verdict_elem = driver.find_element(By.CSS_SELECTOR, '.conclusion .verdict')
            verdict = verdict_elem.text.strip()
        except:
            pass

        # Опыт использования
        usage_experience = ""
        try:
            exp_label = driver.find_element(By.XPATH, "//*[contains(text(), 'Опыт использования:')]")
            parent = exp_label.find_element(By.XPATH, "./following-sibling::div[@class='item-data']")
            usage_experience = parent.text.strip()
        except:
            pass

        # Формируем полный текст
        full_text = f"{title}\n\n{review_text}\n\nДостоинства: {plus}\n\nНедостатки: {minus}\n\nВердикт: {verdict}\n\nОпыт использования: {usage_experience}"

        return {
            'text': full_text[:5000],
            'review_text': review_text[:3000],
            'url': review_url,
            'title': title,
            'plus': plus,
            'minus': minus,
            'verdict': verdict,
            'usage_experience': usage_experience
        }

    except Exception as e:
        print(f"   ❌ Ошибка парсинга: {e}")
        return None


def save_review_to_db(drug_name, review_data, db_path='medical_data.db'):
    """Сохраняет отзыв в базу данных"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('SELECT id FROM medicines WHERE medicine_name = ?', (drug_name.lower(),))
    result = cursor.fetchone()

    if not result:
        conn.close()
        return False

    medicine_id = result[0]
    review_url = review_data.get('url')

    full_text = f"""Заголовок: {review_data.get('title', '')}

Текст отзыва: {review_data.get('review_text', '')}

Достоинства: {review_data.get('plus', '')}

Недостатки: {review_data.get('minus', '')}

Вердикт: {review_data.get('verdict', '')}

Опыт использования: {review_data.get('usage_experience', '')}"""

    if review_url:
        existing = cursor.execute('''
            SELECT 1 FROM reviews WHERE medicine_id = ? AND url = ?
        ''', (medicine_id, review_url)).fetchone()
        if existing:
            conn.close()
            return False

    try:
        cursor.execute('''
            INSERT INTO reviews (medicine_id, review_text, source, url)
            VALUES (?, ?, ?, ?)
        ''', (medicine_id, full_text[:5000], 'irecommend', review_url))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")
        conn.close()
        return False


def parse_drug_reviews(drug_name, max_reviews=20):
    """Главная функция парсинга"""
    print(f"\n{'=' * 60}")
    print(f"🔍 Парсинг отзывов для '{drug_name}'")
    print(f"{'=' * 60}")

    driver = get_driver()

    try:
        # 1. Находим страницу препарата
        drug_page_url = search_drug_on_irecommend(driver, drug_name)

        if not drug_page_url:
            print(f"❌ Не найдена страница препарата '{drug_name}'")
            return 0

        # 2. Собираем ссылки на отзывы
        review_links = get_review_links_from_page(driver, drug_page_url)

        if not review_links:
            print(f"❌ Не найдено отзывов")
            return 0

        print(f"📊 Найдено ссылок на отзывы: {len(review_links)}")

        # 3. Парсим отзывы
        saved = 0
        for i, link in enumerate(review_links[:max_reviews]):
            print(f"\n   [{i + 1}/{min(max_reviews, len(review_links))}]")

            review_data = parse_review_page(driver, link)

            if review_data and review_data.get('review_text'):
                if save_review_to_db(drug_name, review_data):
                    saved += 1
                    print("      ✅ Сохранён")
                    if review_data.get('minus'):
                        print(f"      📝 Минусы: {review_data['minus'][:100]}...")
                else:
                    print("      ⚠️ Уже есть в БД")
            else:
                print("      ❌ Не удалось спарсить")

            time.sleep(randint(3, 6))

        print(f"\n📊 ИТОГО сохранено: {saved} отзывов для '{drug_name}'")
        return saved

    finally:
        driver.quit()


def parse_all_drugs_from_json(max_reviews_per_drug=10):
    """
    Парсит отзывы для ВСЕХ препаратов из side_e_dataset.json
    """
    import json
    import os
    from time import sleep

    JSON_PATH = 'side_e_dataset.json'

    # 1. Загружаем препараты из JSON
    if not os.path.exists(JSON_PATH):
        print(f"❌ Файл {JSON_PATH} не найден")
        return

    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    drugs_from_json = []
    for item in data:
        drug_name = item.get('drug_name_ru', '').strip().lower()
        if drug_name and len(drug_name) > 2:
            drugs_from_json.append(drug_name)

    print(f"\n{'=' * 70}")
    print(f"🚀 ПАРСИНГ ОТЗЫВОВ ДЛЯ {len(drugs_from_json)} ПРЕПАРАТОВ")
    print(f"{'=' * 70}")

    # Статистика
    total_parsed = 0
    total_reviews = 0

    # Запускаем парсинг для каждого препарата
    for i, drug_name in enumerate(drugs_from_json):
        print(f"\n{'=' * 50}")
        print(f"[{i + 1}/{len(drugs_from_json)}] Парсинг: {drug_name}")
        print(f"{'=' * 50}")

        try:
            # Проверяем, есть ли препарат в БД
            conn = sqlite3.connect('medical_data.db')
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM medicines WHERE medicine_name = ?', (drug_name,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                print(f"   ⚠️ Препарат не найден в БД, пропускаем")
                continue

            # Парсим отзывы
            saved = parse_drug_reviews(drug_name, max_reviews=max_reviews_per_drug)

            if saved > 0:
                total_parsed += 1
                total_reviews += saved

            # Пауза между препаратами
            sleep(randint(10, 15))

        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
            continue

    # Итог
    print("\n" + "=" * 70)
    print("📊 ИТОГОВАЯ СТАТИСТИКА:")
    print(f"   ✅ Обработано препаратов: {total_parsed}")
    print(f"   📝 Всего сохранено отзывов: {total_reviews}")
    print("=" * 70)


if __name__ == '__main__':
    parse_all_drugs_from_json(max_reviews_per_drug=10)

