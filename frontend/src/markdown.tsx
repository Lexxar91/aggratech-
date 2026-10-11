import type { ReactNode } from "react";

// React escapes all text; neither raw HTML nor executable links are accepted.
function inline(text: string): ReactNode[] {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith("`") ? <code key={index}>{part.slice(1, -1)}</code> :
      part.startsWith("**") ? <strong key={index}>{part.slice(2, -2)}</strong> : part,
  );
}
export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) continue;
    if (line.startsWith("```")) {
      const code: string[] = [];
      while (++i < lines.length && !lines[i].startsWith("```")) code.push(lines[i]);
      blocks.push(<pre key={i}><code>{code.join("\n")}</code></pre>);
    } else if (/^#{1,6} /.test(line)) {
      blocks.push(<h4 key={i}>{inline(line.replace(/^#{1,6} /, ""))}</h4>);
    } else if (line.includes("|") && /^\s*\|?\s*:?-+/.test(lines[i + 1] ?? "")) {
      const cells = (row: string) => row.replace(/^\s*\||\|\s*$/g, "").split("|");
      const headers = cells(line); i++;
      const rows: string[][] = [];
      while (i + 1 < lines.length && lines[i + 1].includes("|")) rows.push(cells(lines[++i]));
      blocks.push(<div className="table-scroll" key={i}><table><thead><tr>{headers.map((cell, n) => <th key={n}>{inline(cell)}</th>)}</tr></thead><tbody>{rows.map((row, n) => <tr key={n}>{row.map((cell, j) => <td key={j}>{inline(cell)}</td>)}</tr>)}</tbody></table></div>);
    } else if (/^\s*(?:[-*]|\d+\.) /.test(line)) {
      const items = [line];
      while (i + 1 < lines.length && /^\s*(?:[-*]|\d+\.) /.test(lines[i + 1])) items.push(lines[++i]);
      blocks.push(<ul key={i}>{items.map((item, n) => <li key={n}>{inline(item.replace(/^\s*(?:[-*]|\d+\.) /, ""))}</li>)}</ul>);
    } else {
      blocks.push(<p key={i}>{inline(line)}</p>);
    }
  }
  return <div className="markdown">{blocks}</div>;
}

export function TaskStatement({ condition, language, example }: { condition: string; language: string; example?: string }) {
  const [first, second] = condition.split(/\n\n## Вторая часть задания\n|\n\nПеренос:\n/);
  // Split prose only outside inline code: signatures and decimal values remain intact.
  const code: string[] = [];
  const protectedText = first.replace(/`[^`]*`/g, part => { code.push(part); return `INLINECODE${code.length - 1}END`; });
  const sentences = protectedText.split(/(?<=[.!?])\s+|\n\n/).map(part => part.replace(/INLINECODE(\d+)END/g, (_, index: string) => code[Number(index)]).trim()).filter(Boolean);
  const groups: Record<string, string[]> = { "Что нужно сделать": [], "Входные данные": [], "Что вернуть или изменить": [], "Ограничения задания": [] };
  sentences.forEach((sentence, index) => {
    const heading = /^(?:Таблиц|Каждая запись|Поля |Все поля|Параметр|principal|repo\.|Готовый|storage\.|fetch_page|send\(|sleep\(|ledger\.)/.test(sentence) ? "Входные данные" : index === 0 ? "Что нужно сделать" : /^(?:Верните|Вернуть|Возвращайте|Результат|Выведите|Пустая таблица|Вход пустой)/.test(sentence) ? "Что вернуть или изменить" : "Ограничения задания";
    groups[heading].push(sentence);
  });
  if (!groups["Что нужно сделать"].length) groups["Что нужно сделать"].push(language === "sql" ? "Напишите SQL-решение по указанным правилам." : "Реализуйте указанную функцию по условию.");
  return <div className="task-statement">
    {Object.entries(groups).map(([heading, parts]) => parts.length ? <section key={heading}><h4>{heading}</h4><Markdown text={parts.join("\n\n")} /></section> : null)}
    {example && <section><h4>Пример</h4><Markdown text={example} /></section>}
    {second && <section className="changed-condition"><h4>Вторая часть: изменённое условие</h4><Markdown text={second} /><p>Проверьте текущее решение и при необходимости измените его для новых условий.</p></section>}
    {language === "sql" && <section><h4>Типы и правила SQL</h4><p>Целочисленные столбцы используют bigint; значения и суммы помещаются в этот тип. Итоги SUM сравниваются как точные числа. Идентификаторы строк уникальны и столбцы NOT NULL, если в условии явно не сказано иначе. Порядок и состав результата задаёт условие.</p></section>}
    {language === "python" && /JSON|json/.test(condition) && <section><h4>Правила JSON</h4><p>Объекты не содержат повторных ключей и специальных чисел NaN или Infinity. Неуказанные дополнительные поля допустимы и не меняют правила.</p></section>}
    <section><h4>Среда выполнения</h4>{language === "sql" ? <p>PostgreSQL 18. Параметры вида <code>:name</code> передаются отдельно. Проверяется результат запроса; допустимы разные корректные запросы. Менять таблицы можно только если этого требует условие.</p> : <p>Python 3.14. Стандартная библиотека доступна. Реализуйте указанную функцию. Используйте только описанные выше объекты и методы; они предоставляются при запуске решения. Не изменяйте входные данные, если это не требуется условием. Импорт модуля не выполняет ввод-вывод; не используйте глобальное состояние между вызовами.</p>}<p>{language === "sql" ? "На запрос: 1,5 секунды; память 256 МБ." : "На отдельный запуск: 5 секунд; память 128 МБ."} Если условие не говорит иначе, числа целые, поля обязательны, строки сортируются в порядке ASCII. {language === "sql" ? "NULL допустим только там, где указан явно." : "None допустим только там, где указан явно."} Доступа к сети нет. Эти ограничения защищают среду выполнения и не являются оценкой скорости навыка.</p></section>
  </div>;
}
