# Трассировка исполняемого банка v3

Источник SHA-256: `5705b3a6d2d5c4a0da11064b1fc4fed69e40fe034d4f24f609f411168d1ec458`.

Сессии A/B отличаются от тестовых пакетов A/B/C/D. Связанные PY/SQL сохраняют один family_id.

| task_id | family_id | Грейд | Форма | Сессия | Язык | Проверяемые требования | Навыки | Пакеты |
|---|---|---|---|---|---|---|---|---|
| X1-PY-J | X1 | junior | X | A | python | X1-PY-J-R1: Группировка, фильтрация и порядок версий | language_algorithms | A/B/C/D; seeds 1729, 2718, 31415 |
| X1-SQL-J | X1 | junior | X | A | sql | X1-SQL-J-R1: Группировка, NULL и порядок выбора версий | sql_data | A/B/C/D; seeds 1729, 2718, 31415 |
| X1-PY-M | X1 | middle | X | A | python | X1-PY-M-R1: Группировка, фильтрация и порядок версий | language_algorithms | A/B/C/D; seeds 1729, 2718, 31415 |
| X1-SQL-M | X1 | middle | X | A | sql | X1-SQL-M-R1: Группировка, NULL и порядок выбора версий | sql_data | A/B/C/D; seeds 1729, 2718, 31415 |
| X2-J | X2 | junior | X | A | python | X2-J-R1: Статусы и порядок отказов HTTP; X2-J-R2: Проверка исходных байтов, подписи и схемы | http_api, security_validation | A/B/C/D; seeds 1729, 2718, 31415 |
| X2-M | X2 | middle | X | A | python | X2-M-R1: Статусы и порядок отказов HTTP; X2-M-R2: Проверка исходных байтов, подписи и схемы | http_api, security_validation | A/B/C/D; seeds 1729, 2718, 31415 |
| X3-J | X3 | junior | X | A | sql | X3-J-R1: Независимая агрегация и внешнее соединение; X3-J-R2: Предотвращение умножения строк | sql_data, debug_reliability | A/B/C/D; seeds 1729, 2718, 31415 |
| X3-M | X3 | middle | X | A | sql | X3-M-R1: Независимая агрегация и внешнее соединение; X3-M-R2: Предотвращение умножения строк | sql_data, debug_reliability | A/B/C/D; seeds 1729, 2718, 31415 |
| X4-J | X4 | junior | X | A | python | X4-J-R1: Состояние, дедупликация и приоритет завершения; X4-J-R2: Последовательность запросов страниц | language_algorithms, http_api | A/B/C/D; seeds 1729, 2718, 31415 |
| X4-M | X4 | middle | X | A | python | X4-M-R1: Состояние, дедупликация и приоритет завершения; X4-M-R2: Последовательность запросов страниц | language_algorithms, http_api | A/B/C/D; seeds 1729, 2718, 31415 |
| X5-J | X5 | junior | X | B | sql | X5-J-R1: Anti-join, NULL и составная область; X5-J-R2: Устойчивость исключений к NULL и другой компании | sql_data, debug_reliability | A/B/C/D; seeds 1729, 2718, 31415 |
| X5-M | X5 | middle | X | B | sql | X5-M-R1: Anti-join, NULL и составная область; X5-M-R2: Устойчивость исключений к NULL и другой компании | sql_data, debug_reliability | A/B/C/D; seeds 1729, 2718, 31415 |
| X6-J | X6 | junior | X | B | python | X6-J-R1: Статусы локального платежа и конфликтов; X6-J-R2: Повторы, сбои и одно применение платежа; X6-J-R3: Область ключа платежа | http_api, debug_reliability, security_validation | A/B/C/D; seeds 1729, 2718, 31415 |
| X6-M | X6 | middle | X | B | python | X6-M-R1: Статусы локального платежа и конфликтов; X6-M-R2: Повторы, сбои и одно применение платежа; X6-M-R3: Область ключа платежа | http_api, debug_reliability, security_validation | A/B/C/D; seeds 1729, 2718, 31415 |
| Y1-PY-J | Y1 | junior | Y | A | python | Y1-PY-J-R1: Сортировка, версии и составной курсор | language_algorithms | A/B/C/D; seeds 1729, 2718, 31415 |
| Y1-SQL-J | Y1 | junior | Y | A | sql | Y1-SQL-J-R1: ORDER BY, LIMIT, версии и курсор | sql_data | A/B/C/D; seeds 1729, 2718, 31415 |
| Y1-PY-M | Y1 | middle | Y | A | python | Y1-PY-M-R1: Сортировка, версии и составной курсор | language_algorithms | A/B/C/D; seeds 1729, 2718, 31415 |
| Y1-SQL-M | Y1 | middle | Y | A | sql | Y1-SQL-M-R1: ORDER BY, LIMIT, версии и курсор | sql_data | A/B/C/D; seeds 1729, 2718, 31415 |
| Y2-J | Y2 | junior | Y | A | python | Y2-J-R1: Порядок HTTP-отказов и допустимое обновление; Y2-J-R2: Проверка доступа в точке записи | http_api, security_validation | A/B/C/D; seeds 1729, 2718, 31415 |
| Y2-M | Y2 | middle | Y | A | python | Y2-M-R1: Порядок HTTP-отказов и допустимое обновление; Y2-M-R2: Проверка доступа в точке записи | http_api, security_validation | A/B/C/D; seeds 1729, 2718, 31415 |
| Y3-J | Y3 | junior | Y | A | sql | Y3-J-R1: UPDATE или транзакционная SQL-функция; Y3-J-R2: Нет потерянных или повторных изменений | sql_data, debug_reliability | A/B/C/D; seeds 1729, 2718, 31415 |
| Y3-M | Y3 | middle | Y | A | sql | Y3-M-R1: UPDATE или транзакционная SQL-функция; Y3-M-R2: Нет потерянных или повторных изменений | sql_data, debug_reliability | A/B/C/D; seeds 1729, 2718, 31415 |
| Y4-J | Y4 | junior | Y | A | python | Y4-J-R1: Лимиты попыток, ожиданий и бюджет; Y4-J-R2: Безопасность повторов метода и статуса; Y4-J-R3: Остановка после ошибки или успеха | language_algorithms, http_api, debug_reliability | A/B/C/D; seeds 1729, 2718, 31415 |
| Y4-M | Y4 | middle | Y | A | python | Y4-M-R1: Лимиты попыток, ожиданий и бюджет; Y4-M-R2: Безопасность повторов метода и статуса; Y4-M-R3: Остановка после ошибки или успеха | language_algorithms, http_api, debug_reliability | A/B/C/D; seeds 1729, 2718, 31415 |
| Y5-J | Y5 | junior | Y | B | sql | Y5-J-R1: Одна последняя строка по составному порядку; Y5-J-R2: Не возвращать старое состояние вместо последнего | sql_data, debug_reliability | A/B/C/D; seeds 1729, 2718, 31415 |
| Y5-M | Y5 | middle | Y | B | sql | Y5-M-R1: Одна последняя строка по составному порядку; Y5-M-R2: Не возвращать старое состояние вместо последнего | sql_data, debug_reliability | A/B/C/D; seeds 1729, 2718, 31415 |
| Y6-J | Y6 | junior | Y | B | python | Y6-J-R1: Статусы загрузки и очистка после отказа; Y6-J-R2: Пределы размера и опубликованная политика путей; Y6-J-R3: Одноразовый поток без чтения после отказа | http_api, security_validation, language_algorithms | A/B/C/D; seeds 1729, 2718, 31415 |
| Y6-M | Y6 | middle | Y | B | python | Y6-M-R1: Статусы загрузки и очистка после отказа; Y6-M-R2: Пределы размера и опубликованная политика путей; Y6-M-R3: Одноразовый поток без чтения после отказа | http_api, security_validation, language_algorithms | A/B/C/D; seeds 1729, 2718, 31415 |
