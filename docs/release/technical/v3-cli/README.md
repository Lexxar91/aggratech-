# Автономный CLI на текущем коде интеграции v3

80 искусственных кандидатов, 8 контрольных потребностей, 640 синтетических labels. Фиксированное as_of: 2026-10-09T12:00:00Z. Все B0/B1/B2 рассчитаны общим кодом; manifest сохраняет реальные хеши входов и кода. Это проверка на fixtures, не подтверждение квалификации людей или качества найма.

Воспроизведение из корня после установки зависимостей:

```bash
python -m app.tools.matching_check --input docs/release/technical/v3-cli/input/dataset.json --labels docs/release/technical/v3-cli/input/labels.synthetic.json --output /tmp/matching-v3-new-output
```

Выход должен быть новым/пустым. БД, почта и runner не требуются. [Отчёт](report.md); [manifest](run_manifest.json). Прежние CLI-отчёты RC сохранены в release/cli как история.
