import { t as translateText } from "./locale";
import { useDeferredValue, useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Folder,
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
  const registry = useData<Registry>("/registry");
  const done = ["success", "failed", "cancelled"].includes(r.status);
  const { busy, act } = useAction();
  const [stage, inspect] = useState("");
  const [connection, setConnection] = useState(
    translateText("Подключение к журналу…"),
  );
  useEffect(() => {
    if (done) return;
    const sse = new EventSource("/api/v1" + key + "/events");
    const refresh = () => void cache.invalidateQueries({ queryKey: [key] });
    sse.onopen = () => setConnection(translateText("Журнал подключён"));
    sse.onmessage = refresh;
    sse.addEventListener("done", () => {
      sse.close();
      refresh();
      void cache.invalidateQueries();
    });
    sse.onerror = () => {
      setConnection(translateText("Переподключение к журналу…"));
      refresh();
    };
    return () => sse.close();
  }, [key, done]);
  const complete = r.nodes.filter((n) =>
    ["success", "failed", "skipped", "cancelled"].includes(n.status),
  ).length;
  return (
    <>
      <Link className="back" to="/runs">
        <ChevronLeft size={14} />
        {translateText("История запусков")}
      </Link>
      <Heading
        title={r.workflow_name}
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
          {r.error}
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
          risks={Object.fromEntries(
            r.nodes.flatMap((n) =>
              n.output.levels ? [[n.node_id, n.output.levels]] : [],
            ),
          )}
          statuses={Object.fromEntries(
            r.nodes.map((n) => [n.node_id, n.status]),
          )}
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
                  {new Date(e.created * 1000).toLocaleTimeString("ru-RU")}
                </time>
                <div>
                  <b>{e.message}</b>
                  {e.node_id && (
                    <small>
                      {
                        registry.types[
                          r.graph.nodes.find((n) => n.id === e.node_id)?.type ||
                            ""
                        ]?.title
                      }{" "}
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
            {done
              ? r.count + translateText(" находок в итоговом отчёте.")
              : translateText("Данные появятся после выполнения графа.")}
          </p>
          {done && (
            <>
              {r.nodes
                .filter((n) => n.output.ai)
                .map((n) => {
                  const ai = n.output.ai!;
                  const labels: Record<string, string> = {
                    ok: translateText("Объяснения готовы"),
                    partial: `Объяснения получены для ${ai.explained} из ${ai.total} находок`,
                    no_findings: translateText("Нет находок для объяснения"),
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
                          {ai.summary}
                        </>
                      )}
                    </p>
                  );
                })}
              <Link
                className="button primary"
                to={
                  r.project_archived
                    ? "/findings?run_id=" + r.id
                    : "/projects/" + r.project_id + "?run_id=" + r.id
                }
              >
                {translateText("Результаты сессии")}
              </Link>
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
                      ? n.output.count + translateText(" находок")
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
  const data = useData<{
    valid: boolean;
    partial: boolean;
    count: number;
    levels: Record<string, number>;
    priorities: Finding[];
  }>("/runs/" + run + "/report/preview");
  const [chosen, choose] = useState<Finding | null>(null);
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
                  {f.title}
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
  const data = useData<{ output: unknown }>("/runs/" + run + "/nodes/" + node);
  return (
    <Modal title={translateText("Выход узла")} close={close}>
      <code>{node}</code>
      <pre className="block" style={{ whiteSpace: "pre-wrap" }}>
        {JSON.stringify(data.output, null, 2)}
      </pre>
    </Modal>
  );
}
function Detail({ f, close }: { f: Finding; close: () => void }) {
  return (
    <Modal title={f.title} close={close}>
      <div className="toolbar">
        <Severity value={f.severity} />
        <span className="tag">{f.category}</span>
      </div>
      <h3>{translateText("Расположение")}</h3>
      <code className="block">
        {f.path}:{f.line}
      </code>
      <h3>{translateText("Факт анализатора")}</h3>
      <p>{f.description}</p>
      <code className="block">{f.evidence}</code>
      {f.advisoryId && (
        <p>
          {f.advisoryId} · {f.aliases?.join(", ")}
        </p>
      )}
      <h3>{translateText("Исправление")}</h3>
      <p>{f.remediation}</p>
      {f.ai && (
        <section>
          <h3>
            {translateText("Объяснение AI ·")} {f.ai.model}
          </h3>
          <p>{f.ai.explanation}</p>
          <p>{f.ai.technical_details}</p>
          <p>
            <strong>{translateText("Возможные последствия")}</strong>{" "}
            {f.ai.business_impact}
          </p>
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
          <p>{f.ai.false_positive_notes}</p>
        </section>
      )}
      <small>{f.rule_id}</small>
      <Link className="button" to={"/runs/" + f.run_id}>
        {translateText("Открыть запуск")}
      </Link>
    </Modal>
  );
}
export function FindingsPage() {
  const { sessionId } = useParams();
  const [params] = useSearchParams();
  if (sessionId) return <SessionFindings sessionId={sessionId} />;
  if (params.has("run_id")) return <FindingTable />;
  return <FindingSessions key={params.get("severity") || ""} />;
}

function FindingSessions() {
  const [params, setParams] = useSearchParams();
  const level = params.get("severity") || "";
  const [offset, setOffset] = useState(0);
  const args = new URLSearchParams({ offset: String(offset), limit: "50" });
  if (level) args.set("severity", level);
  const sessions = useData<{ id: string; name: string; count: number }[]>(
    "/findings/sessions?" + args,
  );
  return (
    <>
      <Heading
        title={translateText("Находки")}
        sub={translateText("Выберите сессию, чтобы открыть её находки.")}
      />
      <div className="filters">
        <select
          aria-label={translateText("Критичность")}
          value={level}
          onChange={(e) => {
            const value = e.target.value;
            setParams(value ? { severity: value } : {});
          }}
        >
          <option value="">{translateText("Все уровни")}</option>
          {levels.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </select>
      </div>
      <section className="panel">
        {sessions.length ? (
          sessions.map((session) => (
            <Link
              className="finding-session"
              key={session.id}
              to={
                "/findings/" + session.id + (level ? "?severity=" + level : "")
              }
            >
              <Folder size={20} aria-hidden />
              <strong>{session.name}</strong>
              <small>
                {session.count} {translateText("· находки")}
              </small>
              <ChevronRight size={16} aria-hidden />
            </Link>
          ))
        ) : (
          <Empty title={translateText("Нет сессий с находками")}>
            {translateText("Проверьте фильтр или запустите проверку.")}
          </Empty>
        )}
      </section>
      <Pages
        offset={offset}
        set={setOffset}
        length={sessions.length}
        size={50}
      />
    </>
  );
}

function SessionFindings({ sessionId }: { sessionId: string }) {
  const session = useData<{ name: string }>("/findings/sessions/" + sessionId);
  return <FindingTable sessionId={sessionId} title={session.name} />;
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
  title,
  runId,
  summary,
  partial,
}: {
  sessionId?: string;
  title?: string;
  runId?: string;
  summary?: Record<string, number>;
  partial?: boolean;
}) {
  const [params] = useSearchParams();
  const [level, setLevel] = useState(params.get("severity") || "");
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
  if (level) args.set("severity", level);
  if (kind) args.set("category", kind);
  const selectedRun = runId || params.get("run_id");
  if (selectedRun) args.set("run_id", selectedRun);
  if (sessionId) args.set("project_id", sessionId);
  const path = "/findings?" + args;
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
      {!runId && (
        <>
          <Link className="back" to="/findings">
            <ChevronLeft size={14} />
            {translateText("Все сессии с находками")}
          </Link>
          <Heading
            title={title || translateText("Находки")}
            sub={
              params.has("run_id")
                ? translateText("Результаты выбранного запуска.")
                : translateText("Находки сессии по всем её запускам.")
            }
          />
        </>
      )}
      {summary && (
        <div
          className="session-severity"
          aria-label={translateText("Критичность находок")}
        >
          {levels
            .filter((l) => summary[l])
            .map((l) => (
              <button
                key={l}
                type="button"
                aria-pressed={level === l}
                onClick={() => {
                  setLevel(level === l ? "" : l);
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
            aria-label={translateText("Поиск находок")}
            placeholder={translateText("Путь, класс или advisory")}
            value={q}
            onChange={(e) => {
              search(e.target.value);
              set(0);
            }}
          />
        </label>
        {!runId && (
          <select
            aria-label={translateText("Критичность")}
            value={level}
            onChange={(e) => {
              setLevel(e.target.value);
              set(0);
            }}
          >
            <option value="">{translateText("Все уровни")}</option>
            {levels.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        )}
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
          {translateText("Не удалось загрузить находки.")}
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
                    <th>{translateText("Находка и расположение")}</th>
                    {!runId && <th>{translateText("Анализатор")}</th>}
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
                            {f.title}
                          </button>
                          <small className="mono">
                            {f.path}:{f.line}
                          </small>
                        </td>
                        {!runId && (
                          <td>
                            <code>{f.category}</code>
                          </td>
                        )}
                        <td>
                          <button
                            className="icon"
                            aria-label={translateText("Подробности находки")}
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
                ? translateText("Загружаем находки…")
                : translateText("Находок нет")
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
