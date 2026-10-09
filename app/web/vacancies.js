"use strict";
const vacancyStatus = {published:"Опубликована",closed:"Закрыта"};
const applicationStatus = {submitted:"Подан",viewed:"Просмотрен",accepted:"Принят",rejected:"Отклонён",withdrawn:"Отозван"};
async function vacanciesScreen() {
  const employer = user?.role === "employer";
  content.append(node("h1", employer ? "Мои вакансии" : "Вакансии"));
  if (employer) link("Создать вакансию", "#vacancy-edit");
  else if (user) link("Мои отклики", "#applications");
  const rows = await request(employer ? "/employer/vacancies" : "/vacancies");
  if (!rows.length) content.append(node("p", "Вакансий пока нет."));
  for (const row of rows) {
    content.append(node("p", `${row.company_name || "Компания"} · ${vacancyStatus[row.status]} · ${row.salary_from}–${row.salary_to} ₽/месяц до налогов`));
    link(row.title, `#vacancy/${row.id}`);
  }
}
function vacancyDetails(row) {
  content.append(node("h2",row.title),node("p",row.company_name || "Компания"),node("p",vacancyStatus[row.status]),node("p",row.description));
  content.append(node("p",`Зарплата: ${row.salary_from}–${row.salary_to} ₽ в месяц до налогов (gross).`));
  content.append(node("p",`Формат: ${row.work_formats.join(", ")}. Город: ${row.location || "не требуется"}.`));
  content.append(node("p",`Начало: ${row.desired_start_date || "не указано"}${row.start_date_required ? " (обязательно)" : ""}.`));
  content.append(node("p",`Условия: ${row.conditions}`),node("p",`Связь с работодателем: ${row.representative_contact}`));
}
async function vacancyScreen(id) {
  const row = await request(`/vacancies/${id}`); vacancyDetails(row);
  link("Все вакансии", "#vacancies");
  if (!user) { link("Войти для отклика", "#login"); return; }
  if (user.role === "employer") {
    const own = await request("/employer/vacancies");
    if (own.some(v => v.id === row.id)) {
      link("Отклики на вакансию",`#applications/${id}`);
      if (row.status === "published") {
        link("Редактировать вакансию",`#vacancy-edit/${id}`);
        button(content,"Закрыть вакансию",async () => { await send(`/employer/vacancies/${id}/close`,{}); await render(); });
      }
    }
    return;
  }
  if (row.status === "closed") { content.append(node("p","Новые отклики не принимаются.")); return; }
  content.append(node("h2","Откликнуться"),node("p","Согласие даёт только этой компании доступ к выбранным контактам. Отклик не подтверждает квалификацию. Повторная подача сохраняет первую запись и не восстанавливает отозванный доступ."));
  const form = node("form"); content.append(form);
  field(form,"application_message","Сообщение работодателю","","textarea");
  const fields = {};
  for (const [key,label] of [["email","Email"],["phone","Телефон"],["messengers","Мессенджеры"]]) fields[key] = field(form,`share_${key}`,label,false,"checkbox");
  const consent = field(form,"application_consent","Разрешаю доступ к выбранным контактам (contacts-v1)",false,"checkbox");
  submit(form,"Подать отклик",async data => {
    if (!consent.checked) throw new Error("Подтвердите согласие.");
    const result = await send(`/vacancies/${id}/applications`,{message:data.get("application_message"),allowed_fields:Object.keys(fields).filter(key => fields[key].checked),consent_version:"contacts-v1"});
    location.hash=`#application/${result.id}`;
  });
}
async function vacancyEditor(id) {
  const row = id ? await request(`/employer/vacancies/${id}`) : null;
  content.append(node("h1",row ? "Редактирование вакансии" : "Создание вакансии"));
  if (row?.status === "closed") { content.append(node("p","Вакансия закрыта.")); return; }
  const form = node("form"); content.append(form);
  for (const [key,label,type] of [["title","Название вакансии","text"],["description","Описание задач","textarea"],["salary_from","Зарплата от, ₽/месяц до налогов","number"],["salary_to","Зарплата до, ₽/месяц до налогов","number"],["location","Город для офиса/гибрида","text"],["desired_start_date","Желаемая дата начала","date"],["conditions","Условия работы","textarea"],["representative_contact","Связь с работодателем","text"]]) {
    const input = field(form,key,label,row?.[key] || "",type);
    if (["title","description","salary_from","salary_to","conditions","representative_contact"].includes(key)) input.required=true;
    if (type === "number") { input.step="0.01"; input.min="0.01"; }
  }
  for (const [format,label] of [["remote","Удалённо"],["hybrid","Гибрид"],["office","Офис"]]) field(form,`format_${format}`,label,(row?.work_formats || ["remote"]).includes(format),"checkbox");
  field(form,"start_date_required","Дата начала обязательна",row?.start_date_required || false,"checkbox");
  content.append(node("p","Зарплатный диапазон в рублях обязателен. Отправленные отклики сохраняют прежние условия."));
  submit(form,row ? "Сохранить вакансию" : "Опубликовать вакансию",async data => {
    const value = {title:data.get("title"),description:data.get("description"),salary_from:Number(data.get("salary_from")),salary_to:Number(data.get("salary_to")),currency:"RUB",salary_basis:"gross",conditions:data.get("conditions"),representative_contact:data.get("representative_contact"),location:data.get("location") || null,desired_start_date:data.get("desired_start_date") || null,start_date_required:data.has("start_date_required"),work_formats:["remote","hybrid","office"].filter(key => data.has(`format_${key}`))};
    if (row) value.version=row.version;
    const saved=await send(row ? `/employer/vacancies/${id}` : "/employer/vacancies",value,row ? "PATCH" : "POST");
    location.hash=`#vacancy/${saved.id}`;
  });
}
async function applicationsScreen(vacancyId) {
  content.append(node("h1",user.role === "candidate" ? "Мои отклики" : "Отклики на вакансию"));
  if (user.role === "employer" && !vacancyId) { location.hash="#vacancies"; return; }
  const rows = await request(user.role === "candidate" ? "/candidate/applications" : `/employer/vacancies/${vacancyId}/applications`);
  if (!rows.length) content.append(node("p","Откликов пока нет."));
  for (const row of rows) { content.append(node("p",`${applicationStatus[row.status]} · ${row.submitted_at}`)); link(row.vacancy_snapshot.title,`#application/${row.id}`); }
  link("Вакансии","#vacancies");
}
async function applicationScreen(id) {
  const candidate = user.role === "candidate";
  const row = await request(`/${candidate ? "candidate" : "employer"}/applications/${id}`);
  content.append(node("h1",`Отклик: ${applicationStatus[row.status]}`),node("p","Условия сохранены на момент подачи отклика:"));
  vacancyDetails(row.vacancy_snapshot);
  content.append(node("p",`Сообщение: ${row.message}`));
  if (candidate) {
    content.append(node("p",row.contact_access ? `Этот отклик разрешает: ${row.allowed_fields.join(", ")}` : "У этого отклика нет действующего разрешения."));
    if (row.status !== "withdrawn") button(content,"Отозвать отклик",async () => { await send(`/applications/${id}/withdraw`,{}); await render(); });
    content.append(node("p","Отзыв этого отклика не отменяет согласия других откликов и приглашений."));
  } else {
    if (row.candidate_card) {
      content.append(node("h2",row.candidate_card.display_name),node("p",row.candidate_card.summary));
      content.append(node("p",row.candidate_card.assessment?.label || "Подтверждённая квалификация не опубликована."));
    } else content.append(node("p",row.card_notice));
    if (["submitted","viewed"].includes(row.status)) {
      if (row.status === "submitted") button(content,"Отметить просмотр",async () => { await send(`/applications/${id}/view`,{}); await render(); });
      button(content,"Принять отклик",async () => { await send(`/applications/${id}/accept`,{}); await render(); });
      button(content,"Отклонить отклик",async () => { await send(`/applications/${id}/reject`,{}); await render(); });
    }
    // Контакты могут быть разрешены другим источником: каждый запрос проверяет союз согласий.
    try {
      const contacts = await request(`/candidates/${row.candidate_id}/contacts`);
      content.append(node("h2","Разрешённые контакты"));
      for (const [key,value] of Object.entries(contacts)) content.append(node("p",`${key}: ${typeof value === "object" ? JSON.stringify(value) : value}`));
    } catch (error) { content.append(node("p",error.message)); }
    if (row.candidate_card) button(content,"PDF кандидата",async () => download(`/candidates/${row.candidate_id}/profile.pdf`));
  }
  link("История откликов", candidate ? "#applications" : `#applications/${row.vacancy_id}`);
}
