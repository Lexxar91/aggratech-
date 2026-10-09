"use strict";
let accessToken = null;
let user = null;
const content = document.getElementById("content");
const feedback = document.getElementById("feedback");
const csrf = () => decodeURIComponent(document.cookie.split("; ").find(v => v.startsWith("csrf_token="))?.split("=")[1] || "");
function message(text, error = false) { feedback.textContent = text; feedback.className = error ? "error" : "success"; }
async function request(path, options = {}, retry = true) {
  const headers = {"Content-Type": "application/json", ...options.headers};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (path === "/auth/refresh" || path === "/auth/logout") headers["X-CSRF-Token"] = csrf();
  const response = await fetch(`/api/v1${path}`, {...options, headers, credentials: "same-origin"});
  if (response.status === 401 && retry && accessToken && !path.startsWith("/auth/")) {
    await restore(); return request(path, options, false);
  }
  if (!response.ok) { const problem = await response.json(); throw new Error(problem.detail || "Запрос не выполнен"); }
  if (response.status === 204) return null;
  if (response.headers.get("Content-Type")?.startsWith("application/pdf")) return response.blob();
  return response.json();
}
const send = (path, body, method = "POST") => request(path, {method, body: JSON.stringify(body)});
async function restore() {
  const result = await request("/auth/refresh", {method: "POST"}, false);
  accessToken = result.access_token;
  user = await request("/auth/me", {}, false);
}
function node(tag, text = "") { const element = document.createElement(tag); element.textContent = text; return element; }
function field(form, name, title, value = "", type = "text") {
  const label = node("label", title);
  const input = document.createElement(type === "textarea" ? "textarea" : "input");
  input.name = name; input.id = name;
  if (type !== "textarea") input.type = type;
  if (type === "checkbox") input.checked = Boolean(value); else input.value = value ?? "";
  if (type === "password") { input.minLength = 12; input.maxLength = 128; input.autocomplete = "new-password"; input.required = true; }
  if (type === "email") input.required = true;
  label.append(input); form.append(label); return input;
}
function button(parent, text, action) {
  const element = node("button", text); element.type = "button";
  element.addEventListener("click", () => action().catch(error => message(error.message, true)));
  parent.append(element); return element;
}
function submit(form, text, action) {
  const element = node("button", text); element.type = "submit"; form.append(element);
  form.addEventListener("submit", async event => { event.preventDefault(); element.disabled = true;
    try { await action(new FormData(form)); } catch (error) { message(error.message, true); } finally { element.disabled = false; }
  });
}
function link(text, hash) { const element = node("a", text); element.href = hash; content.append(element); }
async function authScreen(route) {
  content.append(node("h1", route === "register" ? "Регистрация" : "Вход"));
  const form = node("form"); content.append(form);
  field(form, "email", "Email", "", "email"); field(form, "password", "Пароль (от 12 символов)", "", "password");
  if (route === "register") {
    const label = node("label", "Роль"); const select = node("select"); select.name = "role";
    for (const [value, text] of [["candidate", "Кандидат"], ["employer", "Работодатель"]]) { const option = node("option", text); option.value = value; select.append(option); }
    label.append(select); form.append(label);
  }
  submit(form, route === "register" ? "Зарегистрироваться" : "Войти", async data => {
    const email = data.get("email"); const password = data.get("password");
    if (route === "register") { await send("/auth/register", {email, password, role: data.get("role")}); message("Аккаунт создан. Письмо подтверждения отправлено."); }
    const result = await send("/auth/login", {email, password}); accessToken = result.access_token;
    user = await request("/auth/me"); form.reset(); location.hash = "#profile";
  });
  link(route === "register" ? "Уже есть аккаунт" : "Создать аккаунт", route === "register" ? "#login" : "#register");
  link("Восстановить пароль", "#reset-request");
}
async function actionScreen(route, token) {
  content.append(node("h1", route === "verify" ? "Подтверждение email" : "Новый пароль"));
  if (route === "verify") {
    button(content, "Подтвердить email", async () => { await send("/auth/verify-email", {token});
      if (accessToken) user = await request("/auth/me"); message("Email подтверждён."); location.hash = user ? "#profile" : "#login"; });
  } else {
    const form = node("form"); content.append(form); field(form, "new_password", "Новый пароль", "", "password");
    submit(form, "Изменить пароль", async data => { await send("/auth/password-reset/confirm", {token, password: data.get("new_password")}); accessToken = null; user = null; form.reset(); message("Пароль изменён. Войдите снова."); location.hash = "#login"; });
  }
}
async function resetScreen() {
  content.append(node("h1", "Восстановление пароля")); const form = node("form"); content.append(form);
  field(form, "reset_email", "Email", "", "email");
  submit(form, "Отправить ссылку", async data => { const result = await send("/auth/password-reset/request", {email: data.get("reset_email")}); message(result.detail); });
}
async function download(path) {
  const blob = await request(path); const url = URL.createObjectURL(blob);
  const anchor = node("a"); anchor.href = url; anchor.download = "profile.pdf"; anchor.click(); URL.revokeObjectURL(url);
}
async function candidateScreen() {
  const profile = await request("/candidate/profile");
  content.append(node("h2", "Ручной профиль"), node("p", "Зарплата: рубли в месяц до налогов (gross). Технологии заявлены самостоятельно; категория пока не подтверждена."));
  const form = node("form"); form.id = "candidate-profile"; content.append(form);
  field(form, "display_name", "Имя", profile.display_name); field(form, "summary", "Описание", profile.summary, "textarea");
  field(form, "experience", "Опыт", profile.experience, "textarea");
  field(form, "salary_min", "Зарплата от", profile.salary_min, "number"); field(form, "salary_max", "Зарплата до", profile.salary_max, "number");
  form.salary_min.step = "0.01"; form.salary_max.step = "0.01";
  field(form, "available_from", "Доступен с", profile.available_from, "date"); field(form, "location", "Город", profile.work_preferences.location);
  for (const format of ["remote", "hybrid", "office"]) field(form, `format_${format}`, {remote:"Удалённо",hybrid:"Гибрид",office:"Офис"}[format], profile.work_preferences.formats.includes(format), "checkbox");
  field(form, "confirm_preferences", "Подтверждаю актуальность предпочтений", Boolean(profile.preferences_confirmed_at), "checkbox");
  field(form, "consent", "Согласен на хранение профиля и публикацию карточки по выбранным настройкам (profile-v1)", Boolean(profile.consented_at), "checkbox");
  const technologies = await request("/catalog/technologies");
  for (const technology of technologies) field(form, `tech_${technology.id}`, technology.name, profile.technology_ids.includes(technology.id), "checkbox");
  submit(form, "Сохранить профиль", async data => {
    await send("/candidate/profile", {display_name:data.get("display_name"),summary:data.get("summary"),experience:data.get("experience"),
      salary_min:data.get("salary_min") || null,salary_max:data.get("salary_max") || null,available_from:data.get("available_from") || null,
      work_preferences:{location:data.get("location") || null,formats:["remote","hybrid","office"].filter(f => data.has(`format_${f}`))},
      technology_ids:technologies.filter(t => data.has(`tech_${t.id}`)).map(t => t.id),confirm_preferences:data.has("confirm_preferences"),consent_version:data.has("consent") ? "profile-v1" : null}, "PATCH"); message("Профиль сохранён.");
  });
  content.append(node("h2", "Закрытые контакты"));
  const contacts = await request("/candidate/contacts"); const contactForm = node("form"); contactForm.id = "contacts-form"; content.append(contactForm);
  field(contactForm,"contact_email","Контактный email",contacts.email,"email"); field(contactForm,"phone","Телефон",contacts.phone);
  field(contactForm,"telegram","Telegram",contacts.messengers.telegram || "");
  submit(contactForm,"Сохранить контакты",async data => { await send("/candidate/contacts",{email:data.get("contact_email"),phone:data.get("phone"),messengers:data.get("telegram") ? {telegram:data.get("telegram")} : {}},"PATCH"); message("Контакты сохранены."); });
  content.append(node("h2", "Приватность")); const privacyForm = node("form"); privacyForm.id = "privacy-form"; content.append(privacyForm);
  field(privacyForm,"visible_to_employers","Карточка видна работодателям после согласия",profile.privacy.visible_to_employers,"checkbox");
  field(privacyForm,"show_name","Показывать имя в карточке",profile.privacy.show_name,"checkbox");
  submit(privacyForm,"Сохранить приватность",async data => { await send("/candidate/privacy",{visible_to_employers:data.has("visible_to_employers"),show_name:data.has("show_name")},"PATCH"); message("Приватность сохранена."); });
  button(content,"Скачать мой PDF",async () => download("/candidate/profile.pdf"));
  content.append(node("h2","Блокировки компаний"));
  const companies = await request("/employers"); const blocked = new Set((await request("/candidate/blocks")).map(b => b.employer_id));
  for (const company of companies) { const row = node("div",company.company_name || "Компания без названия"); content.append(row);
    button(row, blocked.has(company.id) ? "Разблокировать" : "Заблокировать", async () => { await request(`/candidate/blocks/${company.id}`, {method: blocked.has(company.id) ? "DELETE" : "PUT"}); message("Блокировка сохранена."); await render(); }); }
}
async function employerScreen() {
  const profile = await request("/employer/profile"); const form = node("form"); form.id = "employer-profile"; content.append(form);
  field(form,"company_name","Название компании",profile.company_name); field(form,"description","Описание компании",profile.description,"textarea");
  field(form,"industry","Отрасль",profile.industry); field(form,"representative_contact","Контакт представителя",profile.representative_contact);
  submit(form,"Сохранить компанию",async data => { await send("/employer/profile", Object.fromEntries(data),"PATCH"); message("Компания сохранена."); });
}
async function render() {
  const [route = "home", rawToken] = location.hash.slice(1).split("/");
  content.replaceChildren();
  if (route === "register" || route === "login") return authScreen(route);
  if (route === "verify" || route === "reset") return actionScreen(route, decodeURIComponent(rawToken || ""));
  if (route === "reset-request") return resetScreen();
  if (["profile","candidate","employer"].includes(route)) {
    if (!user) { location.hash = "#login"; return; }
    content.append(node("h1",user.role === "candidate" ? "Кабинет кандидата" : "Кабинет работодателя"));
    content.append(node("p",user.email_verified ? "Email подтверждён." : "Email не подтверждён. Зачётная оценка недоступна."));
    if (!user.email_verified) button(content,"Повторить письмо подтверждения",async () => { const result = await send("/auth/resend-verification",{email:user.email}); message(result.detail); });
    button(content,"Выйти",async () => { await request("/auth/logout",{method:"POST"}); user=null; accessToken=null; location.hash="#login"; });
    return user.role === "candidate" ? candidateScreen() : employerScreen();
  }
  content.append(node("h1","Подбор по проверенным навыкам"),node("p","Создайте аккаунт кандидата или работодателя и заполните профиль."));
  link("Регистрация","#register"); link("Вход","#login");
}
window.addEventListener("hashchange",() => render().catch(error => message(error.message,true)));
(async () => { if (csrf()) { try { await restore(); } catch { user=null; accessToken=null; } }
  await render(); })().catch(error => message(error.message,true));
