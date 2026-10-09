"use strict";
const outcomeNames = {confirmed:"Требования выполнены",not_confirmed:"Требования пока не выполнены",insufficient:"Недостаточно данных",review_required:"Требуется проверка достоверности"};
async function assessmentScreen(id) {
  content.append(node("h1", "Проверка навыков Backend"));
  link("К профилю", "#profile");
  content.append(node("p", "Сейчас доступно демо: банк ожидает независимого review. Результаты не являются верифицированной категорией и не участвуют в подтверждённом подборе работодателя."));
  if (id) return assessmentCycle(await request(`/assessment/cycles/${id}`));
  content.append(node("p", "Правила: A — 30 минут, затем начать B за 24 часа; B — 15 минут. Таймер не останавливается при закрытии страницы. Разрешены редактор, собственный код и справочная документация; ответы самостоятельные. База фиксируется до открытия переноса. Черновики нужно сохранять. Техническую проблему можно обжаловать. Повтор того же грейда — через 7 дней, смена опубликованного — через 30 дней; не более двух завершённых циклов за 30 дней. Для новой попытки нужны непоказанные семейства."));
  const survey = await request("/assessment/survey");
  const form = node("form"); form.id = "assessment-survey"; content.append(form);
  field(form,"industry","Отрасль",survey?.industry || "IT");
  field(form,"stack","Стек через запятую",survey?.stack.join(", ") || "Python, SQL, HTTP");
  const years = field(form,"experience_years","Опыт, лет",survey?.experience_years || 0,"number"); years.min=0; years.max=50;
  field(form,"instructions_accepted","Правила прочитаны, подтверждаю самостоятельность",false,"checkbox");
  const label=node("label","Грейд");const select=node("select");select.name="grade";
  for(const grade of ["junior","middle"]) {const option=node("option",grade);option.value=grade;select.append(option);} label.append(select);form.append(label);
  submit(form,"Начать демо-цикл",async data=>{
    if(!data.get("instructions_accepted")) throw new Error("Примите правила до начала.");
    await send("/assessment/survey",{industry:data.get("industry"),stack:String(data.get("stack")).split(",").map(x=>x.trim()).filter(Boolean),experience_years:Number(data.get("experience_years")),specialization:"backend",tools_policy:"independent",instructions_accepted:true},"PUT");
    const cycle=await send("/assessment/cycles",{grade:data.get("grade"),mode:"demo"});location.hash=`#assessment/${cycle.id}`;
  });
  content.append(node("h2","История"));
  for(const cycle of await request("/assessment/cycles")) {
    link(`${cycle.grade} · ${cycle.mode} · ${cycle.state} · ${outcomeNames[cycle.result.outcome]} · ${new Date(cycle.created_at).toLocaleString()}`,`#assessment/${cycle.id}`);
    content.append(node("br"));
  }
  for(const appeal of await request("/assessment/appeals")) content.append(node("p",`Апелляция ${appeal.cycle_id}: ${appeal.state}. ${appeal.resolution || "Решение ожидается"}`));
}
async function assessmentCycle(cycle) {
  link("Все прохождения", "#assessment");
  content.append(node("h2",`${cycle.grade} · ${cycle.mode} · ${cycle.state}`));
  content.append(node("p",cycle.result.label));
  const deadline=cycle.state==="A"?cycle.a_deadline:cycle.state==="B"?cycle.b_deadline:cycle.state==="B_ready"?cycle.b_start_deadline:null;
  if(deadline) content.append(node("p",`Серверный срок ${cycle.state==="B_ready"?"начала B":"сдачи"}: ${new Date(deadline).toLocaleString()}`));
  if(cycle.technical_issue) content.append(node("p","Технический сбой оценивания: оценки за сбой не выставлены. Обратитесь через апелляцию для восстановления проверки того же цикла."));
  if(cycle.result.total!==null) content.append(node("p",`Суммарный показатель: ${cycle.result.total}. Решение зависит также от порогов каждого навыка.`));
  for(const skill of cycle.result.skills) content.append(node("p",`${skill.skill}: ${skill.status}, ${skill.score ?? "нет данных"}/100, семейств: ${skill.families}`));
  button(content,"Обновить состояние",async()=>render());
  for(const task of cycle.tasks) {
    const form=node("form");form.id=`task-${task.family}`;content.append(form);
    form.append(node("h3",`${task.family} · ${task.step}`),node("p",task.condition),node("p",task.diagnosis_prompt),node("pre",JSON.stringify(task.input,null,2)));
    if(task.finalized) {form.append(node("p","Ответ зафиксирован."));continue;}
    if(task.python_required) {
      field(form,"source","Python: функция solve(data)",task.draft.source,"textarea");
      field(form,"diagnosis",`Диагноз: ${task.diagnosis_options.join(", ")}`,task.draft.diagnosis);
      field(form,"verification",`Проверенные случаи через запятую: ${task.verification_options.join(", ")}`,task.draft.verification.join(", "));
    }
    if(task.structured_condition) {
      form.append(node("p",task.structured_condition),node("pre",JSON.stringify({input:task.structured_input,options:task.answer_options},null,2)));
      field(form,"structured","Структурированный ответ (JSON)",JSON.stringify(task.draft.structured,null,2),"textarea");
    }
    if(task.candidate_test_contract) {form.append(node("p",task.candidate_test_contract));field(form,"tests","Собственные тесты (JSON)",JSON.stringify(task.draft.tests,null,2),"textarea");}
    const answer=()=>{const data=new FormData(form);return {source:data.get("source")||"",diagnosis:data.get("diagnosis")||"",verification:String(data.get("verification")||"").split(",").map(x=>x.trim()).filter(Boolean),structured:JSON.parse(String(data.get("structured")||"{}")),tests:JSON.parse(String(data.get("tests")||"[]"))};};
    let revision=task.revision;
    button(form,"Сохранить черновик",async()=>{const saved=await send(`/assessment/cycles/${cycle.id}/answers/${task.family}`,{revision,step:task.step,answer:answer()},"PUT");revision=saved.tasks.find(t=>t.family===task.family).revision;message("Черновик сохранён.");});
    submit(form,task.step==="base"?"Зафиксировать базу и открыть перенос":"Зафиксировать перенос",async()=>{await send(`/assessment/cycles/${cycle.id}/answers/${task.family}/fix`,{revision,step:task.step,answer:answer()});await render();});
  }
  if(["A","B"].includes(cycle.state)) button(content,`Сдать ${cycle.state} с сохранёнными черновиками`,async()=>{await send(`/assessment/cycles/${cycle.id}/submit/${cycle.state}`,{});await render();});
  if(cycle.state==="B_ready") button(content,"Начать B (15 минут)",async()=>{await send(`/assessment/cycles/${cycle.id}/start-b`,{});await render();});
  if(cycle.state==="completed"&&cycle.result.outcome==="confirmed") button(content,cycle.mode==="demo"?"Опубликовать демо-результат в своём профиле":"Опубликовать категорию",async()=>{await send(`/assessment/cycles/${cycle.id}/publish`,{});message("Выбор результата сохранён.");});
  const appeal=node("form");content.append(appeal);field(appeal,"message","Апелляция: опишите проблему", "", "textarea");
  submit(appeal,"Отправить апелляцию",async data=>{await send(`/assessment/cycles/${cycle.id}/appeals`,{message:data.get("message")});message("Апелляция зарегистрирована.");await render();});
}
