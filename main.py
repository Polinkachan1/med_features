from flask import *
from database_work import init_db, get_medicine, get_medicines_by_name
from textrank import compare_feature
import sqlite3

app = Flask(__name__)
init_db()


def is_drug_ready(drug_name):
    """Проверяет, есть ли уже обработанные симптомы для препарата"""
    conn = sqlite3.connect('medical_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM candidate_symptoms cs
        JOIN medicines m ON cs.medicine_id = m.id
        WHERE LOWER(m.medicine_name) = ?
    ''', (drug_name.lower(),))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0


@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        user_input = request.form.get('drug_name', '').strip().lower()
        selected_medicine_id = request.form.get('selected_medicine_id')

        if selected_medicine_id:
            conn = sqlite3.connect('medical_data.db')
            cursor = conn.cursor()
            cursor.execute('SELECT medicine_name FROM medicines WHERE id = ?', (selected_medicine_id,))
            row = cursor.fetchone()
            conn.close()

            if row:
                drug_name = row[0]

                if not is_drug_ready(drug_name):
                    return render_template('index.html',
                                           error=f"Препарат '{drug_name}' ещё обрабатывается. Зайдите позже.",
                                           show_selection=False)

                print(f"🔍 Анализ выбранного препарата: {drug_name}")
                result_html = compare_feature(drug_name)
                return render_template('index.html',
                                       result=result_html,
                                       drug_name=drug_name,
                                       selected_medicine=drug_name)

            return render_template('index.html', error="Препарат не найден")

        if user_input == '':
            return render_template('index.html', error="Введите название препарата")

        matches = get_medicines_by_name(user_input)

        if not matches:
            return render_template('index.html', error=f"Препарат '{user_input}' не найден в базе")

        exact_match = None
        for med in matches:
            if med['medicine_name'].lower() == user_input.lower():
                exact_match = med
                break

        if exact_match:
            drug_name = exact_match['medicine_name']

            if not is_drug_ready(drug_name):
                return render_template('index.html',
                                       error=f"Препарат '{drug_name}' ещё обрабатывается. Зайдите позже.",
                                       show_selection=False)

            print(f"🔍 Найдено ТОЧНОЕ совпадение: {drug_name}")
            result_html = compare_feature(drug_name)
            return render_template('index.html',
                                   result=result_html,
                                   drug_name=drug_name,
                                   selected_medicine=drug_name)

        best_match = None
        for med in matches:
            effects = med.get('official_side_effects')
            if effects and effects != '[]' and effects != 'null':
                best_match = med
                break

        if best_match:
            drug_name = best_match['medicine_name']

            if not is_drug_ready(drug_name):
                return render_template('index.html',
                                       error=f"Препарат '{drug_name}' ещё обрабатывается. Зайдите позже.",
                                       show_selection=False)

            print(f"🔍 Анализ препарата с побочками: {drug_name}")
            result_html = compare_feature(drug_name)
            return render_template('index.html',
                                   result=result_html,
                                   drug_name=drug_name,
                                   selected_medicine=drug_name)

        elif len(matches) == 1:
            drug_name = matches[0]['medicine_name']

            if not is_drug_ready(drug_name):
                return render_template('index.html',
                                       error=f"Препарат '{drug_name}' ещё обрабатывается. Зайдите позже.",
                                       show_selection=False)

            print(f"🔍 Анализ единственного совпадения: {drug_name}")
            result_html = compare_feature(drug_name)
            return render_template('index.html',
                                   result=result_html,
                                   drug_name=drug_name)

        else:
            print(f"⚠️ Несколько совпадений для '{user_input}': {[m['medicine_name'] for m in matches]}")
            return render_template('index.html',
                                   matches=matches,
                                   search_term=user_input,
                                   show_selection=True)

    return render_template('index.html', error=None, show_selection=False)


if __name__ == '__main__':
    app.run(debug=True)