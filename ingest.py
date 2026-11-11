
import re
import json
import hashlib
from pathlib import Path

import config
# --- Читатели форматов: готовы ---

def read_txt(path: Path) -> list[tuple[int, str]]:
    """Возвращает [(номер страницы, текст)]. У TXT страниц нет, поэтому страница 0."""
    return [(0, path.read_text(encoding="utf-8", errors="ignore"))]


def read_pdf(path: Path) -> list[tuple[int, str]]:
    """Возвращает [(номер страницы, текст)] — постранично, чтобы метаданное page было честным."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]


READERS = {".txt": read_txt, ".md": read_txt, ".pdf": read_pdf}


# --- Очистка, нарезка и рубрикация (П2) ---


def clean_text(text: str) -> str:
    r"""Очистить сырой текст перед нарезкой.

    Убирает невидимые символы, номера страниц в начале страницы и отдельной
    строкой, склеивает слова, разорванные переносом, и сжимает пробелы.
    Числа внутри текста (сроки, баллы, суммы) сохраняются.
    """
    if not text:
        return ""

    # Невидимые символы и «мягкие» пробелы
    text = text.replace("\xa0", " ")      # NBSP из PDF и веб-страниц
    text = text.replace("\u200b", "")     # zero-width space
    text = text.replace("\ufeff", "")     # BOM

    # Номер страницы в начале страницы: " 12 Текст..." -> "Текст..."
    # Делаем это только для начала строки и не трогаем числа внутри текста:
    # сроки, баллы и суммы должны остаться в корпусе.
    text = re.sub(r"^\s*\d{1,3}(?=\s|$)", " ", text)

    # Номер страницы отдельной строкой
    text = re.sub(r"(?m)^[ \t]*\d{1,3}[ \t]*$", " ", text)

    # Склейка слов, разорванных переносом: "инфор-\nмация" -> "информация"
    text = re.sub(r"-\s*\n\s*", "", text)

    # Рваные строки PDF -> один поток
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def chunk_text(text: str, size: int = config.CHUNK_SIZE,
               overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    """Нарезать текст на чанки размером size с перекрытием overlap.

    Перекрытие нужно, чтобы мысль, попавшая на границу нарезки, не потерялась:
    её хвост окажется в начале следующего чанка.

    Следите за двумя вещами: шаг сдвига равен size - overlap (не size), и
    overlap обязан быть меньше size, иначе цикл не сойдётся.
    """
    if overlap >= size:
        raise ValueError(
            f"overlap ({overlap}) должен быть меньше size ({size})"
        )

    step = size - overlap
    chunks: list[str] = []

    for i in range(0, len(text), step):
        chunk = text[i:i + size]
        if chunk.strip():
            chunks.append(chunk)
        if i + size >= len(text):
            break

    return chunks


RUBRICS: dict[str, list[str]] = {
    # Частные рубрики идут первыми: иначе общее слово «документ» в вопросе
    # про общежитие уведёт фрагмент в admission и фильтр роли не сработает.
    "dormitory": [
        "общежит", "заселен", "проживан", "койк", "комендант", "бытов",
    ],
    "exams": [
        "экзамен", "испытан", "егэ", "балл", "вступительн",
        "предмет", "профильн", "минимальн",
    ],
    "cost": [
        "стоимост", "оплат", "скидк", "тариф", "рубл", "платн",
        "цена", "платеж",
    ],
    "admission": [
        "прием", "поступлен", "заявлен", "подач", "направлен",
        "бюджет", "целев", "абитуриент", "комисси", "документ",
        "срок", "согласие",
    ],
}

DEFAULT_RUBRIC = "general"


def detect_category(text: str, source: str) -> str:
    """Определить рубрику чанка.

    Достаточно правил по ключевым словам — LLM здесь не нужна.
    Порядок рубрик в RUBRICS важен: частные темы проверяются раньше
    общей, иначе одно общее слово перекрывает более точную рубрику.
    Пустых категорий быть не должно: для нераспознанного текста есть
    DEFAULT_RUBRIC.
    """
    text_lower = text.lower().replace("ё", "е")

    admission_phrases = (
        "прием документов",
        "приема документов",
        "приеме документов",
        "подача документов",
        "подачи документов",
        "подать документы",
        "подать документ",
        "срок подачи",
        "завершения приема документов",
        "заявление о приеме",
        "заявлении о приеме",
        "согласие на зачисление",
        "20 июня 2026",
        "15 июля 2026",
        "25 июля 2026",
    )
    if any(phrase in text_lower for phrase in admission_phrases):
        return "admission"

    for rubric, keywords in RUBRICS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return rubric

    return DEFAULT_RUBRIC


# --- Сборка индекса: готова ---

def ingest() -> int:
    """Обходит исходные данные, нарезает и складывает в ChromaDB. Возвращает число чанков.

    Индекс собирается заново с нуля: коллекция очищается перед наполнением.
    Иначе после смены CHUNK_SIZE в коллекции остались бы чанки предыдущей
    нарезки, и hit-rate@5 замерялся бы по смеси двух — молча, без ошибки.
    """
    collection = config.reset_collection()
    total = 0

    # README.md отсеивается намеренно: это шаблонная заглушка каталога,
    # а не документ предметной области. Без отсева она попадает в индекс
    # и выдаётся поиском как знание.
    files = [p for p in config.RAW_DIR.rglob("*")
             if p.suffix.lower() in READERS and p.name != "README.md"]
    if not files:
        raise SystemExit(f"В {config.RAW_DIR} нет файлов .txt/.md/.pdf — положите исходные данные (П2).")

    for path in files:
        for page, raw in READERS[path.suffix.lower()](path):
            cleaned = clean_text(raw)
            if not cleaned:
                continue

            for chunk in chunk_text(cleaned):
                # id детерминированный: одинаковый текст даёт один и тот же чанк,
                # поэтому дубли не возникают даже внутри одного прогона
                chunk_id = hashlib.sha1(
                    f"{path.name}:{page}:{chunk}".encode("utf-8")
                ).hexdigest()

                collection.upsert(
                    ids=[chunk_id],
                    documents=[chunk],
                    metadatas=[{
                        "source": path.name,
                        "page": page,
                        "category": detect_category(chunk, path.name),
                    }],
                )
                total += 1

    return total


# --- Замер качества поиска: готов ---

def evaluate_retrieval(k: int = config.TOP_K) -> float:
    """hit-rate@k по черновику Gold Dataset. Готово, менять не нужно.

    Для каждого вопроса выполняется поиск и проверяется, попал ли в первые k
    результатов хотя бы один чанк из ожидаемых источников.

    Вопросы с пустым expected_sources пропускаются: это проверка отказа отвечать,
    а она требует LLM и меряется на П6, а не здесь.

    Обращается к коллекции напрямую, а не через MCP: на П2 оркестратора ещё нет.
    """
    import json

    dataset_path = Path(__file__).parent / "gold_dataset.json"
    cases = [c for c in json.loads(dataset_path.read_text(encoding="utf-8"))
             if c.get("expected_sources")]

    if not cases:
        print("В gold_dataset.json нет вопросов с expected_sources — замерять нечего (П2).")
        return 0.0

    collection = config.get_collection()
    hits = 0

    print(f"\nhit-rate@{k}  |  чанк {config.CHUNK_SIZE}, overlap {config.CHUNK_OVERLAP}")
    for case in cases:
        result = collection.query(query_texts=[case["question"]], n_results=k)
        found = {(m or {}).get("source", "") for m in (result.get("metadatas") or [[]])[0]}
        hit = bool(found & set(case["expected_sources"]))
        hits += hit
        print(f"  [{'+' if hit else '-'}] {case['question'][:70]}")
        if not hit:
            print(f"      ожидалось: {case['expected_sources']}, найдено: {sorted(found)}")

    rate = hits / len(cases)
    print(f"\nhit-rate@{k} = {rate:.0%}  ({hits} из {len(cases)})")
    skipped = len(json.loads(dataset_path.read_text(encoding="utf-8"))) - len(cases)
    if skipped:
        print(f"Пропущено вопросов без expected_sources: {skipped} — они меряются на П6.")
    return rate


if __name__ == "__main__":
    import sys

    if "--eval" not in sys.argv:
        count = ingest()
        print(f"Индекс пересобран заново. Проиндексировано чанков: {count}")
        print(f"Всего в коллекции: {config.get_collection().count()}")

    evaluate_retrieval()


