"""Закрытые независимые альтернативы и диагностические ошибки v3 для допуска."""

from app.assessment.v3_models import V3Card, V3Case, V3Solution

ALTERNATIVES: dict[str, str] = {
    "X1-PY-J": """
def totals(rows, paid_only=False):
    sums = {}
    for record in rows:
        if paid_only and record["status"] != "paid":
            continue
        sums[record["team"]] = sums.get(record["team"], 0) + (record["amount"] or 0)
    return [dict(team=name, total=sums[name]) for name in sorted(sums)]
""",
    "X1-PY-M": """
def totals_latest(rows, paid_only=False):
    winners, sums = {}, {}
    for record in rows:
        ident = record["record_id"]
        version = (record["revision"], record["revision_id"])
        if ident not in winners or version > winners[ident][0]:
            winners[ident] = (version, record)
    for _, record in winners.values():
        if paid_only and record["status"] != "paid":
            continue
        name = record["team"]
        sums[name] = sums.get(name, 0) + (record["amount"] or 0)
    return [dict(team=name, total=sums[name]) for name in sorted(sums)]
""",
    "X1-SQL-J": """
WITH selected AS (
 SELECT team,amount FROM payments
 WHERE CASE WHEN :paid_only THEN status='paid' ELSE TRUE END
)
SELECT team,COALESCE(SUM(amount),0) AS total
FROM selected GROUP BY team ORDER BY team;
""",
    "X1-SQL-M": """
WITH selected AS (
 SELECT DISTINCT ON (record_id) * FROM revisions
 ORDER BY record_id,revision DESC,revision_id DESC
)
SELECT team,COALESCE(SUM(amount),0) AS total FROM selected
WHERE NOT :paid_only OR status='paid'
GROUP BY team ORDER BY team;
""",
    "X2-J": """
import hashlib, hmac, json


def webhook(raw, signature, secret, content_type, enqueue):
    if len(signature) != 64 or any(c not in "0123456789abcdef" for c in signature):
        return 401
    if not hmac.compare_digest(
        hmac.new(secret, raw, hashlib.sha256).hexdigest(), signature
    ):
        return 401
    if content_type != "application/json":
        return 415
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except ValueError, UnicodeError:
        return 400
    if type(parsed) is not dict:
        return 400
    enqueue(parsed)
    return 202
""",
    "X2-M": """
import hashlib, hmac, json


def accept_event(raw, signature, secret, now, window, store):
    if len(signature) != 64 or any(c not in "0123456789abcdef" for c in signature):
        return 401
    digest = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.encode(), digest.encode()):
        return 401
    try:
        event = json.loads(raw.decode("utf-8"))
    except ValueError, UnicodeError:
        return 400
    if not isinstance(event, dict):
        return 400
    if not isinstance(event.get("event_id"), str) or len(event["event_id"]) == 0:
        return 400
    if type(event.get("timestamp")) != int or not isinstance(event.get("data"), dict):
        return 400
    if event["timestamp"] < now - window or event["timestamp"] > now + window:
        return 401
    return {"new": 202, "same": 202, "conflict": 409}[
        store.record(event["event_id"], raw)
    ]
""",
    "X3-J": """
SELECT o.order_id,o.total_amount,
 (SELECT COUNT(*) FROM order_lines l WHERE l.order_id=o.order_id) AS line_count
FROM orders o ORDER BY o.order_id;
""",
    "X3-M": """
SELECT o.customer_id,COUNT(*) AS order_count,SUM(o.total_amount) AS gross_total,
 COALESCE((SELECT SUM(r.amount) FROM refunds r
 JOIN orders x ON x.order_id=r.order_id WHERE 
x.customer_id=o.customer_id),0) AS refund_total
FROM orders o GROUP BY o.customer_id ORDER BY o.customer_id;
""",
    "X4-J": """
def collect(fetch_page, start, max_items):
    if max_items <= 0:
        return [], []
    records, calls = {}, []
    cursor = start
    while True:
        page = fetch_page(cursor)
        calls.append(cursor)
        for entry in page["items"]:
            if entry["id"] not in records:
                records[entry["id"]] = entry
            if len(records) >= max_items:
                return list(records.values()), calls
        if not page["has_more"]:
            return list(records.values()), calls
        cursor = page["next_cursor"]
""",
    "X4-M": """
def collect_safe(fetch_page, start, max_items):
    records, calls = {}, []

    def out(reason):
        return dict(items=list(records.values()), calls=calls, stop=reason)

    if max_items <= 0:
        return out("limit")
    cursor = start
    while cursor not in calls:
        calls.append(cursor)
        page = fetch_page(cursor)
        for entry in page["items"]:
            records.setdefault(entry["id"], entry)
            if len(records) >= max_items:
                return out("limit")
        if not page["has_more"]:
            return out("end")
        cursor = page["next_cursor"]
    return out("cursor_cycle")
""",
    "X5-J": """
SELECT user_id FROM users
WHERE user_id NOT IN (SELECT user_id FROM blocked WHERE user_id IS NOT NULL)
ORDER BY user_id;
""",
    "X5-M": """
SELECT u.user_id FROM users u
LEFT JOIN exclusions e ON e.tenant_id=u.tenant_id AND e.user_id=u.user_id 
AND e.active
LEFT JOIN extra_exclusions x ON x.user_id=u.user_id
WHERE u.tenant_id=:tenant_id AND e.user_id IS NULL AND x.user_id IS NULL
ORDER BY u.user_id;
""",
    "X6-J": """
def create_payment(account_id, key, amount, ledger):
    result, ident = ledger.create_once((account_id, "payments", key), amount)
    if result in ("same", "new"):
        return dict(status=201, payment_id=ident)
    return dict(status=409, payment_id=None)
""",
    "X6-M": """
def submit_payment(account_id, key, amount, repo):
    operation = repo.reserve((account_id, "payments", key), amount)
    if operation["conflict"]:
        return dict(status=409, payment_id=None)
    if operation["state"] == "pending":
        return dict(status=202, payment_id=None)
    return dict(status=201, payment_id=operation["payment_id"])


def deliver_payment(operation_id, repo, provider):
    operation = repo.get(operation_id)
    if operation["state"] == "pending":
        try:
            payment = provider.charge(operation_id, operation["amount"])
        except TimeoutError:
            return dict(status=202, payment_id=None)
        repo.complete(operation_id, payment)
    else:
        payment = operation["payment_id"]
    return dict(status=201, payment_id=payment)
""",
    "Y1-PY-J": """
import heapq


def first_ids(rows, limit):
    return [
        r["id"]
        for r in heapq.nsmallest(
            max(0, limit), rows, key=lambda r: (r["score"], r["id"])
        )
    ]
""",
    "Y1-PY-M": """
def next_page(rows, limit, after):
    if limit <= 0:
        return []
    versions = {}
    for record in rows:
        ident = record["id"]
        old = versions.get(ident)
        if old is None or (record["revision"], record["revision_id"]) > (
            old["revision"],
            old["revision_id"],
        ):
            versions[ident] = record
    ordered = sorted(versions.values(), key=lambda r: (r["score"], r["id"]))
    answer = []
    for record in ordered:
        if (
            after is None
            or record["score"] > after[0]
            or (record["score"] == after[0] and record["id"] > after[1])
        ):
            answer.append(record)
            if len(answer) == limit:
                break
    return answer
""",
    "Y1-SQL-J": """
SELECT id FROM scores ORDER BY score ASC,id ASC
LIMIT CASE WHEN :limit>0 THEN :limit ELSE 0 END;
""",
    "Y1-SQL-M": """
WITH latest AS (
 SELECT DISTINCT ON (id) * FROM scores ORDER BY id,revision 
DESC,revision_id DESC
)
SELECT id,score FROM latest
WHERE NOT :has_after OR score>:after_score OR (score=:after_score AND 
id>:after_id)
ORDER BY score,id LIMIT CASE WHEN :limit>0 THEN :limit ELSE 0 END;
""",
    "Y2-J": """
def handle_invoice(principal, invoice_id, method, amount, repo):
    if principal is None:
        return 401
    invoice = repo.get(invoice_id)
    if not invoice or invoice["owner_id"] != principal["user_id"]:
        return 404
    if method != "GET":
        repo.set_amount(invoice_id, amount)
    return 200
""",
    "Y2-M": """
def handle_scoped_invoice(user_id, invoice_id, method, amount, repo):
    if user_id is None:
        return 401
    attempts = 0
    while attempts < 3:
        current = repo.snapshot(user_id, invoice_id)
        invoice = current["invoice"]
        if (
            invoice is None
            or invoice["deleted"]
            or invoice["tenant_id"] != current["tenant_id"]
        ):
            return 404
        if method == "GET":
            return 200
        if current["role"] == "reader":
            return 403
        attempts += 1
        if repo.cas_update(current["token"], amount):
            return 200
    return 409
""",
    "Y3-J": """
WITH changed AS (
 UPDATE counters SET value=value+:delta WHERE account_id=:account_id 
RETURNING value
) SELECT value FROM changed;
""",
    "Y3-M": """
CREATE OR REPLACE FUNCTION apply_event(p_account bigint,p_event 
text,p_delta bigint)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE previous_delta bigint; current_value bigint;
BEGIN
 SELECT value INTO current_value FROM counters WHERE account_id=p_account 
FOR UPDATE;
 SELECT delta INTO previous_delta FROM applied WHERE account_id=p_account 
AND event_id=p_event;
 IF FOUND THEN
   IF previous_delta=p_delta THEN RETURN 'duplicate'; ELSE RETURN 
'conflict'; END IF;
 END IF;
 INSERT INTO applied(account_id,event_id,delta) 
VALUES(p_account,p_event,p_delta);
 UPDATE counters SET value=value+p_delta WHERE account_id=p_account;
 INSERT INTO outbox(account_id,event_id,delta) 
VALUES(p_account,p_event,p_delta);
 RETURN 'applied';
END;
$$;
""",
    "Y4-J": """
def retry(send, sleep, max_attempts, delay, retryable=frozenset({503})):
    waits = []
    last = None
    used = 0
    for index in range(max(0, max_attempts)):
        last = send()
        used = index + 1
        if last == 200 or last not in retryable or used == max_attempts:
            break
        sleep(delay)
        waits.append(delay)
    return dict(attempts=used, last_status=last, waits=waits)
""",
    "Y4-M": """
def retry_request(
    send, sleep, method, idempotency_supported, key, max_attempts, delay, wait_budget
):
    count, last, waits = 0, None, []
    stop = "attempts"
    safe_retry = method != "POST" or (idempotency_supported and bool(key))
    for index in range(max(0, max_attempts)):
        count = index + 1
        try:
            last = send(method, key)
        except TimeoutError:
            last = None
        if last == 200:
            stop = "success"
            break
        if last is not None and last != 503:
            stop = "status"
            break
        if count == max_attempts:
            break
        if not safe_retry:
            stop = "unsafe"
            break
        if delay + sum(waits) > wait_budget:
            stop = "budget"
            break
        waits.append(delay)
        sleep(delay)
    return dict(attempts=count, last_status=last, waits=waits, stop=stop)
""",
    "Y5-J": """
SELECT DISTINCT ON (key) key,event_id,created_at,value
FROM events ORDER BY key,created_at DESC,event_id DESC;
""",
    "Y5-M": """
SELECT key,event_id,created_at,value FROM (
 SELECT DISTINCT ON (key) * FROM events ORDER BY key,created_at 
DESC,event_id DESC
) latest WHERE NOT deleted ORDER BY key;
""",
    "Y6-J": """
def upload(chunks, max_bytes, storage):
    temp = storage.begin()
    committed = False
    total = 0
    try:
        for part in chunks:
            total += len(part)
            if total > max_bytes:
                return 413
            temp.write(part)
        if total == 0:
            return 400
        temp.commit()
        committed = True
        return 201
    except OSError:
        return 503
    finally:
        if not committed:
            temp.abort()
""",
    "Y6-M": """
def upload_archive(
    chunks, content_type, max_bytes, expanded_limit, max_files, storage, inspect_archive
):
    if content_type != "application/zip":
        return 415
    temp = storage.begin()
    committed = False
    compressed = 0
    try:
        for part in chunks:
            compressed += len(part)
            if compressed > max_bytes:
                return 413
            temp.write(part)
        if compressed == 0:
            return 400
        names = set()
        expanded = 0
        for entry in inspect_archive(temp):
            name = entry["name"]
            if (
                entry["is_symlink"]
                or not name
                or name[0] == "/"
                or "\\\\" in name
                or ":" in name
            ):
                return 400
            if set(name.split("/")) & {"", ".", ".."} or name in names:
                return 400
            names.add(name)
            if len(names) > max_files:
                return 413
            for part in entry["chunks"]:
                expanded += len(part)
                if expanded > expanded_limit:
                    return 413
        temp.commit()
        committed = True
        return 201
    except ValueError:
        return 415
    except OSError:
        return 503
    finally:
        if not committed:
            temp.abort()
""",
}

# Мутанты меняют одно объявленное требование; они не становятся новым ключом.
MUTATIONS: dict[str, tuple[str, str, str]] = {
    "X1-PY-J": (
        'sums.setdefault(row["team"], 0)',
        'sums.setdefault(row["team"], 1)',
        "Группа None получает 1 вместо 0",
    ),
    "X1-PY-M": (
        '(row["revision"], row["revision_id"]) > (old["revision"], old["revision_id"])',
        'row["revision"] > old["revision"]',
        "Отсутствует tie-break revision_id",
    ),
    "X1-SQL-J": ("COALESCE(SUM(amount), 0)", "SUM(amount)", "NULL не заменён нулём"),
    "X1-SQL-M": (
        "revision DESC, revision_id DESC",
        "revision DESC",
        "Отсутствует revision_id",
    ),
    "X2-J": (
        (
            'if not re.fullmatch(r"[0-9a-f]{64}", signature) '
            "or not hmac.compare_digest(expected, signature):"
        ),
        "if False:",
        "Неподписанное событие принимается",
    ),
    "X2-M": (
        (
            'if not re.fullmatch(r"[0-9a-f]{64}", signature) '
            "or not hmac.compare_digest(expected, signature):"
        ),
        "if False:",
        "Неподписанное событие записывается",
    ),
    "X3-J": (
        "COUNT(l.line_id)",
        "COALESCE(SUM(l.qty),0)",
        "Сумма qty вместо числа строк",
    ),
    "X3-M": (
        "SUM(o.total_amount)",
        "SUM(DISTINCT o.total_amount)",
        "Одинаковые суммы разных заказов потеряны",
    ),
    "X4-J": (
        'if not page["has_more"]:',
        'if not page["items"] or not page["has_more"]:',
        "Пустая промежуточная страница принята за конец",
    ),
    "X4-M": (
        'return result("end")',
        'return result("cursor_cycle")',
        "Terminal принят за цикл курсора",
    ),
    "X5-J": (
        (
            "SELECT u.user_id FROM users u\nWHERE NOT EXISTS "
            "(SELECT 1 FROM blocked b WHERE "
            "b.user_id=u.user_id)"
        ),
        (
            "SELECT u.user_id FROM users u WHERE u.user_id "
            "NOT IN (SELECT user_id FROM blocked)"
        ),
        "NOT IN с NULL",
    ),
    "X5-M": ("e.tenant_id=u.tenant_id AND ", "", "Область компании забыта"),
    "X6-J": (
        '(account_id, "payments", key)',
        '(0, "payments", key)',
        "Аккаунты смешиваются",
    ),
    "X6-M": (
        '(account_id, "payments", key)',
        '(0, "payments", key)',
        "Неправильная область сохранённого ключа",
    ),
    "Y1-PY-J": (
        '(r["score"], r["id"])',
        '(r["score"], -r["id"])',
        "Равенство разрешено большим ID",
    ),
    "Y1-PY-M": (
        '(row["revision"], row["revision_id"]) > (old["revision"], old["revision_id"])',
        'row["revision"] > old["revision"]',
        "Tie версий не учитывает revision_id",
    ),
    "Y1-SQL-J": ("GREATEST(:limit,0)", ":limit", "Отрицательный LIMIT вызывает ошибку"),
    "Y1-SQL-M": ("GREATEST(:limit,0)", ":limit", "Отрицательный LIMIT вызывает ошибку"),
    "Y2-J": (
        'row["owner_id"] != principal["user_id"]',
        "False",
        "Разрешено обновление чужого счёта",
    ),
    "Y2-M": ('if s["role"] != "editor":', "if False:", "Reader может обновлять счёт"),
    "Y3-J": (
        "value=value+:delta",
        "value=:delta",
        "Абсолютное значение вместо прибавления",
    ),
    "Y3-M": (
        "RETURN 'duplicate';",
        (
            "UPDATE counters SET value=value+p_delta WHERE "
            "account_id=p_account; RETURN 'duplicate';"
        ),
        "Повтор применяет delta ещё раз",
    ),
    "Y4-J": (
        "attempts == max_attempts",
        "False",
        "Лишнее ожидание после последней попытки",
    ),
    "Y4-M": (
        "idempotency_supported and bool(key)",
        "bool(key)",
        "Ключ принят за гарантию идемпотентности",
    ),
    "Y5-J": ("event_id DESC", "event_id ASC", "Неверный tie-break события"),
    "Y5-M": (
        "FROM events e",
        "FROM events e WHERE NOT deleted",
        "Старое состояние воскресает вместо удалённого",
    ),
    "Y6-J": ("temp.abort()", "pass", "Временный файл не очищен при отказе"),
    "Y6-M": ("temp.abort()", "pass", "Архив не очищен при отказе"),
}


def prepared_solutions(card: V3Card) -> list[V3Solution]:
    """Добавляет закрытые проверки альтернатив, сохраняя человеческий ключ целиком."""
    reference = card.solutions[0]
    before, after, description = MUTATIONS[card.task_id]
    if before not in reference.base:
        raise ValueError(f"v3_mutation_anchor_missing:{card.task_id}")
    wrong = reference.base.replace(before, after)
    alternative = ALTERNATIVES[card.task_id].strip() + "\n"
    syntax = "def broken(:\n" if card.language == "python" else "SELCT missing;"
    solutions = [
        reference,
        V3Solution(
            id=f"{card.task_id}-alternative",
            kind="alternative",
            base=alternative,
            transfer=alternative,
            description=(
                "Независимая исполняемая альтернатива: тот же опубликованный контракт"
            ),
        ),
        V3Solution(
            id=f"{card.task_id}-contract-error",
            kind="mistake",
            base=wrong,
            transfer=wrong,
            description=description,
        ),
        V3Solution(
            id=f"{card.task_id}-syntax-error",
            kind="mistake",
            base=syntax,
            transfer=syntax,
            description="Завершённое синтаксически неработающее решение",
        ),
    ]
    # В C с новыми данными неизменённый правильный код законно проходит.
    # Не требуем искусственной правки там, где опубликованное правило прежнее.
    unadapted = reference.base
    if card.task_id == "X2-J":
        unadapted = unadapted.replace(
            '    if content_type != "application/json":\n        return 415\n', ""
        )
    elif card.task_id == "Y2-J":
        unadapted = unadapted.replace(
            '    if method == "PATCH":\n        repo.set_amount(invoice_id, amount)\n',
            "",
        )
    elif card.task_id == "Y4-J":
        unadapted = unadapted.replace("status not in retryable", "status != 503")
    solutions.append(
        V3Solution(
            id=f"{card.task_id}-unadapted",
            kind="unadapted",
            base=unadapted,
            transfer=unadapted,
            description=(
                "Без адаптации: провал ожидается только для "
                "действительно изменённого правила"
            ),
        )
    )
    return solutions


def partial_solution(card: V3Card, cases: list[V3Case], seed: int) -> V3Solution:
    """Один обычный случай решён, другой — нет; это завершённый частичный ответ."""
    first = next(case for case in cases if case.pack == "A")
    source = card.solutions[0].base
    if card.language == "sql":
        if card.task_id == "Y3-J":
            source = source.replace(
                "WHERE account_id=:account_id",
                "WHERE account_id=:account_id AND :delta=3",
            )
        elif card.task_id == "Y3-M":
            source = source.replace(
                "BEGIN", "BEGIN\n IF p_delta <> 3 THEN RETURN 'duplicate'; END IF;", 1
            )
        else:
            expected = next(a.expected for a in first.assertions if a.path == ["rows"])
            if (
                not isinstance(expected, list)
                or not expected
                or not isinstance(expected[0], dict)
            ):
                raise ValueError("v3_partial_fixture_missing")
            columns = list(expected[0])
            values = []
            for i, row in enumerate(expected):
                if not isinstance(row, dict):
                    raise ValueError("v3_partial_fixture_invalid")
                literals = [str(i)]
                for column in columns:
                    value = row[column]
                    if isinstance(value, str):
                        literals.append("'" + value.replace("'", "''") + "'::text")
                    elif type(value) is int:
                        literals.append(str(value) + "::bigint")
                    else:
                        raise ValueError("unsupported_partial_sql_value")
                values.append("(" + ",".join(literals) + ")")
            source = (
                "SELECT "
                + ",".join(columns)
                + " FROM (VALUES "
                + ",".join(values)
                + ") AS v(_position,"
                + ",".join(columns)
                + ") ORDER BY _position;"
            )
    else:
        raw_invocations = first.scenario["invocations"]
        if not isinstance(raw_invocations, list) or not isinstance(
            raw_invocations[0], dict
        ):
            raise ValueError("v3_partial_invocation_missing")
        raw = raw_invocations[0]
        function = raw["function"]
        args = raw["args"]
        if not isinstance(function, str) or not isinstance(args, list):
            raise ValueError("v3_partial_function_missing")
        source = source.replace(f"def {function}(", f"def _complete_{function}(", 1)
        prefix = ""
        if card.family_id == "X2":
            value = args[0]
            if not isinstance(value, dict) or not isinstance(value["$bytes"], str):
                raise ValueError("v3_partial_raw_missing")
            condition = "args[0] == " + repr(bytes.fromhex(value["$bytes"]))
        elif card.family_id == "Y2":
            condition = (
                "args[1] == " + repr(args[1])
                if card.grade == "junior"
                else "args[2] == 'GET'"
            )
        elif card.task_id == "Y4-M":
            condition = "args[2] == 'GET'"
        elif card.task_id == "X6-M":
            condition = "args[1] == " + repr(args[1])
        elif card.task_id == "X6-J":
            expected = next(
                a.expected for a in first.assertions if a.path == ["return_values"]
            )
            if not isinstance(expected, list) or not expected:
                raise ValueError("v3_partial_payment_result_missing")
            condition = "result == " + repr(expected[0])
        elif card.family_id == "Y6":
            streams = first.scenario["streams"]
            if not isinstance(streams, dict) or not isinstance(streams["chunks"], dict):
                raise ValueError("v3_partial_chunks_missing")
            parts = streams["chunks"]["items"]
            if (
                not isinstance(parts, list)
                or not isinstance(parts[0], dict)
                or not isinstance(parts[0]["$bytes"], str)
            ):
                raise ValueError("v3_partial_first_chunk_missing")
            prefix = (
                "    import itertools\n    first = next(args[0], "
                "b'')\n    changed = list(args)\n    changed[0] = "
                "itertools.chain([first], args[0])\n    args = "
                "tuple(changed)\n"
            )
            condition = "first == " + repr(bytes.fromhex(parts[0]["$bytes"]))
        else:
            check = next(
                a for a in first.assertions if a.path[:3] == ["results", "0", "value"]
            )
            expression = "result"
            for part in check.path[3:]:
                expression += "[" + (part if part.isdecimal() else repr(part)) + "]"
            condition = expression + " == " + repr(check.expected)
        source += (
            f"\ndef {function}(*args, **kwargs):\n"
            + prefix
            + f"    result = _complete_{function}(*args, **kwargs)\n"
            + f"    return result if {condition} else None\n"
        )
    return V3Solution(
        id=f"{card.task_id}-partial-{seed}",
        kind="partial",
        base=source,
        transfer=source,
        seed=seed,
        description="Закрытый диагностический ответ: только первый обычный случай",
    )
