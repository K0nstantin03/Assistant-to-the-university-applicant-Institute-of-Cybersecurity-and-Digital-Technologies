"""
orchestrator.py — ядро системы: конечный автомат, переключающий роли агентов.

ПРАКТИКА 3. Что делает студент:
  1. описать роли в ROLES — минимум две, с разными зонами ответственности
  2. заполнить INTENT_TO_ROLE и TRANSITIONS — граф переходов автомата
  3. реализовать detect_intent() — определение интента пользователя

Готово и трогать не нужно: route(), handle(), подключение MCP и LLM.

Критерии приёмки:
  - ролей не меньше двух, у каждой описана своя зона ответственности
  - граф переходов задан структурой данных, а не цепочкой if по всему файлу
  - смена интента в диалоге переключает роль, это видно в логе
  - неизвестный интент не роняет процесс, а уходит в состояние по умолчанию
  - контекст при переходе не теряется: вторая роль видит найденное первой
  - вызов инструмента идёт через MCP-клиент, а не прямым импортом функции поиска

НЕ МЕНЯТЬ: сигнатуру handle(session_id, text) -> str. Это единственная точка
входа в систему, и её вызывают оба канала (app.py, vk_bot.py) и test_suite.py.

Порядок сдачи. На П3 сквозного ответа ещё не будет: build_messages() и клиент LLM
пишутся на П4. Проверяйте автомат отдельно — вызовом detect_intent() и route()
на наборе фраз. Сквозной ответ появится на П4, память подключится на П5.
"""

import logging
import re
import guardrails
import memory
import prompts
from contracts import Chunk
from llm_client import build_client
from mcp_client import MCPTools

log = logging.getLogger(__name__)

BLOCKED_REPLY = "Запрос отклонён слоем безопасности. Переформулируйте вопрос по существу темы."


class Orchestrator:

    """Оркестратор ролей ассистента абитуриента."""

    # --- Роли: у каждой своя зона ответственности ---

    ROLES: dict[str, dict] = {

        "analyst": {

            "description": (

                "консультирует абитуриентов по правилам приёма, "

                "срокам подачи документов, необходимым документам, "

                "направлениям подготовки, заявлениям и проходным "

                "баллам прошлых лет"

            ),

            "temperature": 0.2,

            "filters": {"category": "admission"},

        },

        "dormitory": {

            "description": (

                "отвечает на вопросы об общежитии, условиях "

                "заселения, документах для заселения, предоставлении "

                "мест и правилах проживания"

            ),

            "temperature": 0.2,

            "filters": {"category": "dormitory"},

        },

        "cost": {

            "description": (

                "консультирует по стоимости обучения, оплате, "

                "ценам на образовательные программы и приказам "

                "об установлении стоимости обучения"

            ),

            "temperature": 0.2,

            "filters": {"category": "cost"},

        },

        "exams": {

            "description": (

                "отвечает на вопросы о вступительных испытаниях, "

                "предметах ЕГЭ, минимальных баллах, дополнительных "

                "экзаменах и требованиях для поступления"

            ),

            "temperature": 0.2,

            "filters": {"category": "exams"},

        },

    }

    INITIAL_ROLE = "analyst"

    FALLBACK_ROLE = "analyst"

    # --- Граф переходов конечного автомата ---

    TRANSITIONS: dict[str, set[str]] = {

        "analyst": {"analyst", "dormitory", "cost", "exams"},

        "dormitory": {"analyst", "dormitory", "cost", "exams"},

        "cost": {"analyst", "dormitory", "cost", "exams"},

        "exams": {"analyst", "dormitory", "cost", "exams"},

    }

    # --- Соответствие интентов ролям ---

    INTENT_TO_ROLE: dict[str, str] = {

        "admission": "analyst",

        "dormitory": "dormitory",

        "cost": "cost",

        "exams": "exams",

        "unknown": "analyst",

    }

    def __init__(self):

        self.tools = MCPTools()

        self.llm = build_client()

        memory.create_schema()

        self._state: dict[str, str] = {}

        self._context: dict[str, list[Chunk]] = {}

        self.usage: list[dict] = []

    # --- Определение интента пользователя ---

    def detect_intent(self, text: str) -> str:

        """Определить категорию вопроса абитуриента.

        Возвращает ключ из INTENT_TO_ROLE.

        При неизвестном запросе возвращает unknown.

        """

        text_lower = text.lower().strip().replace("ё", "е")

        if not text_lower:

            return "unknown"

        # 1. Вопросы об общежитии

        dormitory_patterns = [

            r"\bобщежити\w*",

            r"\bзаселени\w*",

            r"\bпроживани\w*",

            r"\bпоселиться\b",

            r"\bкомендант\w*",

            r"\bместо в общежитии\b",

            r"\bдокумент\w* для заселени\w*",

            r"\bоплат\w* за проживани\w*",

        ]

        if any(

            re.search(pattern, text_lower)

            for pattern in dormitory_patterns

        ):

            return "dormitory"

        # 2. Вопросы о стоимости обучения

        cost_patterns = [

            r"\bстоимост\w*",

            r"\bсколько стоит\b",

            r"\bцен\w* на обучени\w*",

            r"\bплатн\w* обучени\w*",

            r"\bоплат\w* за обучени\w*",

            r"\bоплат\w* обучени\w*",

            r"\bконтракт\w*",

            r"\bдоговорн\w* основ\w*",

            r"\bрассрочк\w*",

            r"\bприказ\w* о стоимост\w*",

        ]

        if any(

            re.search(pattern, text_lower)

            for pattern in cost_patterns

        ):

            return "cost"

        # 3. Вопросы о вступительных испытаниях

        exams_patterns = [

            r"\bегэ\b",

            r"\bвступительн\w* экзамен\w*",

            r"\bвступительн\w* испытани\w*",

            r"\bэкзамен\w*",

            r"\bминимальн\w* балл\w*",

            r"\bпредмет\w* для поступлени\w*",

            r"\bкакие предметы\b",

            r"\bрезультат\w* экзамен\w*",

            r"\bдополнительн\w* испытани\w*",

            r"\bперечень испытани\w*",

        ]

        if any(

            re.search(pattern, text_lower)

            for pattern in exams_patterns

        ):

            return "exams"

        # 4. Вопросы о приёме в вуз

        admission_patterns = [

            r"\bпоступлени\w*",

            r"\bприем\w*",

            r"\bабитуриент\w*",

            r"\bподать заявлени\w*",

            r"\bподач\w* документ\w*",

            r"\bдокумент\w* для поступлени\w*",

            r"\bсрок\w* подач\w*",

            r"\bдо какого числа\b",

            r"\bна бюджет\b",

            r"\bнаправлени\w* подготовк\w*",

            r"\bспециальност\w*",

            r"\bпроходн\w* балл\w* прошл\w* лет\b",

            r"\bцелев\w* обучени\w*",

            r"\bконкурсн\w* списк\w*",

            r"\bприемн\w* комисси\w*",

            r"\bдва направлени\w*",

            r"\bнесколько направлени\w*",

            r"\bправил\w* приема\b",

            r"\bсрок\w* приема\b",

            r"\bзаявлени\w* на бюджет\b",

        ]

        if any(

            re.search(pattern, text_lower)

            for pattern in admission_patterns

        ):

            return "admission"

        # 5. Общие вопросы по теме поступления

        question_words = (

            "что",

            "как",

            "почему",

            "когда",

            "где",

            "кто",

            "можно ли",

            "нужно ли",

        )

        if "?" in text_lower or any(

            re.search(rf"\b{re.escape(word)}\b", text_lower)

            for word in question_words

        ):

            return "admission"

        # 6. Неизвестный интент

        return "unknown"

    # --- Готовая механика: не менять ---

    def route(self, session_id: str, intent: str) -> str:

        """Перевести автомат в новое состояние и вернуть активную роль."""

        current = self._state.get(session_id, self.INITIAL_ROLE)

        target = self.INTENT_TO_ROLE.get(intent, self.FALLBACK_ROLE)

        allowed = self.TRANSITIONS.get(current, {self.FALLBACK_ROLE})

        rolled_back = target not in allowed

        if rolled_back:

            log.warning(

                "Переход %s -> %s запрещён, откат в %s",

                current,

                target,

                self.FALLBACK_ROLE,

            )

            target = self.FALLBACK_ROLE

        if target != current:

            log.info(

                "Сессия %s: роль %s -> %s (интент %s%s)",

                session_id,

                current,

                target,

                intent,

                ", откат" if rolled_back else "",

            )

        self._state[session_id] = target

        return target

    def handle(self, session_id: str, text: str) -> str:

        """Единственная точка входа.

        Конвейер: guardrail -> память -> интент -> роль ->

        поиск через MCP -> сборка промпта -> LLM -> память -> ответ.

        """

        verdict = guardrails.check(text)

        if not verdict.allowed:

            guardrails.log_attempt(session_id, text, verdict)

            log.warning(

                "Сессия %s: запрос заблокирован (%s)",

                session_id,

                verdict.reason,

            )

            return BLOCKED_REPLY

        previous_role = self._state.get(session_id, self.INITIAL_ROLE)

        intent = self.detect_intent(text)

        role = self.route(session_id, intent)

        role_config = self.ROLES[role]

        filters = role_config.get("filters") or {}

        if filters:

            chunks = self.tools.search_filtered(text, filters)

        else:

            chunks = self.tools.search(text)

        # Контекст переезжает между ролями.

        # Новая роль видит результаты предыдущего поиска.

        if role != previous_role:

            known = {

                (c.source, c.page, c.text[:80])

                for c in chunks

            }

            chunks = chunks + [

                c

                for c in self._context.get(session_id, [])

                if (c.source, c.page, c.text[:80]) not in known

            ]

        self._context[session_id] = chunks

        history = memory.window(session_id)

        memory.save(session_id, "user", text)

        messages = prompts.build_messages(

            role,

            text,

            chunks,

            history,

        )

        prompt_size = self.llm.count_tokens(

            "\n".join(m["content"] for m in messages)

        )

        log.info(

            "Сессия %s: роль %s, чанков %d, промпт ~%d токенов",

            session_id,

            role,

            len(chunks),

            prompt_size,

        )

        answer = self.llm.generate(

            messages,

            temperature=role_config["temperature"],

        )

        self.usage.append({

            "session_id": session_id,

            "role": role,

            "prompt_tokens": prompt_size,

            "completion_tokens": self.llm.count_tokens(answer),

        })

        memory.save(session_id, "assistant", answer)

        return answer

    def reset(self, session_id: str) -> None:

        """Сбросить сессию: состояние автомата, контекст и историю."""

        self._state.pop(session_id, None)

        self._context.pop(session_id, None)

        memory.clear(session_id)

    def close(self) -> None:

        """Закрыть MCP-клиент."""

        self.tools.close()
