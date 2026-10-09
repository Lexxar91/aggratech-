# Matching check

Данные: внешние fixture, не реальные подтверждённые профили. Независимая проверка labels и объективности человеком не подтверждена.

Основные метрики: Precision@10 (делитель 10), Recall@20 (полный oracle-пул), nDCG@10 (полный идеальный пул); группы и грейды раздельно. Нет labels или пропущена пара — not_measured для всей потребности.

```json
{
  "label_source": "caller_provided; independent human review not verified",
  "fixture_only": true,
  "records": [
    {
      "need_id": "jury-sql-priority",
      "grade": "middle",
      "group": "eligible",
      "algorithm": "B0",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 2,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    },
    {
      "need_id": "jury-sql-priority",
      "grade": "middle",
      "group": "needs_clarification",
      "algorithm": "B0",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 1,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    },
    {
      "need_id": "jury-http-priority",
      "grade": "middle",
      "group": "eligible",
      "algorithm": "B0",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 2,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    },
    {
      "need_id": "jury-http-priority",
      "grade": "middle",
      "group": "needs_clarification",
      "algorithm": "B0",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 1,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    },
    {
      "need_id": "jury-sql-priority",
      "grade": "middle",
      "group": "eligible",
      "algorithm": "B1",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 2,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    },
    {
      "need_id": "jury-sql-priority",
      "grade": "middle",
      "group": "needs_clarification",
      "algorithm": "B1",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 1,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    },
    {
      "need_id": "jury-http-priority",
      "grade": "middle",
      "group": "eligible",
      "algorithm": "B1",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 2,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    },
    {
      "need_id": "jury-http-priority",
      "grade": "middle",
      "group": "needs_clarification",
      "algorithm": "B1",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 1,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    },
    {
      "need_id": "jury-sql-priority",
      "grade": "middle",
      "group": "eligible",
      "algorithm": "B2",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 2,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    },
    {
      "need_id": "jury-sql-priority",
      "grade": "middle",
      "group": "needs_clarification",
      "algorithm": "B2",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 1,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    },
    {
      "need_id": "jury-http-priority",
      "grade": "middle",
      "group": "eligible",
      "algorithm": "B2",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 2,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    },
    {
      "need_id": "jury-http-priority",
      "grade": "middle",
      "group": "needs_clarification",
      "algorithm": "B2",
      "status": "not_measured",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null,
      "returned": 1,
      "relevant_in_oracle": null,
      "relevant_fraction_of_returned": null,
      "missing_pairs": [
        "jury-sql-strong",
        "jury-http-strong",
        "jury-unknown-salary",
        "jury-unconfirmed",
        "jury-private"
      ],
      "eligibility_errors": [],
      "privacy_violations": []
    }
  ],
  "averages_equal_weight_per_need": [
    {
      "algorithm": "B0",
      "group": "eligible",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "algorithm": "B0",
      "group": "needs_clarification",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "algorithm": "B1",
      "group": "eligible",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "algorithm": "B1",
      "group": "needs_clarification",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "algorithm": "B2",
      "group": "eligible",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "algorithm": "B2",
      "group": "needs_clarification",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    }
  ],
  "paired_differences": [
    {
      "need_id": "jury-sql-priority",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B0",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "need_id": "jury-sql-priority",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B1",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "need_id": "jury-sql-priority",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B0",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "need_id": "jury-sql-priority",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B1",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "need_id": "jury-http-priority",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B0",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "need_id": "jury-http-priority",
      "grade": "middle",
      "group": "eligible",
      "baseline": "B1",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "need_id": "jury-http-priority",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B0",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "need_id": "jury-http-priority",
      "grade": "middle",
      "group": "needs_clarification",
      "baseline": "B1",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    }
  ],
  "average_paired_differences_equal_weight_per_need": [
    {
      "baseline": "B0",
      "group": "eligible",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "baseline": "B0",
      "group": "needs_clarification",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "baseline": "B1",
      "group": "eligible",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    },
    {
      "baseline": "B1",
      "group": "needs_clarification",
      "precision_at_10": null,
      "recall_at_20": null,
      "ndcg_at_10": null
    }
  ]
}
```
