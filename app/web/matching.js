"use strict";
async function needsScreen(id) {
  link("Компания", "#employer");
  content.append(node("h1", "Потребности и подбор"), node("p", "Подбор включает только опубликованные зачётные категории. Пока review банка не завершён, демо-результаты в него не попадают."));
  const dictionary = await request("/catalog/matching-dictionary");
  const templates = await request("/employer/need-templates");
  const existing = id ? await request(`/employer/needs/${id}`) : null;
  const form = node("form"); form.id = "employer-need"; content.append(form);
  let templateCode = existing?.template_code ?? null, templateVersion = existing?.template_version ?? null;
  const fields = {};
  for (const [name, label, type] of [
    ["title", "Название", "text"], ["role", "Роль в команде", "text"],
    ["team_description", "Команда", "textarea"], ["task_description", "Задачи", "textarea"],
    ["location", "Город для офиса/гибрида", "text"], ["salary_from", "Бюджет от, RUB/месяц gross", "number"], ["salary_to", "Бюджет до", "number"],
    ["desired_start_date", "Желаемая дата начала", "date"],
    ["additional_wishes", "Дополнительные пожелания (текст не влияет на оценку)", "textarea"], ["vacancy_id", "ID вакансии (необязательно)", "text"]
  ]) fields[name] = field(form, name, label, existing?.[name] ?? "", type);
  fields.salary_from.step = fields.salary_to.step = "0.01";
  const grades = {}, formats = {}, stack = {}, priorities = {}, requiredSkills = {};
  form.append(node("h2", "Подходящие категории"));
  for (const grade of ["junior", "middle"]) grades[grade] = field(form, `grade_${grade}`, grade === "junior" ? "Junior" : "Middle", (existing?.accepted_grades ?? ["junior", "middle"]).includes(grade), "checkbox");
  form.append(node("h2", "Стек"), node("p", "Заявленная технология учитывается отдельно от проверенного навыка. Независимая проверка технологий пока охватывает Python, SQL и HTTP/API."));
  const technologyNames = {python:"Python", sql:"SQL", postgresql:"PostgreSQL", fastapi:"FastAPI", docker:"Docker", http_api:"HTTP/API"};
  for (const code of Object.keys(dictionary.technologies)) {
    const row = node("fieldset"); form.append(row); row.append(node("legend", technologyNames[code] ?? code));
    const required = existing?.required_stack.find(item => item.technology === code);
    stack[code] = {
      required: field(row, `required_${code}`, "Обязательно", Boolean(required), "checkbox"),
      preferred: field(row, `preferred_${code}`, "Желательно", existing?.preferred_stack.includes(code) ?? false, "checkbox"),
      verified: field(row, `verified_${code}`, "Требуется независимое подтверждение", required?.verification_required ?? false, "checkbox")
    };
    stack[code].verified.disabled = !dictionary.verified_technology_evidence[code];
  }
  form.append(node("h2", "Навыки"), node("p", "Выберите навыки, влияющие на подбор, и их вес: 1 — обычный, 2 — повышенный. Если ни один не выбран, используются тематические веса категории."));
  for (const [code, label] of Object.entries(dictionary.skills)) {
    const row = node("fieldset"); row.append(node("legend", label)); form.append(row);
    const enabled = field(row, `priority_${code}`, "Учитывать в приоритетах", Boolean(existing?.skill_priorities[code]), "checkbox");
    const weightLabel = node("label", "Вес"); const weight = node("select"); weight.id = `weight_${code}`;
    for (const [value, text] of [["1", "1 — обычный"], ["2", "2 — повышенный"]]) { const option = node("option", text); option.value = value; weight.append(option); }
    weight.value = String(existing?.skill_priorities[code] ?? 1); weightLabel.append(weight); row.append(weightLabel);
    priorities[code] = {enabled, weight};
    requiredSkills[code] = field(row, `skill_required_${code}`, "Наличие проверенного навыка обязательно", existing?.required_verified_skills.includes(code) ?? false, "checkbox");
  }
  form.append(node("h2", "Условия"));
  for (const [code,label] of [["remote","Удалённо"],["hybrid","Гибрид"],["office","Офис"]]) formats[code] = field(form, `format_${code}`, label, (existing?.work_formats ?? ["remote"]).includes(code), "checkbox");
  const requiredDate = field(form, "start_date_required", "Дата начала обязательна", existing?.start_date_required ?? false, "checkbox");
  const urgencyLabel = node("label", "Срочность"); const urgency = node("select"); urgency.id = "urgency";
  for (const [code,label] of [["normal","Обычная"],["urgent","Срочно"],["flexible","Гибкие сроки"]]) { const option = node("option", label); option.value = code; urgency.append(option); }
  urgency.value = existing?.urgency ?? "normal"; urgencyLabel.append(urgency); form.append(urgencyLabel);
  const years = field(form, "min_experience_years", "Минимум лет опыта (необязательно; самоописание кандидата)", existing?.additional_requirements.required_experience_years ?? "", "number"); years.min = "0"; years.max = "50"; years.step = "1";
  const choose = node("div"); content.insertBefore(choose, form);
  for (const template of templates) button(choose, `Шаблон: ${template.title}`, async () => {
    for (const name of ["title", "task_description"]) fields[name].value = template[name];
    for (const [code,input] of Object.entries(grades)) input.checked = template.accepted_grades.includes(code);
    for (const [code,inputs] of Object.entries(priorities)) { inputs.enabled.checked = Boolean(template.skill_priorities[code]); inputs.weight.value = String(template.skill_priorities[code] ?? 1); }
    templateCode = template.code; templateVersion = template.version;
    message("Шаблон применён. Бюджет и обязательный стек задайте самостоятельно; все поля можно редактировать.");
  });
  button(choose, "Без шаблона", async () => { templateCode = null; templateVersion = null; message("Привязка шаблона снята."); });
  submit(form, "Сохранить потребность", async () => {
    const value = Object.fromEntries(Object.entries(fields).map(([name,input]) => [name,input.value]));
    for (const name of ["salary_from", "salary_to"]) { if (!value[name]) throw new Error("Укажите обе границы бюджета."); value[name] = Number(value[name]); }
    for (const name of ["location", "desired_start_date", "vacancy_id"]) value[name] ||= null;
    for (const inputs of Object.values(stack)) if (inputs.required.checked && inputs.preferred.checked) throw new Error("Технология должна быть обязательной или желательной.");
    Object.assign(value, {
      specialization: "backend", accepted_grades: Object.keys(grades).filter(code => grades[code].checked),
      required_stack: Object.entries(stack).filter(([,inputs]) => inputs.required.checked).map(([code,inputs]) => ({technology:code,verification_required:inputs.verified.checked})),
      preferred_stack: Object.keys(stack).filter(code => stack[code].preferred.checked),
      skill_priorities: Object.fromEntries(Object.entries(priorities).filter(([,inputs]) => inputs.enabled.checked).map(([code,inputs]) => [code,Number(inputs.weight.value)])),
      required_verified_skills: Object.keys(requiredSkills).filter(code => requiredSkills[code].checked),
      work_formats: Object.keys(formats).filter(code => formats[code].checked), urgency: urgency.value,
      additional_requirements: years.value === "" ? {} : {required_experience_years:Number(years.value)},
      start_date_required: requiredDate.checked, version: existing?.version ?? 1, template_code: templateCode, template_version: templateVersion
    });
    const saved = await send(`/employer/needs${id ? `/${id}` : ""}`, value, id ? "PATCH" : "POST");
    message(`Потребность сохранена, версия ${saved.version}.`);
    if (id) await render(); else location.hash = `#needs/${saved.need_id}`;
  });
  if (id) {
    button(content, "Создать подборку", async () => { const snapshot = await send(`/employer/needs/${id}/recommendations`, {}); location.hash = `#recommendations/${snapshot.id}`; });
    content.append(node("h2", "История подборок"));
    for (const snapshot of await request(`/employer/needs/${id}/recommendations`)) link(`Версия потребности ${snapshot.need_version}, ${snapshot.as_of}`, `#recommendations/${snapshot.id}`);
  }
  content.append(node("h2", "Мои потребности"));
  for (const need of await request("/employer/needs")) link(`${need.title} (v${need.version})`, `#needs/${need.need_id}`);
  link("Новая потребность", "#needs");
}

async function recommendationsScreen(id) {
  const snapshot = await request(`/employer/recommendations/${id}`);
  content.append(node("h1", "Подборка"), node("p", snapshot.notice), node("p", `Версия потребности ${snapshot.need_version}, ${snapshot.as_of}; ${snapshot.algorithm_version}.`));
  link("Потребность", `#needs/${snapshot.need_id}`);
  const selected = new Set();
  if (!snapshot.entries.length) content.append(node("p", "Доступных подтверждённых профилей нет. Демо и fixture не используются в подборе."));
  for (const grade of ["junior", "middle"]) for (const group of ["eligible", "needs_clarification"]) {
    const rows = snapshot.entries.filter(row => row.available && row.recommendation.grade === grade && row.recommendation.group === group);
    if (!rows.length) continue;
    content.append(node("h2", `${grade}: ${group === "eligible" ? "Основная группа" : "Требуется уточнение"}`));
    for (const row of rows) {
      const box = node("section"); content.append(box);
      box.append(node("h3", row.card.display_name), node("p", `Баллы подбора: ${row.recommendation.score}. ${row.card.summary}`));
      for (const explanation of row.recommendation.explanations) box.append(node("p", explanation));
      const check = field(box, `compare_${row.candidate_id}`, "Сравнить", false, "checkbox");
      check.addEventListener("change", () => check.checked ? selected.add(row.candidate_id) : selected.delete(row.candidate_id));
      button(box, row.saved ? "Убрать из сохранённых" : "Сохранить", async () => { await send(`/employer/needs/${snapshot.need_id}/candidates/${row.candidate_id}`, {saved: !row.saved, hidden: false}, "PUT"); await render(); });
      const reason = field(box, `reason_${row.candidate_id}`, "Причина скрытия (необязательно)");
      button(box, "Скрыть для этой потребности", async () => { await send(`/employer/needs/${snapshot.need_id}/candidates/${row.candidate_id}`, {saved: row.saved, hidden: true, reason: reason.value}, "PUT"); await render(); });
      const invite = node("a", "Пригласить"); invite.href = `#offer/${snapshot.need_id}/${row.candidate_id}`; box.append(invite);
      button(box, "PDF", async () => download(`/candidates/${row.candidate_id}/profile.pdf`));
    }
  }
  for (const row of snapshot.entries.filter(row => !row.available)) {
    content.append(node("p", "Карточка недоступна."));
    if (row.hidden) button(content, "Отменить скрытие", async () => { await send(`/employer/needs/${snapshot.need_id}/candidates/${row.candidate_id}`, {saved: row.saved, hidden: false}, "PUT"); await render(); });
  }
  const result = node("section"); content.append(result);
  button(content, "Сравнить две выбранные карточки", async () => {
    if (selected.size !== 2) throw new Error("Выберите две карточки.");
    const fresh = await request(`/employer/recommendations/${id}`);
    const rows = fresh.entries.filter(row => selected.has(row.candidate_id));
    result.replaceChildren();
    if (rows.length !== 2 || rows.some(row => !row.available)) throw new Error("Одна из карточек больше недоступна.");
    const [a,b] = rows;
    if (a.recommendation.grade !== b.recommendation.grade || a.recommendation.group !== b.recommendation.group) throw new Error("Сравниваются карточки одного грейда и одной группы этой подборки.");
    const comparable = a.recommendation.assessment_scope.method_version === b.recommendation.assessment_scope.method_version && a.recommendation.assessment_scope.format === b.recommendation.assessment_scope.format;
    result.append(node("h2", "Сравнение"));
    if (!comparable) { result.append(node("p", "Методики несопоставимы; числовое сравнение недоступно.")); return; }
    const table = node("table"); result.append(table);
    const formatNames = {remote:"Удалённо",hybrid:"Гибрид",office:"Офис"};
    const stackNames = {python:"Python",sql:"SQL",http_api:"HTTP/API",postgresql:"PostgreSQL",fastapi:"FastAPI",docker:"Docker"};
    const skillNames = {language_algorithms:"Python и алгоритмы",sql_data:"SQL и данные",http_api:"HTTP/API",debug_reliability:"Отладка и надёжность",security_validation:"Безопасность и валидация"};
    const stackText = row => Object.entries(row.recommendation.technologies ?? {}).map(([code,status]) => `${stackNames[code] ?? code}: ${{verified:"проверено",self_reported:"заявлено",absent:"нет доказательств"}[status]}`).join("; ");
    const conditionsText = row => `${row.card.work_preferences.formats.map(code => formatNames[code]).join(", ")}; город: ${row.card.work_preferences.location ?? "не указан"}; дата начала: ${row.card.available_from ?? "не указана"}; зарплата: ${row.card.salary_min == null ? "нужно уточнить" : `${row.card.salary_min}–${row.card.salary_max}, RUB/месяц gross`}`;
    for (const [label,left,right] of [["Кандидат",a.card.display_name,b.card.display_name], ["Категория",a.recommendation.grade,b.recommendation.grade], ["Баллы подбора",a.recommendation.score,b.recommendation.score], ...Object.keys(a.recommendation.skills).concat(Object.keys(b.recommendation.skills)).filter((x,i,all) => all.indexOf(x) === i).map(skill => [skillNames[skill], a.recommendation.skills[skill]?.score ?? "Нет доказательств", b.recommendation.skills[skill]?.score ?? "Нет доказательств"]), ["Запрошенный стек",stackText(a),stackText(b)], ["Методика",a.recommendation.assessment_scope.method_version,b.recommendation.assessment_scope.method_version], ["Условия",conditionsText(a),conditionsText(b)], ["Объяснение",a.recommendation.explanations.join(" "),b.recommendation.explanations.join(" ")]]) {
      const tr = node("tr"); for (const text of [label,left,right]) tr.append(node("td", String(text))); table.append(tr);
    }
  });
}

async function fspScreen() {
  link("Профиль", "#candidate"); content.append(node("h1", "ФСП mock"));
  const value = await request("/candidate/fsp/achievements");
  content.append(node("p", value.notice), node("p", `Статус: ${value.status}; ID: ${value.external_id ?? "не привязан"}`));
  const form = node("form"); content.append(form);
  field(form, "external_id", "ID участника demo", value.external_id);
  field(form, "claim_code", "Код принадлежности demo");
  submit(form, "Привязать", async data => { await send("/candidate/fsp/link", Object.fromEntries(data)); await render(); });
  button(content, "Синхронизировать mock", async () => { await send("/candidate/fsp/sync", {}); await render(); });
  button(content, "Отозвать связь", async () => { await request("/candidate/fsp/link", {method: "DELETE"}); await render(); });
  for (const item of value.achievements) content.append(node("p", `${item.title}, ${item.date}, ${item.result} — демонстрационная запись.`));
}
