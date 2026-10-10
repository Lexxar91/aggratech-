"""Детерминированно переносит принятый документ v3 без редактирования условий."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from app.assessment.bank_models import Skill
from app.assessment.v3_models import (
    V3_SEEDS,
    V3Bank,
    V3Card,
    V3Requirement,
    V3Solution,
)

# Свидетельства описывают наблюдаемое действие, а не самостоятельность диагностики.
ACTIONS: dict[str, list[tuple[Skill, str, str]]] = {
    "X1-PY": [
        (
            "language_algorithms",
            "Группировка, фильтрация и порядок версий",
            "Значения; неизменность входа; одноразовый ввод",
        )
    ],
    "X1-SQL": [
        (
            "sql_data",
            "Группировка, NULL и порядок выбора версий",
            "Строки и порядок результата PostgreSQL",
        )
    ],
    "X2": [
        (
            "http_api",
            "Статусы и порядок отказов HTTP",
            "Возвращённые коды на отдельных сценариях",
        ),
        (
            "security_validation",
            "Проверка исходных байтов, подписи и схемы",
            "Нет записи при неподписанном запросе; compare_digest",
        ),
    ],
    "X3": [
        (
            "sql_data",
            "Независимая агрегация и внешнее соединение",
            "Обычные результаты, столбцы и порядок",
        ),
        (
            "debug_reliability",
            "Предотвращение умножения строк",
            "Контрастные наборы связей и одинаковые суммы",
        ),
    ],
    "X4": [
        (
            "language_algorithms",
            "Состояние, дедупликация и приоритет завершения",
            "Данные, порядок, неизменность входа",
        ),
        (
            "http_api",
            "Последовательность запросов страниц",
            "Независимый журнал реально вызванных курсоров",
        ),
    ],
    "X5": [
        (
            "sql_data",
            "Anti-join, NULL и составная область",
            "Результаты PostgreSQL для таблиц исключений",
        ),
        (
            "debug_reliability",
            "Устойчивость исключений к NULL и другой компании",
            "Контрасты с NULL, дублями и совпадающими ID",
        ),
    ],
    "X6": [
        (
            "http_api",
            "Статусы локального платежа и конфликтов",
            "Коды и идентификаторы ответов",
        ),
        (
            "debug_reliability",
            "Повторы, сбои и одно применение платежа",
            "Независимый журнал сохранённых операций и списаний",
        ),
        (
            "security_validation",
            "Область ключа платежа",
            "Разные аккаунты с одинаковым ключом не смешиваются",
        ),
    ],
    "Y1-PY": [
        (
            "language_algorithms",
            "Сортировка, версии и составной курсор",
            "Полные выбранные данные, порядок и неизменность входа",
        )
    ],
    "Y1-SQL": [
        (
            "sql_data",
            "ORDER BY, LIMIT, версии и курсор",
            "Исполненная страница PostgreSQL и все страницы снимка",
        )
    ],
    "Y2": [
        (
            "http_api",
            "Порядок HTTP-отказов и допустимое обновление",
            "Статусы и ограничение числа попыток",
        ),
        (
            "security_validation",
            "Проверка доступа в точке записи",
            "Изменение только доступного счёта; нет записи при отказе",
        ),
    ],
    "Y3": [
        (
            "sql_data",
            "UPDATE или транзакционная SQL-функция",
            "Результат и изменения PostgreSQL",
        ),
        (
            "debug_reliability",
            "Нет потерянных или повторных изменений",
            "Итоги реальных транзакций, rollback и повтор",
        ),
    ],
    "Y4": [
        (
            "language_algorithms",
            "Лимиты попыток, ожиданий и бюджет",
            "Счётчики, бюджет и управление циклом",
        ),
        (
            "http_api",
            "Безопасность повторов метода и статуса",
            "Фактические вызовы send и их аргументы",
        ),
        (
            "debug_reliability",
            "Остановка после ошибки или успеха",
            "Независимый журнал sleep и отказ от опасного повтора",
        ),
    ],
    "Y5": [
        (
            "sql_data",
            "Одна последняя строка по составному порядку",
            "Столбцы и порядок результата PostgreSQL",
        ),
        (
            "debug_reliability",
            "Не возвращать старое состояние вместо последнего",
            "Равные времена, удаление и восстановление",
        ),
    ],
    "Y6": [
        (
            "http_api",
            "Статусы загрузки и очистка после отказа",
            "Коды и независимые commit/abort",
        ),
        (
            "security_validation",
            "Пределы размера и опубликованная политика путей",
            "Нет публикации недопустимого содержимого",
        ),
        (
            "language_algorithms",
            "Одноразовый поток без чтения после отказа",
            "Чередование чтения/записи и остановка итератора",
        ),
    ],
}


def import_document(source: Path, destination: Path) -> V3Bank:
    """Сохраняет источник, закрытый банк и открытую таблицу трассировки."""
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    headings = list(
        re.finditer(r"^### ([XY][1-6](?:-(?:PY|SQL))?-[JM]) — (.+)$", text, re.M)
    )
    common = (
        text.split("## 3. Общий технический контракт\n", 1)[1]
        .split("## 4.", 1)[0]
        .strip()
    )
    cards: list[V3Card] = []
    for i, heading in enumerate(headings):
        end = (
            headings[i + 1].start()
            if i + 1 < len(headings)
            else text.index("## 6.", heading.end())
        )
        section = text[heading.end() : end]
        condition = (
            section.split("**Кандидату**", 1)[1].split("**Перенос", 1)[0].strip()
        )
        transfer = (
            section.split("**Перенос — показать после сохранения первого решения**", 1)[
                1
            ]
            .split("**Ключ", 1)[0]
            .strip()
        )
        notes = (
            section.split("**Ключ для разработчика проверки**", 1)[1]
            .split("**Обязательные пакеты", 1)[0]
            .strip()
        )
        code_match = re.search(r"```(python|sql)\n(.*?)```", notes, re.S)
        if code_match is None:
            raise ValueError("v3_missing_executable_reference")
        language, code = code_match.groups()
        task_id, title = heading.groups()
        family = task_id.split("-")[0]
        action_key = task_id.rsplit("-", 1)[0]
        requirements = [
            V3Requirement(
                id=f"{task_id}-R{j + 1}", skill=skill, action=action, evidence=evidence
            )
            for j, (skill, action, evidence) in enumerate(ACTIONS[action_key])
        ]
        packs = dict(re.findall(r"^- ([ABCD]): (.+)$", section, re.M))
        cards.append(
            V3Card(
                task_id=task_id,
                family_id=family,
                grade="junior" if task_id.endswith("-J") else "middle",
                form="X" if family.startswith("X") else "Y",
                session="A" if family[1] in "1234" else "B",
                language="python" if language == "python" else "sql",
                title=title,
                condition=condition,
                transfer=transfer,
                common_contract=common,
                source_start_line=text[: heading.start()].count("\n") + 1,
                source_end_line=text[:end].count("\n"),
                source_hash=digest,
                seeds=list(V3_SEEDS),
                packs=packs,
                requirements=requirements,
                solutions=[
                    V3Solution(
                        id=f"{task_id}-reference",
                        kind="reference",
                        base=code,
                        transfer=code,
                        description="Ключ принятого документа v3",
                    )
                ],
                developer_notes=notes,
            )
        )
    bank = V3Bank(
        source_path="bank/sources/backend_junior_middle_bank_v3.md",
        source_hash=digest,
        cards=cards,
    )
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "private").mkdir(exist_ok=True)
    (destination / "sources").mkdir(exist_ok=True)
    (destination / "sources" / source.name).write_bytes(raw)
    (destination / "private" / "v3.json").write_text(
        json.dumps(bank.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    )
    rows = [
        "# Трассировка исполняемого банка v3",
        "",
        f"Источник SHA-256: `{digest}`.",
        "",
        (
            "Сессии A/B отличаются от тестовых пакетов "
            "A/B/C/D. Связанные PY/SQL сохраняют один "
            "family_id."
        ),
        "",
        (
            "| task_id | family_id | Грейд | Форма | Сессия |"
            " Язык | Проверяемые требования | Навыки | Пакеты"
            " |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for card in cards:
        rows.append(
            f"| {card.task_id} | {card.family_id} | {card.grade} | {card.form} | "
            f"{card.session} | {card.language} | "
            + "; ".join(r.id + ": " + r.action for r in card.requirements)
            + " | "
            + ", ".join(r.skill for r in card.requirements)
            + " | A/B/C/D; seeds "
            + ", ".join(map(str, card.seeds))
            + " |"
        )
    (destination / "v3_traceability.md").write_text("\n".join(rows) + "\n")
    return bank


def main() -> None:
    """Импорт выполняется вручную при поставке; runtime не генерирует задания."""
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=Path("bank"))
    args = parser.parse_args()
    bank = import_document(args.source, args.destination)
    print(f"Imported {len(bank.cards)} cards; source SHA-256 {bank.source_hash}")


if __name__ == "__main__":
    main()
