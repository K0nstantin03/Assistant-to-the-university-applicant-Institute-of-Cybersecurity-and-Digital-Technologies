"""Проверка автомата ролей на наборе фраз.

По две фразы на каждый интент плюс одна заведомо непонятная.
Ожидаемые переходы и откаты видны в журнале route().
"""

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from orchestrator import Orchestrator

o = Orchestrator()

phrases = [
    # admission -> analyst
    "До какого числа можно подать документы на бюджет?",
    # housing -> dormitory: переход analyst -> dormitory
    "Можно ли получить место в общежитии?",
    # housing -> dormitory: остаёмся в dormitory
    "Какие документы нужны для заселения?",
    # admission -> analyst: переход dormitory -> analyst
    "Какие документы нужны для поступления?",
    # tuition -> cost: переход analyst -> cost
    "Сколько стоит обучение на выбранном направлении?",
    # tuition -> cost: остаёмся в cost
    "Можно ли оплатить обучение в рассрочку?",
    # admission -> analyst: переход cost -> analyst
    "Можно ли подать заявление на несколько направлений подготовки?",
    # entrance_exams -> exams: переход analyst -> exams
    "Какие экзамены нужно сдать для поступления?",
    # entrance_exams -> exams: остаёмся в exams
    "Какой минимальный балл по ЕГЭ?",
    # unknown -> analyst: переход exams -> analyst
    "asdf qwerty",
]

for phrase in phrases:
    intent = o.detect_intent(phrase)
    role = o.route("test", intent)
    print(f"{phrase[:55]:<57} интент {intent:<15} роль {role}")

# Прямой переход exams -> dormitory запрещён: route() должен откатить
# систему в роль по умолчанию, а не уронить её.
o.route("forbidden", "entrance_exams")
role = o.route("forbidden", "housing")
print(f"\nзапрещённый переход entrance_exams -> housing: роль {role}")

o.close()
