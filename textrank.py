import sqlite3
import json
import matplotlib.pyplot as plt
import io
import base64
import networkx as nx
from working_with_text import normalize_phrase


# ============================================================
# ЗАГРУЗКА ДАННЫХ ИЗ БД
# ============================================================

def load_candidates(medicine_name: str, db_path: str = "medical_data.db"):
    """Загружает кандидатов из БД"""
    conn = sqlite3.connect(db_path)
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
    return results


def load_sentences(medicine_name: str, db_path: str = "medical_data.db"):
    """Загружает предложения из БД"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT ps.sentence, ps.original_sentence
        FROM processed_sentences ps
        JOIN medicines m ON ps.medicine_id = m.id
        WHERE LOWER(m.medicine_name) = ?
    ''', (medicine_name.lower(),))

    results = cursor.fetchall()
    conn.close()
    return results


def load_official_effects(medicine_name: str, db_path: str = "medical_data.db"):
    """Загружает официальные побочки"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT official_side_effects
        FROM medicines
        WHERE LOWER(medicine_name) = ?
    ''', (medicine_name.lower(),))

    row = cursor.fetchone()
    conn.close()

    if row and row[0]:
        try:
            return json.loads(row[0])
        except:
            return []
    return []


def load_all_candidates_with_sentences(medicine_name: str, db_path: str = "medical_data.db"):
    """Загружает ВСЕХ кандидатов с их предложениями для анализа связей"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT DISTINCT cs.candidate_norm, cs.candidate_original, ps.sentence
        FROM candidate_symptoms cs
        JOIN processed_sentences ps ON cs.sentence_id = ps.id
        JOIN medicines m ON cs.medicine_id = m.id
        WHERE LOWER(m.medicine_name) = ? AND cs.is_medical = 1
    ''', (medicine_name.lower(),))

    results = cursor.fetchall()
    conn.close()

    # Группируем по симптомам
    candidates_data = {}
    for norm, original, sentence in results:
        if norm not in candidates_data:
            candidates_data[norm] = {
                'original': original,
                'sentences': []
            }
        if sentence not in candidates_data[norm]['sentences']:
            candidates_data[norm]['sentences'].append(sentence)

    return candidates_data


# ============================================================
# ВЫЧИСЛЕНИЕ СХОЖЕСТИ
# ============================================================

def calculate_similarity(official: str, non_official: str) -> float:
    """Вычисляет схожесть между официальным и неофициальным симптомом"""
    official_norm = normalize_phrase(official)
    non_official_norm = normalize_phrase(non_official)

    # Точное совпадение
    if official_norm == non_official_norm:
        return 1.0

    # Проверка вхождения
    if official_norm in non_official_norm or non_official_norm in official_norm:
        return 0.85

    # Jaccard similarity
    words1 = set(official_norm.split())
    words2 = set(non_official_norm.split())

    if not words1 or not words2:
        return 0.0

    intersection = words1.intersection(words2)
    union = words1.union(words2)
    jaccard = len(intersection) / len(union) if union else 0

    if jaccard >= 0.5:
        return 0.8
    elif jaccard >= 0.3:
        return 0.6
    elif jaccard >= 0.15:
        return 0.4
    else:
        return jaccard * 0.5


# ============================================================
# АНАЛИЗ СВЯЗЕЙ МЕЖДУ СИМПТОМАМИ
# ============================================================

def find_connected_official_symptoms(official_effects: list, candidates_data: dict, similarity_threshold: float = 0.25):
    """
    Находит официальные симптомы, которые связаны с неофициальными (подтверждены в отзывах)
    Возвращает словарь: {официальный_симптом: {неофициальные_симптомы: [предложения]}}
    """
    connections = {}

    for official in official_effects:
        official_norm = normalize_phrase(official)
        found_matches = []

        for cand_norm, cand_data in candidates_data.items():
            score = calculate_similarity(official, cand_data['original'])

            if score >= similarity_threshold:
                found_matches.append({
                    'non_official': cand_data['original'],
                    'non_official_norm': cand_norm,
                    'sentences': cand_data['sentences'],
                    'similarity_score': score
                })

        if found_matches:
            connections[official] = found_matches

    return connections


def get_all_confirmed_official_with_sentences(official_effects: list, candidates_data: dict,
                                              similarity_threshold: float = 0.25):
    """
    Возвращает список подтверждённых официальных симптомов с примерами предложений
    Один официальный симптом может быть подтверждён несколькими предложениями
    """
    confirmed = []

    for official in official_effects:
        official_norm = normalize_phrase(official)
        all_sentences = []

        for cand_norm, cand_data in candidates_data.items():
            score = calculate_similarity(official, cand_data['original'])

            if score >= similarity_threshold:
                for sentence in cand_data['sentences']:
                    if sentence not in all_sentences:
                        all_sentences.append(sentence)

        if all_sentences:
            confirmed.append({
                'symptom': official,
                'sentences': all_sentences[:3]
            })

    return confirmed


# ============================================================
# ПОСТРОЕНИЕ ГРАФА
# ============================================================

def build_graph(drug_name: str, candidates: list, official_effects: list):
    """Строит расширенный граф связей"""
    G = nx.Graph()
    official_norm_set = set(normalize_phrase(e) for e in official_effects)

    # 1. Добавляем препарат
    G.add_node(drug_name, type='drug', original=drug_name)

    # 2. Добавляем официальные побочки
    official_nodes = []
    for effect in official_effects:
        effect_norm = normalize_phrase(effect)
        official_nodes.append(effect_norm)
        G.add_node(effect_norm, original=effect, type='official', is_official=True)
        G.add_edge(drug_name, effect_norm, weight=1.0)

    # 3. Добавляем неофициальные симптомы
    non_official_nodes = []
    for cand_norm, cand_orig, freq in candidates:
        if cand_norm not in official_norm_set:
            non_official_nodes.append(cand_norm)
            G.add_node(cand_norm, original=cand_orig, type='non_official',
                       is_official=False, frequency=freq)
            G.add_edge(drug_name, cand_norm, weight=min(1.0, freq / 100))

    # 4. Связываем официальные и неофициальные симптомы
    for official in official_nodes:
        official_orig = G.nodes[official]['original']
        for non_official in non_official_nodes:
            non_official_orig = G.nodes[non_official]['original']
            score = calculate_similarity(official_orig, non_official_orig)
            if score >= 0.25:
                G.add_edge(official, non_official, weight=score)

    # 5. Связываем похожие неофициальные симптомы между собой
    for i in range(len(non_official_nodes)):
        for j in range(i + 1, len(non_official_nodes)):
            orig1 = G.nodes[non_official_nodes[i]]['original']
            orig2 = G.nodes[non_official_nodes[j]]['original']
            score = calculate_similarity(orig1, orig2)
            if score >= 0.5:
                G.add_edge(non_official_nodes[i], non_official_nodes[j], weight=score * 0.7)

    return G


def rank_symptoms(G: nx.Graph, drug_name: str) -> list:
    """Ранжирует симптомы с помощью PageRank"""
    if G.number_of_edges() == 0:
        return []

    ranks = nx.pagerank(G, weight='weight')

    ranked = []
    for node, score in sorted(ranks.items(), key=lambda x: x[1], reverse=True):
        if node == drug_name:
            continue

        node_data = G.nodes[node]
        ranked.append({
            'name': node,
            'original': node_data.get('original', node),
            'score': score,
            'type': node_data.get('type', 'unknown'),
            'is_official': node_data.get('is_official', False),
            'frequency': node_data.get('frequency', 0)
        })

    return ranked


# ============================================================
# ВИЗУАЛИЗАЦИЯ
# ============================================================

def render_graph_to_html(G: nx.Graph, drug_name: str) -> str:
    """Рендерит граф в base64 HTML-картинку"""
    try:
        plt.figure(figsize=(14, 12))

        pos = nx.spring_layout(G, k=2, iterations=50, seed=42)

        # Цвета узлов
        node_colors = []
        for node in G.nodes():
            if node == drug_name:
                node_colors.append('#FF6B6B')
            elif G.nodes[node].get('type') == 'official':
                node_colors.append('#3498DB')
            else:
                node_colors.append('#F39C12')

        # Размеры узлов
        node_sizes = []
        for node in G.nodes():
            if node == drug_name:
                node_sizes.append(3500)
            elif G.nodes[node].get('type') == 'official':
                node_sizes.append(1800)
            else:
                freq = G.nodes[node].get('frequency', 50)
                node_sizes.append(1200 + min(freq, 300))

        nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=node_sizes, alpha=0.9)

        # Рёбра
        edges_drug = [(drug_name, n) for n in G.neighbors(drug_name)]
        edges_other = [(u, v) for u, v in G.edges() if u != drug_name and v != drug_name]

        nx.draw_networkx_edges(G, pos, edgelist=edges_drug, edge_color='gray', width=1.5, alpha=0.6)
        nx.draw_networkx_edges(G, pos, edgelist=edges_other, edge_color='orange', width=1, alpha=0.4, style='dashed')

        # Подписи
        labels = {}
        for node in G.nodes():
            if node == drug_name:
                labels[node] = drug_name.upper()
            else:
                original = G.nodes[node].get('original', node)
                labels[node] = original[:25] + '...' if len(original) > 25 else original

        nx.draw_networkx_labels(G, pos, labels, font_size=7, font_weight='bold')

        plt.title(f"Граф связей препарата {drug_name.upper()}", fontsize=12, fontweight='bold')
        plt.axis('off')

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close()

        return f"<img src='data:image/png;base64,{img_base64}' style='max-width: 100%; border: 1px solid #ddd; border-radius: 8px;'>"

    except Exception as e:
        print(f"Ошибка визуализации: {e}")
        return "<p>⚠️ Ошибка построения графа</p>"


# ============================================================
# HTML ФОРМАТТЕРЫ
# ============================================================

def format_error(drug_name: str) -> str:
    """Форматирует сообщение об ошибке"""
    return f"""
    <div style="background: #f0f7ff; padding: 20px; border-radius: 10px;">
        <h3>💊 Препарат: {drug_name.upper()}</h3>
        <p style="color: #e67e22;">⚠️ Данные для этого препарата ещё не обработаны.</p>
        <p>Пожалуйста, подождите или сообщите администратору.</p>
    </div>
    """


def format_official_effects(effects: list) -> str:
    """Форматирует список официальных побочек"""
    html = "<p><b>📋 Официальные побочки:</b> "
    html += ", ".join(effects) if effects else "нет"
    html += "</p>"
    return html


def format_confirmed_official(confirmed: list) -> str:
    """
    Форматирует подтверждённые официальные побочки
    Здесь показываем ТОЛЬКО те, у которых есть связь с неофициальными
    """
    if not confirmed:
        return """
        <div style="background: #e8f5e9; padding: 15px; border-radius: 10px; margin: 15px 0;">
            <h4 style="color: #2e7d32; margin-top: 0;">✅ Подтверждённые официальные побочки (найдены в отзывах):</h4>
            <p>Нет подтверждённых официальных побочек в отзывах</p>
        </div>
        """

    html = """
    <div style="background: #e8f5e9; padding: 15px; border-radius: 10px; margin: 15px 0;">
        <h4 style="color: #2e7d32; margin-top: 0;">✅ Подтверждённые официальные побочки (найдены в отзывах):</h4>
    """
    for item in confirmed:
        html += f"<p><b>{item['symptom']}</b><br>"
        for sentence in item['sentences']:
            html += f"<span style='color: #555; margin-left: 20px;'>📝 \"{sentence}\"</span><br>"
        html += "</p>"
    html += "</div>"
    return html


def format_non_official_sentences(connected_official: dict, similarity_threshold: float = 0.25) -> str:
    """
    Форматирует предложения с неофициальными симптомами, которые НЕ связаны с официальными
    Если неофициальный симптом связан с официальным, он уже показан в блоке выше
    """
    # Собираем все неофициальные симптомы, которые уже связаны с официальными
    connected_non_official = set()
    for official, matches in connected_official.items():
        for match in matches:
            connected_non_official.add(match['non_official_norm'])

    # Загружаем все неофициальные предложения, которые НЕ связаны с официальными
    # (эта логика требует отдельного запроса, упростим для примера)

    return ""


def format_non_official_sentences_simple(non_official_sentences: list) -> str:
    """Простой форматтер для неофициальных предложений"""
    if not non_official_sentences:
        return """
        <div style="background: #fff3e0; padding: 15px; border-radius: 10px; margin: 15px 0;">
            <h4 style="color: #e65100; margin-top: 0;">⚠️ Другие найденные симптомы (без связей с официальными):</h4>
            <p>Нет предложений</p>
        </div>
        """

    html = """
    <div style="background: #fff3e0; padding: 15px; border-radius: 10px; margin: 15px 0;">
        <h4 style="color: #e65100; margin-top: 0;">⚠️ Другие найденные симптомы (без связей с официальными):</h4>
    """
    for item in non_official_sentences[:15]:
        html += f"<p style='margin-bottom: 8px;'>📝 \"{item['sentence']}\"<br>"
        html += f"<span style='color: #e65100; margin-left: 20px;'>→ симптом: <b>{item['symptom']}</b></span></p>"
    html += "</div>"
    return html


def format_ranked_table(ranked: list) -> str:
    """Форматирует таблицу ранжированных симптомов"""
    if not ranked:
        return "<p>⚠️ Симптомы не найдены</p>"

    html = """
    <h4>📊 Все симптомы (ранжированные с учётом связей):</h4>
    <table style="border-collapse: collapse; width: 100%; margin-top: 10px;">
        <tr style="background: #3498db; color: white;">
            <th style="padding: 10px; text-align: left;">Ранг</th>
            <th style="padding: 10px; text-align: left;">Симптом</th>
            <th style="padding: 10px; text-align: center;">Score</th>
            <th style="padding: 10px; text-align: center;">Тип</th>
        </tr>
    """

    for i, symptom in enumerate(ranked[:30]):
        badge = "✅ Официальный" if symptom['is_official'] else "⚠️ Неофициальный"
        badge_color = "#2ecc71" if symptom['is_official'] else "#e67e22"

        html += f"""
        <tr>
            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{i + 1}</td>
            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><b>{symptom['original']}</b></td>
            <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: center;">{symptom['score']:.4f}</td>
            <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: center;">
                <span style="background: {badge_color}; color: white; padding: 2px 8px; border-radius: 15px; font-size: 12px;">
                    {badge}
                </span>
            </td>
        </tr>
        """
    html += "</table>"
    return html


def format_stats(G: nx.Graph, drug_name: str, ranked: list, confirmed_count: int, non_official_count: int) -> str:
    """Форматирует статистику"""
    official_in_graph = sum(1 for n in G.nodes() if G.nodes[n].get('type') == 'official')
    non_official_in_graph = sum(1 for n in G.nodes() if G.nodes[n].get('type') == 'non_official')

    return f"""
    <div style="background: #f8f9fa; padding: 10px; border-radius: 8px; margin-top: 20px; font-size: 12px; color: #666;">
        📊 <b>Статистика:</b><br>
        • Всего узлов в графе: {G.number_of_nodes()}<br>
        • Официальных побочек: {official_in_graph}<br>
        • Найденных в отзывах: {non_official_in_graph}<br>
        • Связей между симптомами: {len([e for e in G.edges() if e[0] != drug_name and e[1] != drug_name])}<br>
        • Подтверждённых официальных побочек в отзывах: {confirmed_count}<br>
        • Других найденных симптомов: {non_official_count}<br>
        • Всего ранжированных симптомов: {len(ranked)}
    </div>
    """


# ============================================================
# ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ НЕСВЯЗАННЫХ ПРЕДЛОЖЕНИЙ
# ============================================================

def get_unconnected_non_official_sentences(medicine_name: str, official_effects: list, candidates_data: dict,
                                           similarity_threshold: float = 0.25) -> list:
    """Возвращает предложения с неофициальными симптомами, которые НЕ связаны с официальными"""

    # Находим все неофициальные симптомы, которые связаны с официальными
    connected_non_official = set()
    for official in official_effects:
        for cand_norm, cand_data in candidates_data.items():
            score = calculate_similarity(official, cand_data['original'])
            if score >= similarity_threshold:
                connected_non_official.add(cand_norm)

    # Собираем предложения с несвязанными симптомами
    unconnected = []
    for cand_norm, cand_data in candidates_data.items():
        if cand_norm not in connected_non_official:
            for sentence in cand_data['sentences'][:2]:
                unconnected.append({
                    'sentence': sentence,
                    'symptom': cand_data['original'],
                    'symptom_norm': cand_norm
                })

    return unconnected[:20]


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ============================================================

def compare_feature(medicine_name: str, db_path: str = "medical_data.db") -> str:
    """
    Главная функция: загружает данные, строит граф, ранжирует, визуализирует
    """
    print(f"🔍 Загрузка данных для {medicine_name}...")

    # Загрузка данных
    candidates = load_candidates(medicine_name, db_path)

    if not candidates:
        return format_error(medicine_name)

    sentences = load_sentences(medicine_name, db_path)
    official_effects = load_official_effects(medicine_name, db_path)
    candidates_data = load_all_candidates_with_sentences(medicine_name, db_path)

    # 1. Находим подтверждённые официальные симптомы (те, у которых есть связь с неофициальными)
    confirmed_official = get_all_confirmed_official_with_sentences(official_effects, candidates_data,
                                                                   similarity_threshold=0.25)

    # 2. Находим неофициальные симптомы, которые НЕ связаны с официальными
    unconnected_sentences = get_unconnected_non_official_sentences(medicine_name, official_effects, candidates_data,
                                                                   similarity_threshold=0.25)

    # Построение графа и ранжирование
    G = build_graph(medicine_name, candidates, official_effects)
    ranked = rank_symptoms(G, medicine_name)

    # Визуализация
    graph_img = render_graph_to_html(G, medicine_name)

    # Формирование HTML
    html = f"<h3>💊 Препарат: {medicine_name.upper()}</h3>"
    html += format_official_effects(official_effects)
    html += format_confirmed_official(confirmed_official)
    html += format_non_official_sentences_simple(unconnected_sentences)
    html += format_ranked_table(ranked)

    html += "<div style='margin-top: 30px; text-align: center;'>"
    html += "<h3>📊 Граф связей препарата</h3>"
    html += "<p style='font-size: 12px; color: #666;'>🔴 Препарат | 🔵 Официальные побочки | 🟠 Найденные в отзывах</p>"
    html += graph_img
    html += "</div>"

    html += format_stats(G, medicine_name, ranked, len(confirmed_official), len(unconnected_sentences))

    return html