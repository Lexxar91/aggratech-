"use strict";
const invitationStatuses = {sent:"Отправлено", viewed:"Просмотрено", accepted:"Принято", rejected:"Отклонено", expired:"Срок истёк", withdrawn:"Отозвано"};
async function invitationOfferScreen(needId, candidateId) {
  link("Приглашения", "#invitations");
  const need = await request(`/employer/needs/${needId}`);
  const company = await request("/employer/profile");
  content.append(node("h1", "Пригласить кандидата"), node("p", "Предложение действует семь суток. После отправки условия нельзя изменить: отзовите предложение и создайте новое. Вакансия не требуется."));
  const form = node("form"); form.id = "invitation-offer"; content.append(form);
  const inputs = {};
  for (const [key,label,type,value] of [
    ["description","Описание предложения","textarea",need.task_description],
    ["salary_from","Зарплата от, RUB/месяц gross","number",need.salary_from],
    ["salary_to","Зарплата до, RUB/месяц gross","number",need.salary_to],
    ["location","Город","text",need.location],
    ["desired_start_date","Дата начала","date",need.desired_start_date],
    ["conditions","Существенные условия работы","textarea",need.additional_wishes],
    ["representative_contact","Как связаться с представителем компании","text",company.representative_contact]
  ]) inputs[key] = field(form,key,label,value,type);
  inputs.salary_from.step = inputs.salary_to.step = "0.01";
  const formats = {};
  for (const [code,label] of [["remote","Удалённо"],["hybrid","Гибрид"],["office","Офис"]]) formats[code] = field(form, `offer_${code}`,label,need.work_formats.includes(code),"checkbox");
  const dateRequired = field(form,"offer_date_required","Дата начала обязательна",need.start_date_required,"checkbox");
  // Один ключ живёт до успешного ответа, включая сетевой повтор.
  const idempotencyKey = crypto.randomUUID();
  submit(form,"Отправить приглашение",async () => {
    const offer = Object.fromEntries(Object.entries(inputs).map(([key,input]) => [key,input.value]));
    if (!offer.salary_from || !offer.salary_to) throw new Error("Укажите обе границы зарплаты.");
    Object.assign(offer,{salary_from:Number(offer.salary_from),salary_to:Number(offer.salary_to),location:offer.location || null,desired_start_date:offer.desired_start_date || null,work_formats:Object.keys(formats).filter(code => formats[code].checked),start_date_required:dateRequired.checked});
    const result = await send("/employer/invitations", {need_id:needId,candidate_id:candidateId,idempotency_key:idempotencyKey,offer});
    location.hash = `#invitations/${result.id}`;
  });
}
async function invitationsScreen(id) {
  const candidate = user.role === "candidate";
  const prefix = candidate ? "/candidate" : "/employer";
  link("Кабинет", "#profile"); link("Все приглашения", "#invitations");
  content.append(node("h1", "Приглашения"));
  if (!id) {
    const rows = await request(`${prefix}/invitations`);
    if (!rows.length) content.append(node("p", "Приглашений пока нет. Демо-категории не дают доступа к подтверждённому подбору."));
    for (const row of rows) link(`${row.offer_snapshot.company_name}: ${invitationStatuses[row.status]}, до ${new Date(row.expires_at).toLocaleString("ru-RU")}`, `#invitations/${row.id}`);
    return;
  }
  const row = await request(`${prefix}/invitations/${id}`), offer = row.offer_snapshot.offer;
  content.append(node("h2", row.offer_snapshot.company_name),node("p", `Статус: ${invitationStatuses[row.status]}`),node("p", `Действует до ${new Date(row.expires_at).toLocaleString("ru-RU")}`));
  for (const text of [offer.description,`Зарплата: ${offer.salary_from}–${offer.salary_to} RUB/месяц gross`, `Формат: ${offer.work_formats.join(", ")}; город: ${offer.location ?? "не требуется"}`,`Дата начала: ${offer.desired_start_date ?? "по договорённости"}`,offer.conditions,`Представитель: ${offer.representative_contact}`,row.offer_snapshot.notice]) content.append(node("p", text));
  content.append(node("p", `Снимок потребности: версия ${row.offer_snapshot.need_version}. Более поздние изменения не переписывают предложение.`));
  if (["sent","viewed"].includes(row.status)) {
    if (candidate) {
      const form = node("form"); content.append(form); const fields = {};
      content.append(node("p","Принятие означает готовность продолжить общение. Выберите контакты для этой компании; остальные работодатели доступа не получают."));
      for (const [key,label] of [["email","Email"],["phone","Телефон"],["messengers","Мессенджеры"]]) fields[key] = field(form,`share_${key}`,label,false,"checkbox");
      const consent = field(form,"contact_consent","Разрешаю доступ к выбранным контактам (contacts-v1)",false,"checkbox");
      submit(form,"Принять приглашение",async () => { if (!consent.checked) throw new Error("Подтвердите согласие."); await send(`${prefix}/invitations/${id}/accept`,{allowed_fields:Object.keys(fields).filter(key => fields[key].checked),consent_version:"contacts-v1"}); await render(); });
      button(content,"Отклонить приглашение",async () => { await send(`${prefix}/invitations/${id}/reject`,{}); await render(); });
    } else button(content,"Отозвать приглашение",async () => { await send(`${prefix}/invitations/${id}/withdraw`,{}); await render(); });
  }
  if (candidate) {
    if (row.contact_access) button(content,"Закрыть контакты этой компании",async () => { await request(`/candidate/contact-grants/${row.employer_id}`,{method:"DELETE"}); await render(); });
    button(content,"Запретить приглашения от компании",async () => { await request(`/candidate/blocks/${row.employer_id}`,{method:"PUT"}); await render(); });
  } else {
    if (row.contact_access) {
      const contacts = await request(`/candidates/${row.candidate_id}/contacts`);
      content.append(node("h2","Разрешённые контакты"));
      for (const [key,value] of Object.entries(contacts)) content.append(node("p",`${key}: ${typeof value === "object" ? Object.entries(value).map(([name,address]) => `${name}: ${address}`).join("; ") : value}`));
    } else content.append(node("p","Разрешения на контакты нет."));
    button(content,"PDF кандидата",async () => download(`/candidates/${row.candidate_id}/profile.pdf`));
  }
}
