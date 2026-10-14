import logging

logging.basicConfig(level=logging.INFO)

from orchestrator import Orchestrator

o = Orchestrator()

phrases = [
    "Кто такой ден?",
    "Реал мадрид чемпион?",
    "Проверь тест",
    "asdf qwerty",
]

for p in phrases:
    intent = o.detect_intent(p)
    role = o.route("test", intent)
    print(f"{p[:40]:<42} интент {intent:<12} роль {role}")

o.close()