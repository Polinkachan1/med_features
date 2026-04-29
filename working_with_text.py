import re
import pymorphy2

morph = pymorphy2.MorphAnalyzer()

# СВОЙ СПИСОК СТОП-СЛОВ (без nltk)
STOP_WORDS = {
    # Междометия и частицы
    'ой', 'ах', 'эх', 'ух', 'ну', 'вот', 'да', 'нет', 'ага', 'угу',
    'же', 'бы', 'ли', 'разве', 'неужели', 'и', 'или', 'но', 'а', 'зато',
    'чтобы', 'потому', 'так', 'как', 'будто', 'словно', 'ведь', 'даже',

    # Наречия (ненужные для симптомов)
    'очень', 'сильно', 'слабо', 'быстро', 'медленно', 'постоянно',
    'всегда', 'никогда', 'иногда', 'редко', 'часто', 'уже', 'ещё',
    'просто', 'прямо', 'едва', 'чуть', 'слишком', 'совсем', 'вдруг',
    'наконец', 'сразу', 'теперь', 'потом', 'сначала', 'пока',

    # Предлоги
    'без', 'до', 'для', 'за', 'из', 'к', 'на', 'над', 'о', 'об', 'от',
    'по', 'под', 'при', 'про', 'с', 'у', 'через', 'между', 'перед',

    # Местоимения
    'я', 'ты', 'он', 'она', 'оно', 'мы', 'вы', 'они',
    'мой', 'твой', 'его', 'её', 'наш', 'ваш', 'их',
    'этот', 'тот', 'такой', 'какой', 'который', 'весь', 'сам',
    'себя', 'другой', 'каждый', 'любой', 'некоторый', 'это',

    # Вопросительные слова
    'что', 'кто', 'где', 'куда', 'откуда', 'зачем', 'почему', 'как',
    'сколько', 'почему', 'отчего', 'когда',

    # Вводные слова
    'конечно', 'возможно', 'наверное', 'кажется', 'значит', 'итак',
    'во-первых', 'во-вторых', 'например', 'вообще', 'действительно',
    'правда', 'вероятно', 'очевидно', 'безусловно',

    # Глаголы-связки и общие действия
    'быть', 'стать', 'являться', 'оказаться', 'находиться',
    'начать', 'стать', 'продолжать', 'бросить', 'перестать',
    'мочь', 'хотеть', 'должен', 'обязан',

    # Слова, связанные с приёмом препарата
    'акнекутан', 'акнекутаный', 'акнекута', 'препарат', 'лекарство',
    'таблетка', 'укол', 'лечение', 'приём', 'доза', 'курс',
    'месяц', 'день', 'неделя', 'год', 'время', 'час', 'минута',

    # Слова-паразиты из отзывов
    'сказать', 'говорить', 'думать', 'знать', 'понимать', 'казаться',
    'помочь', 'спасти', 'рекомендовать', 'посоветовать', 'попробовать',
    'случиться', 'произойти', 'случаться', 'бывать'
}


def is_meaningful_pos(pos):
    """
    Значимые части речи для симптомов:
    - существительные (NOUN)
    - прилагательные (ADJF, ADJS)
    - глаголы в личной форме (VERB) и инфинитивы (INFN)
    """
    meaningful = {'NOUN', 'ADJF', 'ADJS', 'VERB', 'INFN'}
    return pos in meaningful


def clean_text_for_side_effects(text):
    if not text:
        return ""

    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\d+', '', text)

    words = text.split()
    cleaned_words = []

    for word in words:
        if len(word) < 3:
            continue

        if word in STOP_WORDS:
            continue

        try:
            parsed = morph.parse(word)[0]
            pos = parsed.tag.POS

            if not is_meaningful_pos(pos):
                continue

            normalized = parsed.normal_form
            cleaned_words.append(normalized)

        except Exception:
            if len(word) > 3:
                cleaned_words.append(word)

    return ' '.join(cleaned_words)


def normalize_phrase(phrase):
    """Приводит фразу к нормальной форме"""
    if not phrase:
        return ""

    words = phrase.split()
    normalized = []

    for word in words:
        try:
            parsed = morph.parse(word)[0]
            normalized.append(parsed.normal_form)
        except Exception:
            normalized.append(word)

    return ' '.join(normalized)


def extract_phrases_from_cleaned_text(text, max_phrase_length=2):
    """Из очищенного текста извлекает фразы (униграммы и биграммы)"""
    words = text.split()

    if len(words) == 0:
        return []
    if len(words) == 1:
        return words

    phrases = []
    # Одиночные слова
    phrases.extend(words)

    # Биграммы (пары слов)
    for i in range(len(words) - 1):
        phrases.append(f"{words[i]} {words[i+1]}")

    # Триграммы (если нужно)
    if max_phrase_length >= 3:
        for i in range(len(words) - 2):
            phrases.append(f"{words[i]} {words[i+1]} {words[i+2]}")

    return list(set(phrases))

