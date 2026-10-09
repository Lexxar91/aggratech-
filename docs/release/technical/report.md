# Контрольные измерения: этап 7

Только синтетические тестовые данные. Это проверка вычислений, а не оценка качества для реальных работодателей. Банк `not_admitted`; fixtures не поступают в продуктовую БД и подтверждённый подбор.

Версия: `stage7-synthetic-v1`; seed `20261009`; as_of `2026-10-09T12:00:00Z`. 120 кандидатов, 12 потребностей, 6 искусственных работодателей; разработочная часть 40/4, контрольная 80/8. Баллы случайны независимо от номинального уровня; task-fit labels заданы искусственными темами, независимо от Score. Human labels пусты: все показатели человеческого качества — **не измерено**.

Весовая формула неизменна: 55T + 25K + 8A + 7F + 5U − P. Настройка весов по контролю не выполнялась. B0 — фильтры/ID; B1 — тот же фильтр/стек; B2 — общая продуктовая логика. Группы не смешиваются; порядок B2 Score → T → K → candidate_id.

Precision@10: релевантность ≥2, делитель 10 даже для короткой выдачи. Recall@20: полный размеченный пул релевантных кандидатов этой категории/группы; пустой знаменатель — не измерено. nDCG@10: gain 2^rel−1, полный идеальный пул. Среднее: равный вес потребностей, сначала категорий внутри потребности. Все 640 контрольных пар размечены только техническим oracle; человеческая разметка 0/640.

## Все восемь контрольных потребностей

| Потребность | Алгоритм | Группа | Выдано | Релевантных в oracle | P@10 | R@20 | nDCG@10 |
|---|---|---|---:|---:|---:|---:|---:|
| c-j-ledger-reconciliation | B0 | eligible | 20 | 11 | 0.300000 | 1.000000 | 0.366399 |
| c-j-ledger-reconciliation | B0 | needs_clarification | 6 | 2 | 0.200000 | 1.000000 | 0.844558 |
| c-j-webhook-contract | B0 | eligible | 20 | 13 | 0.600000 | 1.000000 | 0.471150 |
| c-j-webhook-contract | B0 | needs_clarification | 6 | 4 | 0.400000 | 1.000000 | 0.706622 |
| c-j-queue-recovery | B0 | eligible | 14 | 2 | 0.200000 | 1.000000 | 0.771260 |
| c-j-queue-recovery | B0 | needs_clarification | 3 | 1 | 0.100000 | 1.000000 | 0.796708 |
| c-j-access-control | B0 | eligible | 20 | 11 | 0.700000 | 1.000000 | 0.694026 |
| c-j-access-control | B0 | needs_clarification | 6 | 4 | 0.400000 | 1.000000 | 0.851019 |
| c-m-ledger-reconciliation | B0 | eligible | 16 | 7 | 0.200000 | 1.000000 | 0.522273 |
| c-m-ledger-reconciliation | B0 | needs_clarification | 6 | 6 | 0.600000 | 1.000000 | 1.000000 |
| c-m-webhook-contract | B0 | eligible | 18 | 5 | 0.200000 | 1.000000 | 0.336265 |
| c-m-webhook-contract | B0 | needs_clarification | 6 | 2 | 0.200000 | 1.000000 | 0.967783 |
| c-m-queue-recovery | B0 | eligible | 7 | 3 | 0.300000 | 1.000000 | 0.651102 |
| c-m-queue-recovery | B0 | needs_clarification | 3 | 1 | 0.100000 | 1.000000 | 0.709810 |
| c-m-access-control | B0 | eligible | 17 | 12 | 0.800000 | 1.000000 | 0.596478 |
| c-m-access-control | B0 | needs_clarification | 4 | 3 | 0.300000 | 1.000000 | 0.760135 |
| c-j-ledger-reconciliation | B1 | eligible | 20 | 11 | 0.500000 | 1.000000 | 0.468433 |
| c-j-ledger-reconciliation | B1 | needs_clarification | 6 | 2 | 0.200000 | 1.000000 | 0.681783 |
| c-j-webhook-contract | B1 | eligible | 20 | 13 | 0.700000 | 1.000000 | 0.545934 |
| c-j-webhook-contract | B1 | needs_clarification | 6 | 4 | 0.400000 | 1.000000 | 0.828454 |
| c-j-queue-recovery | B1 | eligible | 14 | 2 | 0.200000 | 1.000000 | 0.656439 |
| c-j-queue-recovery | B1 | needs_clarification | 3 | 1 | 0.100000 | 1.000000 | 0.796708 |
| c-j-access-control | B1 | eligible | 20 | 11 | 0.600000 | 1.000000 | 0.526701 |
| c-j-access-control | B1 | needs_clarification | 6 | 4 | 0.400000 | 1.000000 | 0.703981 |
| c-m-ledger-reconciliation | B1 | eligible | 16 | 7 | 0.400000 | 1.000000 | 0.380554 |
| c-m-ledger-reconciliation | B1 | needs_clarification | 6 | 6 | 0.600000 | 1.000000 | 0.866980 |
| c-m-webhook-contract | B1 | eligible | 18 | 5 | 0.200000 | 1.000000 | 0.357911 |
| c-m-webhook-contract | B1 | needs_clarification | 6 | 2 | 0.200000 | 1.000000 | 0.858475 |
| c-m-queue-recovery | B1 | eligible | 7 | 3 | 0.300000 | 1.000000 | 0.665180 |
| c-m-queue-recovery | B1 | needs_clarification | 3 | 1 | 0.100000 | 1.000000 | 0.709810 |
| c-m-access-control | B1 | eligible | 17 | 12 | 0.600000 | 1.000000 | 0.511770 |
| c-m-access-control | B1 | needs_clarification | 4 | 3 | 0.300000 | 1.000000 | 1.000000 |
| c-j-ledger-reconciliation | B2 | eligible | 20 | 11 | 0.600000 | 1.000000 | 0.648313 |
| c-j-ledger-reconciliation | B2 | needs_clarification | 6 | 2 | 0.200000 | 1.000000 | 0.663782 |
| c-j-webhook-contract | B2 | eligible | 20 | 13 | 0.800000 | 1.000000 | 0.707521 |
| c-j-webhook-contract | B2 | needs_clarification | 6 | 4 | 0.400000 | 1.000000 | 0.808532 |
| c-j-queue-recovery | B2 | eligible | 14 | 2 | 0.000000 | 1.000000 | 0.350473 |
| c-j-queue-recovery | B2 | needs_clarification | 3 | 1 | 0.100000 | 1.000000 | 0.796708 |
| c-j-access-control | B2 | eligible | 20 | 11 | 0.600000 | 1.000000 | 0.576884 |
| c-j-access-control | B2 | needs_clarification | 6 | 4 | 0.400000 | 1.000000 | 0.670978 |
| c-m-ledger-reconciliation | B2 | eligible | 16 | 7 | 0.400000 | 1.000000 | 0.497509 |
| c-m-ledger-reconciliation | B2 | needs_clarification | 6 | 6 | 0.600000 | 1.000000 | 0.835784 |
| c-m-webhook-contract | B2 | eligible | 18 | 5 | 0.300000 | 1.000000 | 0.495056 |
| c-m-webhook-contract | B2 | needs_clarification | 6 | 2 | 0.200000 | 1.000000 | 0.626379 |
| c-m-queue-recovery | B2 | eligible | 7 | 3 | 0.300000 | 1.000000 | 0.581793 |
| c-m-queue-recovery | B2 | needs_clarification | 3 | 1 | 0.100000 | 1.000000 | 0.982842 |
| c-m-access-control | B2 | eligible | 17 | 12 | 0.700000 | 1.000000 | 0.650973 |
| c-m-access-control | B2 | needs_clarification | 4 | 3 | 0.300000 | 1.000000 | 1.000000 |

## Средние и парные разности

```json
{
  "averages_equal_weight_per_need": [
    {
      "algorithm": "B0",
      "group": "eligible",
      "precision_at_10": 0.4125,
      "recall_at_20": 1.0,
      "ndcg_at_10": 0.5511191410385337
    },
    {
      "algorithm": "B0",
      "group": "needs_clarification",
      "precision_at_10": 0.2875,
      "recall_at_20": 1.0,
      "ndcg_at_10": 0.8295792081858572
    },
    {
      "algorithm": "B1",
      "group": "eligible",
      "precision_at_10": 0.4375,
      "recall_at_20": 1.0,
      "ndcg_at_10": 0.5141151028377796
    },
    {
      "algorithm": "B1",
      "group": "needs_clarification",
      "precision_at_10": 0.2875,
      "recall_at_20": 1.0,
      "ndcg_at_10": 0.8057738978049959
    },
    {
      "algorithm": "B2",
      "group": "eligible",
      "precision_at_10": 0.4625,
      "recall_at_20": 1.0,
      "ndcg_at_10": 0.5635653696170428
    },
    {
      "algorithm": "B2",
      "group": "needs_clarification",
      "precision_at_10": 0.2875,
      "recall_at_20": 1.0,
      "ndcg_at_10": 0.7981254816228288
    }
  ],
  "paired_differences": [
    {
      "need_id": "c-j-ledger-reconciliation",
      "grade": "junior",
      "group": "eligible",
      "baseline": "B0",
      "precision_at_10": 0.3,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.28191414805243104
    },
    {
      "need_id": "c-j-ledger-reconciliation",
      "grade": "junior",
      "group": "eligible",
      "baseline": "B1",
      "precision_at_10": 0.09999999999999998,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.1798805058597115
    },
    {
      "need_id": "c-j-ledger-reconciliation",
      "grade": "junior",
      "group": "needs_clarification",
      "baseline": "B0",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.18077596249505568
    },
    {
      "need_id": "c-j-ledger-reconciliation",
      "grade": "junior",
      "group": "needs_clarification",
      "baseline": "B1",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.0180018622850856
    },
    {
      "need_id": "c-j-webhook-contract",
      "grade": "junior",
      "group": "eligible",
      "baseline": "B0",
      "precision_at_10": 0.20000000000000007,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.23637078971290226
    },
    {
      "need_id": "c-j-webhook-contract",
      "grade": "junior",
      "group": "eligible",
      "baseline": "B1",
      "precision_at_10": 0.10000000000000009,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.1615869811570556
    },
    {
      "need_id": "c-j-webhook-contract",
      "grade": "junior",
      "group": "needs_clarification",
      "baseline": "B0",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.10191011155043994
    },
    {
      "need_id": "c-j-webhook-contract",
      "grade": "junior",
      "group": "needs_clarification",
      "baseline": "B1",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.019922785844420643
    },
    {
      "need_id": "c-j-queue-recovery",
      "grade": "junior",
      "group": "eligible",
      "baseline": "B0",
      "precision_at_10": -0.2,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.42078756896039005
    },
    {
      "need_id": "c-j-queue-recovery",
      "grade": "junior",
      "group": "eligible",
      "baseline": "B1",
      "precision_at_10": -0.2,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.30596573800476823
    },
    {
      "need_id": "c-j-queue-recovery",
      "grade": "junior",
      "group": "needs_clarification",
      "baseline": "B0",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.0
    },
    {
      "need_id": "c-j-queue-recovery",
      "grade": "junior",
      "group": "needs_clarification",
      "baseline": "B1",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.0
    },
    {
      "need_id": "c-j-access-control",
      "grade": "junior",
      "group": "eligible",
      "baseline": "B0",
      "precision_at_10": -0.09999999999999998,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.11714205368362363
    },
    {
      "need_id": "c-j-access-control",
      "grade": "junior",
      "group": "eligible",
      "baseline": "B1",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.05018318632997054
    },
    {
      "need_id": "c-j-access-control",
      "grade": "junior",
      "group": "needs_clarification",
      "baseline": "B0",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.18004175631578234
    },
    {
      "need_id": "c-j-access-control",
      "grade": "junior",
      "group": "needs_clarification",
      "baseline": "B1",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.03300387046125586
    },
    {
      "need_id": "c-m-ledger-reconciliation",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B0",
      "precision_at_10": 0.2,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.024763965393106824
    },
    {
      "need_id": "c-m-ledger-reconciliation",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B1",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.11695517394981031
    },
    {
      "need_id": "c-m-ledger-reconciliation",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B0",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.16421555171608904
    },
    {
      "need_id": "c-m-ledger-reconciliation",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B1",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.031195360167752706
    },
    {
      "need_id": "c-m-webhook-contract",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B0",
      "precision_at_10": 0.09999999999999998,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.15879093104791853
    },
    {
      "need_id": "c-m-webhook-contract",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B1",
      "precision_at_10": 0.09999999999999998,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.1371454781644818
    },
    {
      "need_id": "c-m-webhook-contract",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B0",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.3414038915210278
    },
    {
      "need_id": "c-m-webhook-contract",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B1",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.23209593720869648
    },
    {
      "need_id": "c-m-queue-recovery",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B0",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.06930841208651584
    },
    {
      "need_id": "c-m-queue-recovery",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B1",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.08338683131481295
    },
    {
      "need_id": "c-m-queue-recovery",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B0",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.2730324865098742
    },
    {
      "need_id": "c-m-queue-recovery",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B1",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.2730324865098742
    },
    {
      "need_id": "c-m-access-control",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B0",
      "precision_at_10": -0.10000000000000009,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.05449595993845735
    },
    {
      "need_id": "c-m-access-control",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B1",
      "precision_at_10": 0.09999999999999998,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.1392033780926567
    },
    {
      "need_id": "c-m-access-control",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B0",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.2398647514834138
    },
    {
      "need_id": "c-m-access-control",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B1",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.0
    }
  ],
  "average_paired_differences_equal_weight_per_need": [
    {
      "baseline": "B0",
      "group": "eligible",
      "precision_at_10": 0.049999999999999996,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.012446228578509105
    },
    {
      "baseline": "B0",
      "group": "needs_clarification",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.03145372656302836
    },
    {
      "baseline": "B1",
      "group": "eligible",
      "precision_at_10": 0.025,
      "recall_at_20": 0.0,
      "ndcg_at_10": 0.04945026677926316
    },
    {
      "baseline": "B1",
      "group": "needs_clarification",
      "precision_at_10": 0.0,
      "recall_at_20": 0.0,
      "ndcg_at_10": -0.007648416182167134
    }
  ]
}
```

## Вклад компонентов

Фильтры, группы, вход, as_of и остальные веса фиксированы. Явные экспериментальные версии, не продуктовая выдача: FSP — F=0; актуальность — U=0 и P=0; доступность — A=0 (обязательная дата остаётся фильтром). Баллы пересчитываются до clamp; веса не нормируются. Сдвиг метрик на синтетических labels не доказывает пользу компонента человеку.

```json
{
  "B2-without-fsp-v1": {
    "not_product": true,
    "comparisons": [
      {
        "need_id": "c-j-ledger-reconciliation",
        "score_changes": 13,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-j-webhook-contract",
        "score_changes": 13,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-j-queue-recovery",
        "score_changes": 5,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-j-access-control",
        "score_changes": 13,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "score_changes": 12,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-webhook-contract",
        "score_changes": 13,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-queue-recovery",
        "score_changes": 5,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-access-control",
        "score_changes": 10,
        "order_changed": true,
        "groups_unchanged": true
      }
    ],
    "metric_records": [
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.6,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.5943071720316861,
        "returned": 20,
        "relevant_in_oracle": 11,
        "relevant_fraction_of_returned": 0.55,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.2,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.5868707635128156,
        "returned": 6,
        "relevant_in_oracle": 2,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.7,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6643773296438683,
        "returned": 20,
        "relevant_in_oracle": 13,
        "relevant_fraction_of_returned": 0.65,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.4,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.907269049310237,
        "returned": 6,
        "relevant_in_oracle": 4,
        "relevant_fraction_of_returned": 0.6666666666666666,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.0,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.40447957224393916,
        "returned": 14,
        "relevant_in_oracle": 2,
        "relevant_fraction_of_returned": 0.14285714285714285,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.1,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.7967075809905066,
        "returned": 3,
        "relevant_in_oracle": 1,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.7,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6918135406046274,
        "returned": 20,
        "relevant_in_oracle": 11,
        "relevant_fraction_of_returned": 0.55,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.4,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6709775428170647,
        "returned": 6,
        "relevant_in_oracle": 4,
        "relevant_fraction_of_returned": 0.6666666666666666,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.5,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.5372330632280667,
        "returned": 16,
        "relevant_in_oracle": 7,
        "relevant_fraction_of_returned": 0.4375,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.6,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.8603313457212691,
        "returned": 6,
        "relevant_in_oracle": 6,
        "relevant_fraction_of_returned": 1.0,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.3,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.5067534266660042,
        "returned": 18,
        "relevant_in_oracle": 5,
        "relevant_fraction_of_returned": 0.2777777777777778,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.2,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.5681831723570755,
        "returned": 6,
        "relevant_in_oracle": 2,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.3,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6289995525622707,
        "returned": 7,
        "relevant_in_oracle": 3,
        "relevant_fraction_of_returned": 0.42857142857142855,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.1,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.9828422279067397,
        "returned": 3,
        "relevant_in_oracle": 1,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.7,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6278702897543222,
        "returned": 17,
        "relevant_in_oracle": 12,
        "relevant_fraction_of_returned": 0.7058823529411765,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.3,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.9607618369839246,
        "returned": 4,
        "relevant_in_oracle": 3,
        "relevant_fraction_of_returned": 0.75,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      }
    ],
    "differences_vs_B2": [
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.05400603891209721
      },
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.07691080758303648
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": -0.10000000000000009,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.04314379468916596
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0987373383959772
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0540067995901915
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": 0.09999999999999998,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.11492928240205225
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.09999999999999998,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0397241391586603
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.02454689743735816
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.011697393505070541
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.05819559861722079
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.04720641261140168
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.02310320386767073
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.03923816301607541
      }
    ]
  },
  "B2-without-freshness-v1": {
    "not_product": true,
    "comparisons": [
      {
        "need_id": "c-j-ledger-reconciliation",
        "score_changes": 25,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-j-webhook-contract",
        "score_changes": 22,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-j-queue-recovery",
        "score_changes": 16,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-j-access-control",
        "score_changes": 22,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "score_changes": 20,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-webhook-contract",
        "score_changes": 22,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-queue-recovery",
        "score_changes": 7,
        "order_changed": false,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-access-control",
        "score_changes": 19,
        "order_changed": true,
        "groups_unchanged": true
      }
    ],
    "metric_records": [
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.7,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6242896010786471,
        "returned": 20,
        "relevant_in_oracle": 11,
        "relevant_fraction_of_returned": 0.55,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.2,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6637815710958521,
        "returned": 6,
        "relevant_in_oracle": 2,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.7,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6571502384898253,
        "returned": 20,
        "relevant_in_oracle": 13,
        "relevant_fraction_of_returned": 0.65,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.4,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.8897552351927531,
        "returned": 6,
        "relevant_in_oracle": 4,
        "relevant_fraction_of_returned": 0.6666666666666666,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.0,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.3488808879027121,
        "returned": 14,
        "relevant_in_oracle": 2,
        "relevant_fraction_of_returned": 0.14285714285714285,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.1,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.7967075809905066,
        "returned": 3,
        "relevant_in_oracle": 1,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.6,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6300181445354567,
        "returned": 20,
        "relevant_in_oracle": 11,
        "relevant_fraction_of_returned": 0.55,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.4,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6499072130662625,
        "returned": 6,
        "relevant_in_oracle": 4,
        "relevant_fraction_of_returned": 0.6666666666666666,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.4,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.45884957247061836,
        "returned": 16,
        "relevant_in_oracle": 7,
        "relevant_fraction_of_returned": 0.4375,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.6,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.8168870981774197,
        "returned": 6,
        "relevant_in_oracle": 6,
        "relevant_fraction_of_returned": 1.0,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.3,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.47650018424581325,
        "returned": 18,
        "relevant_in_oracle": 5,
        "relevant_fraction_of_returned": 0.2777777777777778,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.2,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6897551619265436,
        "returned": 6,
        "relevant_in_oracle": 2,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.3,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.581793139950869,
        "returned": 7,
        "relevant_in_oracle": 3,
        "relevant_fraction_of_returned": 0.42857142857142855,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.1,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.9828422279067397,
        "returned": 3,
        "relevant_in_oracle": 1,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.7,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.7031831093118266,
        "returned": 17,
        "relevant_in_oracle": 12,
        "relevant_fraction_of_returned": 0.7058823529411765,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.3,
        "recall_at_20": 1.0,
        "ndcg_at_10": 1.0,
        "returned": 4,
        "relevant_in_oracle": 3,
        "relevant_fraction_of_returned": 0.75,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      }
    ],
    "differences_vs_B2": [
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": 0.09999999999999998,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.024023609865136297
      },
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": -0.10000000000000009,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.050370885843208923
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.08122352427849333
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.001591884751035555
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.05313388633288152
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.02107032975080214
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.03865935159878808
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.018897350106491295
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.01855584891512041
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.06337639095224734
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.05220961568983362
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      }
    ]
  },
  "B2-without-availability-v1": {
    "not_product": true,
    "comparisons": [
      {
        "need_id": "c-j-ledger-reconciliation",
        "score_changes": 20,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-j-webhook-contract",
        "score_changes": 20,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-j-queue-recovery",
        "score_changes": 16,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-j-access-control",
        "score_changes": 20,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "score_changes": 14,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-webhook-contract",
        "score_changes": 15,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-queue-recovery",
        "score_changes": 9,
        "order_changed": true,
        "groups_unchanged": true
      },
      {
        "need_id": "c-m-access-control",
        "score_changes": 14,
        "order_changed": true,
        "groups_unchanged": true
      }
    ],
    "metric_records": [
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.6,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.5409254049008844,
        "returned": 20,
        "relevant_in_oracle": 11,
        "relevant_fraction_of_returned": 0.55,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.2,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6637815710958521,
        "returned": 6,
        "relevant_in_oracle": 2,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.8,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.7679125913950092,
        "returned": 20,
        "relevant_in_oracle": 13,
        "relevant_fraction_of_returned": 0.65,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.4,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.7549579868871825,
        "returned": 6,
        "relevant_in_oracle": 4,
        "relevant_fraction_of_returned": 0.6666666666666666,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.0,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.35047277265374766,
        "returned": 14,
        "relevant_in_oracle": 2,
        "relevant_fraction_of_returned": 0.14285714285714285,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.1,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6885288809404666,
        "returned": 3,
        "relevant_in_oracle": 1,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.6,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.48727802679443116,
        "returned": 20,
        "relevant_in_oracle": 11,
        "relevant_fraction_of_returned": 0.55,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.4,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6821336608193568,
        "returned": 6,
        "relevant_in_oracle": 4,
        "relevant_fraction_of_returned": 0.6666666666666666,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.4,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.39032403536484656,
        "returned": 16,
        "relevant_in_oracle": 7,
        "relevant_fraction_of_returned": 0.4375,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.6,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.835784448283911,
        "returned": 6,
        "relevant_in_oracle": 6,
        "relevant_fraction_of_returned": 1.0,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.3,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.5259735647857527,
        "returned": 18,
        "relevant_in_oracle": 5,
        "relevant_fraction_of_returned": 0.2777777777777778,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.2,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.7850431142602208,
        "returned": 6,
        "relevant_in_oracle": 2,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.3,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.581793139950869,
        "returned": 7,
        "relevant_in_oracle": 3,
        "relevant_fraction_of_returned": 0.42857142857142855,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.1,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6442869262030828,
        "returned": 3,
        "relevant_in_oracle": 1,
        "relevant_fraction_of_returned": 0.3333333333333333,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "eligible",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.7,
        "recall_at_20": 1.0,
        "ndcg_at_10": 0.6902299116178033,
        "returned": 17,
        "relevant_in_oracle": 12,
        "relevant_fraction_of_returned": 0.7058823529411765,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "needs_clarification",
        "algorithm": "B2",
        "status": "measured",
        "precision_at_10": 0.3,
        "recall_at_20": 1.0,
        "ndcg_at_10": 1.0,
        "returned": 4,
        "relevant_in_oracle": 3,
        "relevant_fraction_of_returned": 0.75,
        "missing_pairs": [],
        "eligibility_errors": [],
        "privacy_violations": []
      }
    ],
    "differences_vs_B2": [
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.10738780604289899
      },
      {
        "need_id": "c-j-ledger-reconciliation",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.06039146706197496
      },
      {
        "need_id": "c-j-webhook-contract",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.053573724027077274
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      },
      {
        "need_id": "c-j-queue-recovery",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.10817870005004004
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.089606231408144
      },
      {
        "need_id": "c-j-access-control",
        "grade": "junior",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.011156118002292104
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.10718488870455989
      },
      {
        "need_id": "c-m-ledger-reconciliation",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.030917531624819083
      },
      {
        "need_id": "c-m-webhook-contract",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.1586643432859245
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      },
      {
        "need_id": "c-m-queue-recovery",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": -0.3385553017036569
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "eligible",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.039256417995810367
      },
      {
        "need_id": "c-m-access-control",
        "grade": "middle",
        "group": "needs_clarification",
        "precision_at_10": 0.0,
        "recall_at_20": 0.0,
        "ndcg_at_10": 0.0
      }
    ]
  }
}
```

## Реальные сохранённые прохождения

нет данных

```json
{
  "status": "нет данных",
  "source": "saved_attempts_with_verified_human_registry",
  "observed_candidates": 0,
  "source_attempts": 0,
  "excluded_attempts": 0,
  "excluded_modes": {},
  "rows": [],
  "repeatability": "не измерено",
  "false_confirmation": "не измерено",
  "false_failure": "не измерено",
  "interpretation": "Не подтверждает объективность и сопоставимую сложность; технические ошибки не являются ошибками кандидата."
}
```

Цель пилота: 4 внешних участника × 2 цикла **одного** грейда X/Y. Подтверждённых участников сейчас 0; проверка повторяемости, ложного подтверждения/отказа, объективности, сложности, атак и понятности шаблонов/объяснений/сравнения: **не измерено**. Переход Junior↔Middle — отдельный эксперимент, не повторяемость. Контакты с добровольцами и человеческие проверки не проводились; отложены до этапа 9.

## Ошибки и ограничения

Независимый контроль — отдельная реализация вычислений, не независимое человеческое review. В `human-unmeasured` неполная разметка даёт «не измерено» по всем потребностям. Технические ошибки assessment не являются ошибками кандидата. Отдельные результаты диагностики и заметки об условиях не сохраняются: «нет данных». Реальные ответы и закрытые материалы не экспортируются. Времена в `timings.json` измеряют только вычисление matching на синтетике, не полный пользовательский путь; изменчивые duration/timings не входят в сравнение детерминированного содержимого.

См. `run_manifest.json` для хешей входов/кода и протокола проверок; `synthetic` и `human-unmeasured` содержат четыре стандартных артефакта CLI. Изменение правил, данных, labels или оценщика требует новой версии и повторного контроля; человеческий контроль текущей версии ещё не выполнен.
