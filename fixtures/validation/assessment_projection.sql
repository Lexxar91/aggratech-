-- Служебный вход сводки: только SELECT из уже сохранённых попыток.
-- stdout хранится в закрытой рабочей области, не в материалах жюри.
-- Токены — псевдонимы, а не доказательство человеческого происхождения.
BEGIN TRANSACTION READ ONLY;
SELECT coalesce(jsonb_agg(projected ORDER BY projected->>'cycle_token', projected->>'family'), '[]'::jsonb)
FROM (
  SELECT jsonb_build_object(
    'cycle_token', md5(c.id::text), 'subject_token', md5(c.user_id::text),
    'mode', c.mode, 'origin', coalesce(c.admission->>'origin', 'unknown'),
    'review_status', CASE WHEN c.admission->'review_passed' = 'true'::jsonb THEN 'passed' ELSE 'pending' END,
    'fixture_notice', c.admission ? 'fixture_notice',
    'family', material.key, 'item_version', material.value->>'version',
    'evaluator_version', c.evaluator_hash, 'grade', c.grade, 'form', c.form,
    'created_at', c.created_at, 'shown', e.family IS NOT NULL,
    'finalized', a.finalized_at IS NOT NULL,
    'grading_status', coalesce(a.grading_status, 'not_started'),
    'technical_intervention', c.technical_exempt,
    'technical_reason', CASE WHEN a.grading_detail->>'error' IN ('assessment_infrastructure_unavailable', 'worker_recovery_exhausted') THEN a.grading_detail->>'error' ELSE 'unknown' END,
    'scores', coalesce(a.scores, '{}'::jsonb),
    'base_correct', a.grading_detail->'base_correct',
    'transfer_correct', a.grading_detail->'transfer_correct',
    'tests_valid', a.grading_detail->'tests_valid',
    'mandatory_tests_met', a.grading_detail->'mandatory_tests_met'
  ) AS projected
  FROM assessment_cycles c
  CROSS JOIN LATERAL jsonb_each(c.materials) material
  LEFT JOIN assessment_exposures e ON e.cycle_id = c.id AND e.family = material.key
  LEFT JOIN assessment_answers a ON a.cycle_id = c.id AND a.family = material.key
) safe;
COMMIT;
