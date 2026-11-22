import { t as translateText } from "./locale";
import { useDeferredValue, useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "react-router-dom";
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Search,
} from "lucide-react";
import {
  api,
  cache,
  date,
  duration,
  Finding,
  levels,
  Project,
  Registry,
  Run,
  RunDetails,
  RunEvent,
  useData,
} from "./api";
import {
  Empty,
  Heading,
  Modal,
  RunsTable,
  Severity,
  Status,
  useAction,
} from "./ui";
import { ReadonlyGraph } from "./editor";

function Pages({
  offset,
  set,
  length,
  size,
}: {
  offset: number;
  set: (n: number) => void;
  length: number;
  size: number;
}) {
  if (!offset && length < size) return null;
  return (
    <div className="pager">
      <button
        disabled={!offset}
        onClick={() => set(Math.max(0, offset - size))}
      >
        <ChevronLeft />
        {translateText("Назад")}
      </button>
      <span>
        {translateText("Страница")} {1 + offset / size}
      </span>
      <button disabled={length < size} onClick={() => set(offset + size)}>
        {translateText("Далее")}
        <ChevronRight />
      </button>
    </div>
  );
}
export function HistoryPage() {
  const [project, setProject] = useState("");
  const [status, setStatus] = useState("");
  const [offset, set] = useState(0);
  const projects = useData<Project[]>("/projects");
  const params = new URLSearchParams({ offset: String(offset), limit: "25" });
  if (project) params.set("project_id", project);
  if (status) params.set("status", status);
  const rows = useData<Run[]>("/runs?" + params);
  return (
    <>
      <Heading
        title={translateText("История запусков")}
        sub={translateText(
          "Проверки, версии сценариев и результаты выполнения.",
        )}
      />
      <div className="filters">
        <select
          aria-label={translateText("Проект")}
          value={project}
          onChange={(e) => {
            setProject(e.target.value);
            set(0);
          }}
        >
          <option value="">{translateText("Все проекты")}</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          aria-label={translateText("Статус")}
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            set(0);
          }}
        >
          <option value="">{translateText("Все статусы")}</option>
          <option value="success">{translateText("Завершён")}</option>
          <option value="failed">{translateText("Ошибка")}</option>
          <option value="running">{translateText("Выполняется")}</option>
          <option value="queued">{translateText("В очереди")}</option>
        </select>
      </div>
      <div className="panel">
        <RunsTable rows={rows} />
      </div>
      <Pages offset={offset} set={set} length={rows.length} size={25} />
    </>
  );
}
export function Monitor() {
  const { id } = useParams();
  const key = "/runs/" + id;
  const r = useData<RunDetails>(key);
  const location = useLocation();
  const registry = useData<Registry>("/registry");
  const done = ["success", "failed", "cancelled"].includes(r.status);
  const { busy, act } = useAction();
  const [stage, inspect] = useState("");
  const [sequenced] = useState(
    () =>
      (!done || !!location.state?.presentStages) &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [streamedStages, setStreamedStages] = useState<RunEvent[]>([]);
  const [revealed, reveal] = useState(0);
  const [connection, setConnection] = useState(
    translateText("Подключение к журналу…"),
  );
  useEffect(() => {
    if (done) return;
    const sse = new EventSource("/api/v1" + key + "/events");
    let timer: number | undefined;
    const refresh = () => {
      window.clearTimeout(timer);
      timer = undefined;
      void cache.invalidateQueries({ queryKey: [key], exact: true });
    };
    sse.onopen = () => setConnection(translateText("Журнал подключён"));
    sse.onmessage = (message) => {
      const event: RunEvent = JSON.parse(message.data);
      if (event.stage)
        setStreamedStages((previous) =>
          previous.some((item) => item.id === event.id)
            ? previous
            : [...previous, event],
        );
      timer ??= window.setTimeout(refresh, 100);
    };
    sse.addEventListener("done", () => {
      sse.close();
      refresh();
      void cache.invalidateQueries({ refetchType: "none" });
    });
    sse.onerror = () => {
      setConnection(translateText("Переподключение к журналу…"));
      refresh();
    };
    return () => {
      window.clearTimeout(timer);
      sse.close();
    };
  }, [key, done]);
  const mail = r.report_email;
  const mailPending = mail?.status === "queued" || mail?.status === "sending";
  useEffect(() => {
    if (!mailPending) return;
    const timer = window.setInterval(
      () => void cache.invalidateQueries({ queryKey: [key], exact: true }),
      2000,
    );
    return () => window.clearInterval(timer);
  }, [key, mailPending]);
  const stageEvents = [
    ...new Map(
      [...r.events, ...streamedStages]
        .filter((event) => event.stage)
        .map((event) => [event.id, event]),
    ).values(),
  ].sort((left, right) => left.id - right.id);
  const canReveal = sequenced && revealed < stageEvents.length;
  useEffect(() => {
    if (!canReveal) return;
    const timer = window.setTimeout(() => reveal((count) => count + 1), 320);
    return () => window.clearTimeout(timer);
  }, [canReveal, revealed]);
  const hidden = new Set(
    sequenced ? stageEvents.slice(revealed).map((event) => event.node_id) : [],
  );
  const stageById = new Map(
    stageEvents.map((event) => [event.node_id, event.stage]),
  );
  const revealingId = sequenced ? stageEvents[revealed]?.node_id : undefined;
  const waitingForStages = hidden.size > 0;
  const reportIds = new Set(
    r.graph.nodes
      .filter((node) => node.type === "report_generator")
      .map((node) => node.id),
  );
  const stageStatus = Object.fromEntries(
    r.nodes.map((node) => {
      const id = node.node_id;
      if (hidden.has(id))
        return [id, id === revealingId ? "running" : "pending"];
      if (waitingForStages && reportIds.has(id) && node.status === "success")
        return [id, "pending"];
      return [id, stageById.has(id) ? "success" : node.status];
    }),
  );
  const risks = Object.fromEntries(
    r.nodes.flatMap((node) => {
      if (stageStatus[node.node_id] !== "success") return [];
      const counts = stageById.get(node.node_id)?.levels ?? node.output.levels;
      return counts ? [[node.node_id, counts]] : [];
    }),
  );
  const complete = Object.values(stageStatus).filter((status) =>
    ["success", "failed", "skipped", "cancelled"].includes(status),
  ).length;
  return (
    <>
      <Link className="back" to="/runs">
        <ChevronLeft size={14} />
        {translateText("История запусков")}
      </Link>
      <Heading
        title={translateText(r.workflow_name)}
        sub={
          r.project_name +
          translateText(" · версия ") +
          r.revision +
          " · " +
          date(r.created)
        }
        action={
          <div className="toolbar">
            <Status value={r.status} />
            {!done && (
              <button
                disabled={busy || r.cancel_requested}
                onClick={() =>
                  void act(async () => {
                    await api(key + "/cancel", "POST");
                  })
                }
              >
                {r.cancel_requested
                  ? translateText("Завершается этап…")
                  : translateText("Отменить запуск")}
              </button>
            )}
          </div>
        }
      />
      {r.error && (
        <p className="errorline" role="alert">
          {translateText(r.error)}
        </p>
      )}
      {mail && (
        <p role="status">
          <strong>{translateText("Отчёт по почте")}</strong>
          {" · "}
          {translateText(
            {
              queued: "В очереди на отправку",
              sending: "Отправляется",
              accepted: "Принято почтовым сервером",
              skipped: "Отчёт не отправлен",
              failed: "Ошибка отправки",
              uncertain: "Приём письма не подтверждён",
            }[mail.status],
          )}
          {mail.error && (
            <>
              {" · "}
              {translateText(mail.error)}
            </>
          )}
        </p>
      )}
      <section className="panel">
        <div className="sectionHead">
          <h2>{translateText("Выполнение графа")}</h2>
          <span>
            {!done && connection + " · "}
            {complete} {translateText("из")} {r.nodes.length}{" "}
            {translateText("узлов ·")} {duration(r)}
          </span>
        </div>
        <ReadonlyGraph
          graph={r.graph}
          risks={risks}
          statuses={stageStatus}
          animate={sequenced}
          animatedResults={
            new Set(
              stageEvents.flatMap((event) =>
                event.node_id && !hidden.has(event.node_id)
                  ? [event.node_id]
                  : [],
              ),
            )
          }
        />
      </section>
      <div className="monitorgrid">
        <section className="panel">
          <div className="sectionHead">
            <h2>{translateText("Журнал событий")}</h2>
            <Activity size={18} />
          </div>
          <ol className="timeline">
            {r.events.map((e) => (
              <li key={e.id}>
                <time>
                  {new Date(e.created * 1000).toLocaleTimeString(
                    document.documentElement.lang === "en" ? "en-GB" : "ru-RU",
                  )}
                </time>
                <div>
                  <b>{translateText(e.message)}</b>
                  {e.node_id && (
                    <small>
                      {translateText(
                        registry.types[
                          r.graph.nodes.find((n) => n.id === e.node_id)?.type ||
                            ""
                        ]?.title || "",
                      )}{" "}
                      · {e.node_id}
                    </small>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </section>
        <section className="panel padded">
          <FileText />
          <h2>{translateText("Результат проверки")}</h2>
          <small className="mono">run / {r.id.slice(0, 12)}</small>
          <p>
            {done && !waitingForStages
              ? translateText("Обнаружено в итоговом отчёте:") + " " + r.count
              : translateText("Данные появятся после выполнения графа.")}
          </p>
          {done && !waitingForStages && (
            <>
              {r.nodes
                .filter((n) => n.output.ai)
                .map((n) => {
                  const ai = n.output.ai!;
                  const labels: Record<string, string> = {
                    ok: translateText("Объяснения готовы"),
                    partial:
                      translateText("Пояснено результатов:") +
                      ` ${ai.explained} / ${ai.total}`,
                    no_findings: translateText(
                      "Нет результатов для объяснения",
                    ),
                    ai_unavailable: translateText(
                      "Модель недоступна или ответ не прошёл проверку",
                    ),
                    invalid_input: translateText(
                      "Не удалось подтвердить исходные данные",
                    ),
                    invalid_configuration: translateText(
                      "Проверьте настройки провайдера",
                    ),
                  };
                  return (
                    <p key={n.node_id}>
                      <strong>AI · {ai.model}</strong>
                      <br />
                      {labels[ai.status] || ai.status}
                      {ai.summary && (
                        <>
                          <br />
                          {ai.summary.replace(
                            /^Пояснено [^:]+:/,
                            translateText("Пояснено результатов:"),
                          )}
                        </>
                      )}
                    </p>
                  );
                })}
              {!r.project_archived && (
                <Link
                  className="button primary"
                  to={"/projects/" + r.project_id + "?run_id=" + r.id}
                >
                  {translateText("Результаты сессии")}
                </Link>
              )}
              <ReportPreview run={r.id} />
              <div className="downloads">
                {["json", "txt"].map((f) => (
                  <a
                    key={f}
                    href={"/api/v1" + key + "/report?format=" + f}
                    download
                  >
                    <Download size={15} />
                    {f.toUpperCase()}
                  </a>
                ))}
              </div>
            </>
          )}
          <details>
            <summary>{translateText("Данные этапов")}</summary>
            {r.nodes.map((n) => (
              <p key={n.node_id}>
                <button className="textbtn" onClick={() => inspect(n.node_id)}>
                  {n.node_id}
                </button>
                <small>
                  {n.output.files !== undefined
                    ? n.output.files + translateText(" файлов")
                    : n.output.count !== undefined
                      ? n.output.count + translateText(" обнаружений")
                      : "—"}{" "}
                  {n.output.branch}
                </small>
              </p>
            ))}
          </details>
        </section>
      </div>
      {stage && <Stage run={r.id} node={stage} close={() => inspect("")} />}
    </>
  );
}
function ReportPreview({ run }: { run: string }) {
  const path = "/runs/" + run + "/report/preview";
  const { data, isError } = useQuery({
    queryKey: [path],
    queryFn: () =>
      api<{
        valid: boolean;
        partial: boolean;
        count: number;
        levels: Record<string, number>;
        priorities: Finding[];
      }>(path),
  });
  const [chosen, choose] = useState<Finding | null>(null);
  if (!data)
    return (
      <p role={isError ? "alert" : "status"}>
        {translateText(
          isError
            ? "Не удалось загрузить сводку отчёта."
            : "Загружаем сводку отчёта…",
        )}
      </p>
    );
  return (
    <div className="reportPreview">
      <h3>{translateText("Проверка перед экспортом")}</h3>
      <p>
        {data.valid && translateText("Структура JSON проверена")} · {data.count}{" "}
        {translateText("записей")}
      </p>
      {data.partial && (
        <p>
          {translateText(
            "Запуск завершился досрочно. В отчёт вошли результаты завершённых узлов отчёта.",
          )}
        </p>
      )}
      <p>
        {translateText("Критические:")} {data.levels.CRITICAL}{" "}
        {translateText("· Высокие:")} {data.levels.HIGH}
      </p>
      {data.priorities.length > 0 && (
        <details>
          <summary>{translateText("Порядок исправлений")}</summary>
          <ol>
            {data.priorities.map((f) => (
              <li key={f.id}>
                <button className="textbtn" onClick={() => choose(f)}>
                  {translateText(f.title)}
                </button>{" "}
                <Severity value={f.severity} />
              </li>
            ))}
          </ol>
        </details>
      )}
      <small>
        {translateText(
          "Проверены поддерживаемые правила Kotlin и снимок базы Maven. Динамическое поведение приложения требует отдельной проверки.",
        )}
      </small>
      {chosen && <Detail f={chosen} close={() => choose(null)} />}
    </div>
  );
}
function Stage({
  run,
  node,
  close,
}: {
  run: string;
  node: string;
  close: () => void;
}) {
  const path = "/runs/" + run + "/nodes/" + node;
  const { data, isError } = useQuery({
    queryKey: [path],
    queryFn: () => api<{ output: unknown }>(path),
  });
  return (
    <Modal title={translateText("Выход узла")} close={close}>
      <code>{node}</code>
      {data ? (
        <pre className="block" style={{ whiteSpace: "pre-wrap" }}>
          {JSON.stringify(data.output, null, 2)}
        </pre>
      ) : (
        <p role={isError ? "alert" : "status"}>
          {translateText(
            isError
              ? "Не удалось загрузить выход узла."
              : "Загружаем данные этапа…",
          )}
        </p>
      )}
    </Modal>
  );
}
function Detail({ f, close }: { f: Finding; close: () => void }) {
  return (
    <Modal title={translateText(f.title)} close={close}>
      <div className="toolbar">
        <Severity value={f.severity} />
        <span className="tag">{f.category}</span>
      </div>
      <h3>{translateText("Расположение")}</h3>
      <code className="block">
        {f.path}:{f.line}
      </code>
      <h3>{translateText("Факт анализатора")}</h3>
      <p>{translateText(f.description)}</p>
      <code className="block">{translateText(f.evidence)}</code>
      {f.advisoryId && (
        <p>
          {f.advisoryId} · {f.aliases?.join(", ")}
        </p>
      )}
      <h3>{translateText("Исправление")}</h3>
      <p>{translateText(f.remediation)}</p>
      {f.ai && (
        <section>
          <h3>
            {translateText("Объяснение AI ·")} {f.ai.model}
          </h3>
          <p>{f.ai.explanation}</p>
          {f.ai.technical_details && <p>{f.ai.technical_details}</p>}
          {f.ai.business_impact && (
            <p>
              <strong>{translateText("Возможные последствия")}</strong>{" "}
              {f.ai.business_impact}
            </p>
          )}
          <h4>{translateText("Шаги исправления")}</h4>
          <ol>
            {f.ai.remediation_steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
          <p>
            <strong>{translateText("Оценка модели")}</strong>{" "}
            {f.ai.evidence_status}
          </p>
          {f.ai.false_positive_notes && <p>{f.ai.false_positive_notes}</p>}
        </section>
      )}
      <small>{f.rule_id}</small>
      <Link className="button" to={"/runs/" + f.run_id}>
        {translateText("Открыть запуск")}
      </Link>
    </Modal>
  );
}
export function SessionResults({
  sessionId,
  runId,
}: {
  sessionId: string;
  runId: string;
}) {
  const run = useData<RunDetails>("/runs/" + runId);
  if (
    run.project_id !== sessionId ||
    !["success", "failed", "cancelled"].includes(run.status)
  ) {
    return (
      <Empty title={translateText("Результаты запуска пока недоступны")} />
    );
  }
  return <RunFindings sessionId={sessionId} runId={runId} />;
}

function RunFindings({
  sessionId,
  runId,
}: {
  sessionId: string;
  runId: string;
}) {
  const report = useData<{ levels: Record<string, number>; partial: boolean }>(
    "/runs/" + runId + "/report/preview",
  );
  return (
    <FindingTable
      sessionId={sessionId}
      runId={runId}
      summary={report.levels}
      partial={report.partial}
    />
  );
}

function FindingTable({
  sessionId,
  runId,
  summary,
  partial,
}: {
  sessionId: string;
  runId: string;
  summary: Record<string, number>;
  partial: boolean;
}) {
  const [selectedLevels, setSelectedLevels] = useState<string[]>([]);
  const [kind, setKind] = useState("");
  const [q, search] = useState("");
  const query = useDeferredValue(q);
  const [offset, set] = useState(0);
  const [group, setGroup] = useState(false);
  const [sort, setSort] = useState("severity");
  const [selected, select] = useState<Finding | null>(null);
  const args = new URLSearchParams({
    offset: String(offset),
    limit: "50",
    q: query,
    sort,
  });
  for (const level of levels) {
    if (selectedLevels.includes(level)) args.append("severity", level);
  }
  if (kind) args.set("category", kind);
  args.set("run_id", runId);
  args.set("project_id", sessionId);
  const path = "/results?" + args;
  const {
    data: rows = [],
    isFetching,
    isError,
  } = useQuery({
    queryKey: [path],
    queryFn: () => api<Finding[]>(path),
    placeholderData: keepPreviousData,
  });
  const groups = group
    ? Array.from(new Set(rows.map((f) => f.category)))
    : [""];
  return (
    <>
      {levels.some((level) => summary[level]) && (
        <div
          className="session-severity"
          role="group"
          aria-label={translateText("Критичность результатов")}
        >
          {levels
            .filter((l) => summary[l])
            .map((l) => (
              <button
                key={l}
                type="button"
                aria-pressed={selectedLevels.includes(l)}
                onClick={() => {
                  setSelectedLevels((current) =>
                    current.includes(l)
                      ? current.filter((level) => level !== l)
                      : [...current, l],
                  );
                  set(0);
                }}
              >
                <Severity value={l} /> {summary[l]}
              </button>
            ))}
        </div>
      )}
      {partial && (
        <p>
          {translateText(
            "Показаны результаты, сохранённые до завершения запуска.",
          )}
        </p>
      )}
      <div className="filters finding-toolbar">
        <label className="search">
          <Search />
          <input
            aria-label={translateText("Поиск по результатам")}
            placeholder={translateText("Путь, класс или advisory")}
            value={q}
            onChange={(e) => {
              search(e.target.value);
              set(0);
            }}
          />
        </label>
        <div className="finding-filters">
          <select
            aria-label={translateText("Категория")}
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              set(0);
            }}
          >
            <option value="">{translateText("Все анализаторы")}</option>
            {["SECRET", "SCA", "SAST"].map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
          <select
            aria-label={translateText("Сортировка")}
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              set(0);
            }}
          >
            <option value="severity">{translateText("По критичности")}</option>
            <option value="path">{translateText("По пути")}</option>
          </select>
          <label className="check">
            <input
              type="checkbox"
              checked={group}
              onChange={(e) => setGroup(e.target.checked)}
            />
            {translateText("Группировать")}
          </label>
        </div>
      </div>
      {isError ? (
        <p className="errorline" role="alert">
          {translateText("Не удалось загрузить результаты.")}
        </p>
      ) : rows.length ? (
        groups.map((g) => (
          <section className="panel" key={g}>
            {g && (
              <div className="sectionHead">
                <h2>{g}</h2>
              </div>
            )}
            <div className="scroll">
              <table>
                <thead>
                  <tr>
                    <th>{translateText("Критичность")}</th>
                    <th>{translateText("Результат и расположение")}</th>
                    <th aria-label={translateText("Детали")} />
                  </tr>
                </thead>
                <tbody>
                  {rows
                    .filter((f) => !g || f.category === g)
                    .map((f) => (
                      <tr key={f.run_id + f.id}>
                        <td>
                          <Severity value={f.severity} />
                        </td>
                        <td>
                          <button className="textbtn" onClick={() => select(f)}>
                            {translateText(f.title)}
                          </button>
                          <small className="mono">
                            {f.path}:{f.line}
                          </small>
                        </td>
                        <td>
                          <button
                            className="icon"
                            aria-label={translateText("Подробности результата")}
                            onClick={() => select(f)}
                          >
                            <ChevronRight />
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </section>
        ))
      ) : (
        <section className="panel">
          <Empty
            title={
              isFetching
                ? translateText("Загружаем результаты…")
                : translateText("Ничего не обнаружено")
            }
          >
            {!isFetching &&
              "Проверьте фильтры или запустите сценарий для проекта."}
          </Empty>
        </section>
      )}
      <Pages offset={offset} set={set} length={rows.length} size={50} />
      {selected && <Detail f={selected} close={() => select(null)} />}
    </>
  );
}
