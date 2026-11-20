import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Search,
} from "lucide-react";
import {
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
import { Empty, Heading, Modal, RunsTable, Severity, Status } from "./ui";
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
        Назад
      </button>
      <span>Страница {1 + offset / size}</span>
      <button disabled={length < size} onClick={() => set(offset + size)}>
        Далее
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
        title="История запусков"
        sub="Проверки, версии сценариев и результаты выполнения."
      />
      <div className="filters">
        <select
          aria-label="Проект"
          value={project}
          onChange={(e) => {
            setProject(e.target.value);
            set(0);
          }}
        >
          <option value="">Все проекты</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Статус"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            set(0);
          }}
        >
          <option value="">Все статусы</option>
          <option value="success">Завершён</option>
          <option value="failed">Ошибка</option>
          <option value="running">Выполняется</option>
          <option value="queued">В очереди</option>
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
  const [stage, inspect] = useState("");
  const [connection, setConnection] = useState("Подключение к журналу…");
  useEffect(() => {
    if (done) return;
    const sse = new EventSource("/api/v1" + key + "/events");
    const refresh = () => void cache.invalidateQueries({ queryKey: [key] });
    sse.onopen = () => setConnection("Журнал подключён");
    sse.onmessage = refresh;
    sse.addEventListener("done", () => {
      sse.close();
      refresh();
      void cache.invalidateQueries();
    });
    sse.onerror = () => {
      setConnection("Переподключение к журналу…");
      refresh();
    };
    return () => sse.close();
  }, [key, done]);
  const complete = r.nodes.filter((n) =>
    ["success", "failed", "skipped"].includes(n.status),
  ).length;
  return (
    <>
      <Link className="back" to="/runs">
        <ChevronLeft size={14} />
        История запусков
      </Link>
      <Heading
        title={r.workflow_name}
        sub={
          r.project_name + " · версия " + r.revision + " · " + date(r.created)
        }
        action={<Status value={r.status} />}
      />
      {r.error && (
        <p className="errorline" role="alert">
          {r.error}
        </p>
      )}
      <section className="panel">
        <div className="sectionHead">
          <h2>Выполнение графа</h2>
          <span>
            {!done && connection + " · "}
            {complete} из {r.nodes.length} узлов · {duration(r)}
          </span>
        </div>
        <ReadonlyGraph
          graph={r.graph}
          statuses={Object.fromEntries(
            r.nodes.map((n) => [n.node_id, n.status]),
          )}
        />
      </section>
      <div className="monitorgrid">
        <section className="panel">
          <div className="sectionHead">
            <h2>Журнал событий</h2>
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
          <h2>Результат проверки</h2>
          <small className="mono">run / {r.id.slice(0, 12)}</small>
          <p>
            {done
              ? r.count + " находок в итоговом отчёте."
              : "Данные появятся после выполнения графа."}
          </p>
          {done && (
            <>
              <Link className="button primary" to={"/findings?run_id=" + id}>
                Открыть находки
              </Link>
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
            <summary>Данные этапов</summary>
            {r.nodes.map((n) => (
              <p key={n.node_id}>
                <button className="textbtn" onClick={() => inspect(n.node_id)}>
                  {n.node_id}
                </button>
                <small>
                  {n.output.files !== undefined
                    ? n.output.files + " файлов"
                    : n.output.count !== undefined
                      ? n.output.count + " находок"
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
    <Modal title="Выход узла" close={close}>
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
      <h3>Расположение</h3>
      <code className="block">
        {f.path}:{f.line}
      </code>
      <h3>Факт анализатора</h3>
      <p>{f.description}</p>
      <code className="block">{f.evidence}</code>
      {f.advisoryId && (
        <p>
          {f.advisoryId} · {f.aliases?.join(", ")}
        </p>
      )}
      <h3>Исправление</h3>
      <p>{f.remediation}</p>
      <small>{f.rule_id}</small>
      <Link className="button" to={"/runs/" + f.run_id}>
        Открыть запуск
      </Link>
    </Modal>
  );
}
export function FindingsPage() {
  const [params] = useSearchParams();
  const [level, setLevel] = useState(params.get("severity") || "");
  const [kind, setKind] = useState("");
  const [q, search] = useState("");
  const [offset, set] = useState(0);
  const [group, setGroup] = useState(false);
  const [sort, setSort] = useState("severity");
  const [selected, select] = useState<Finding | null>(null);
  const args = new URLSearchParams({
    offset: String(offset),
    limit: "50",
    q,
    sort,
  });
  if (level) args.set("severity", level);
  if (kind) args.set("category", kind);
  if (params.get("run_id")) args.set("run_id", params.get("run_id")!);
  const rows = useData<Finding[]>("/findings?" + args);
  const groups = group
    ? Array.from(new Set(rows.map((f) => f.category)))
    : [""];
  return (
    <>
      <Heading
        title="Находки"
        sub={
          params.has("run_id")
            ? "Результаты выбранного запуска."
            : "Подтверждённые правилами результаты статических проверок."
        }
      />
      <div className="filters">
        <label className="search">
          <Search />
          <input
            aria-label="Поиск находок"
            placeholder="Путь, класс или advisory"
            value={q}
            onChange={(e) => {
              search(e.target.value);
              set(0);
            }}
          />
        </label>
        <select
          aria-label="Критичность"
          value={level}
          onChange={(e) => {
            setLevel(e.target.value);
            set(0);
          }}
        >
          <option value="">Все уровни</option>
          {levels.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </select>
        <select
          aria-label="Категория"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value);
            set(0);
          }}
        >
          <option value="">Все анализаторы</option>
          {["SECRET", "SCA", "SAST"].map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
        <select
          aria-label="Сортировка"
          value={sort}
          onChange={(e) => {
            setSort(e.target.value);
            set(0);
          }}
        >
          <option value="severity">По критичности</option>
          <option value="path">По пути</option>
        </select>
        <label className="check">
          <input
            type="checkbox"
            checked={group}
            onChange={(e) => setGroup(e.target.checked)}
          />
          Группировать
        </label>
      </div>
      {rows.length ? (
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
                    <th>Критичность</th>
                    <th>Находка и расположение</th>
                    <th>Анализатор</th>
                    <th />
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
                        <td>
                          <code>{f.category}</code>
                        </td>
                        <td>
                          <button
                            className="icon"
                            aria-label="Подробности находки"
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
          <Empty title="Находок нет">
            Проверьте фильтры или запустите сценарий для проекта.
          </Empty>
        </section>
      )}
      <Pages offset={offset} set={set} length={rows.length} size={50} />
      {selected && <Detail f={selected} close={() => select(null)} />}
    </>
  );
}
