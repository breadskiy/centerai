import { useEffect, useRef, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  Activity,
  Archive,
  ArrowUpRight,
  Braces,
  CalendarClock,
  ChevronRight,
  Copy,
  FileOutput,
  Folder,
  FolderGit2,
  KeyRound,
  Layers3,
  Network,
  Play,
  Plus,
  Search,
  Send,
  Settings2,
  ScanLine,
  Trash2,
  Upload,
  Workflow,
} from "lucide-react";
import {
  api,
  date,
  Flow,
  Graph,
  levels,
  Project,
  Registry,
  Run,
  Settings,
  useData,
} from "./api";
import { Button } from "./components/button";
import { ScheduleSettings } from "./schedules";
import { TemplateLibrary } from "./templates";
import { uploadForm, uploadProject } from "./upload";
import {
  Empty,
  Heading,
  Modal,
  RunsTable,
  Status,
  useAction,
  useNotice,
} from "./ui";

function Pipeline() {
  return (
    <div
      className="pipeline"
      aria-label="Граф проверки: исходники, три анализатора и отчёт"
    >
      <div className="pipeSource">
        <FolderGit2 />
        <span>Исходники</span>
      </div>
      <div className="fork leftFork" aria-hidden="true">
        <span />
      </div>
      <div className="pipes">
        {[
          [KeyRound, "Secrets"],
          [Layers3, "SCA"],
          [Braces, "SAST"],
        ].map(([Icon, name]) => {
          const I = Icon as typeof Braces;
          return (
            <div className="pipeNode" key={String(name)}>
              <I size={16} />
              {String(name)}
            </div>
          );
        })}
      </div>
      <div className="fork rightFork" aria-hidden="true">
        <span />
      </div>
      <div className="pipeEnd">
        <FileOutput />
        <span>Отчёт</span>
      </div>
    </div>
  );
}
export function Dashboard() {
  const data = useData<{
    projects: number;
    workflows: number;
    runs: number;
    findings: number;
    levels: Record<string, number>;
    recent: Run[];
  }>("/dashboard");
  const [dialog, setDialog] = useState(false);
  const [importError, setImportError] = useState("");
  const [mode, setMode] = useState("archive");
  const [archive, setArchive] = useState<File>();
  const [repository, setRepository] = useState("");
  const [profile, setProfile] = useState("full");
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const nav = useNavigate();
  const { act, busy } = useAction();
  const templates = useData<
    {
      workflow_id: string;
      revision: number;
      name: string;
      description: string;
    }[]
  >("/templates");
  const profiles = [
    { id: "full", name: "Полная проверка", description: "Secrets, SCA и SAST" },
    {
      id: "sca",
      name: "Только зависимости",
      description: "Версии библиотек Gradle и известные уязвимости",
    },
    {
      id: "secrets",
      name: "Только секреты",
      description: "Пароли, токены и ключи в исходниках",
    },
    {
      id: "sast",
      name: "Только код",
      description: "Статические правила для Kotlin и Spring",
    },
    {
      id: "ai",
      name: "Полная проверка с AI",
      description: "Три анализатора и пояснения модели",
    },
    ...templates.map((t) => ({
      id: t.workflow_id + ":" + t.revision,
      name: t.name + " · v" + t.revision,
      description: t.description || "Опубликованный шаблон",
    })),
  ];
  useEffect(() => {
    const isFile = (e: DragEvent) => e.dataTransfer?.types.includes("Files");
    const enter = (e: DragEvent) => {
      if (!isFile(e)) return;
      e.preventDefault();
      if (!busy) {
        dragDepth.current++;
        setDragging(true);
      }
    };
    const over = (e: DragEvent) => {
      if (isFile(e)) e.preventDefault();
    };
    const leave = () => {
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (!dragDepth.current) setDragging(false);
    };
    const reset = () => {
      dragDepth.current = 0;
      setDragging(false);
    };
    const drop = (e: DragEvent) => {
      reset();
      if (!isFile(e)) return;
      e.preventDefault();
      if (busy || !e.dataTransfer?.files.length) return;
      setArchive(e.dataTransfer.files[0]);
      setMode("archive");
      setDialog(true);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    window.addEventListener("blur", reset);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
      window.removeEventListener("blur", reset);
    };
  }, [busy]);
  const fileError =
    archive &&
    (!/\.(zip|rar|7z|tar|tar\.gz|tgz)$/i.test(archive.name)
      ? "Выберите ZIP, RAR, 7Z, TAR, TAR.GZ или TGZ."
      : archive.size > 24 * 1024 * 1024
        ? "Архив превышает 24 МБ."
        : "");
  return (
    <>
      <Heading title="Главная" />
      <section className="hero import-hero">
        <div className="heroText">
          <h2>Проверить репозиторий</h2>
          <p>
            Загрузите архив или вставьте ссылку GitHub, затем выберите профиль
            проверки Kotlin-проекта.
          </p>
          <Button className="button light" onClick={() => setDialog(true)}>
            <Upload size={16} />
            Загрузить репозиторий
          </Button>
        </div>
        <Pipeline />
      </section>
      {dragging && !dialog && (
        <div className="repo-drop">
          <Upload size={36} />
          <strong>Отпустите архив</strong>
          <span>Затем выберите профиль проверки</span>
        </div>
      )}
      {dialog && (
        <Modal
          title="Загрузить репозиторий"
          close={() => {
            if (!busy) setDialog(false);
          }}
        >
          {dragging && (
            <div className="repo-drop">
              <Upload size={36} />
              <strong>Отпустите архив</strong>
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const values = new FormData();
              if (mode === "archive" && archive) values.set("archive", archive);
              if (mode === "link") values.set("repository", repository.trim());
              values.set("profile", profile);
              setProgress(0);
              setImportError("");
              void act(async () => {
                try {
                  const run = await uploadForm<Run>(
                    "/api/v1/quick-scan",
                    values,
                    setProgress,
                  );
                  nav("/runs/" + run.id);
                } catch (error) {
                  setImportError(
                    error instanceof Error ? error.message : "Ошибка импорта",
                  );
                }
              });
            }}
          >
            <div className="seg" aria-label="Источник репозитория">
              <button
                type="button"
                disabled={busy}
                aria-pressed={mode === "archive"}
                className={mode === "archive" ? "on" : ""}
                onClick={() => setMode("archive")}
              >
                Архив
              </button>
              <button
                type="button"
                disabled={busy}
                aria-pressed={mode === "link"}
                className={mode === "link" ? "on" : ""}
                onClick={() => setMode("link")}
              >
                По ссылке
              </button>
            </div>
            {mode === "archive" ? (
              <>
                <label className="repo-file">
                  <Archive size={18} />
                  <span>
                    {archive?.name || "Выбрать архив"}
                    <small>ZIP, RAR, 7Z, TAR, TAR.GZ, TGZ · до 24 МБ</small>
                  </span>
                  <input
                    aria-label="Выбрать архив"
                    type="file"
                    disabled={busy}
                    accept=".zip,.rar,.7z,.tar,.gz,.tgz"
                    onChange={(e) => {
                      if (e.target.files?.[0]) setArchive(e.target.files[0]);
                    }}
                  />
                </label>
                {fileError && (
                  <p role="alert" className="errorline">
                    {fileError}
                  </p>
                )}
              </>
            ) : (
              <label>
                Ссылка на публичный GitHub-репозиторий
                <input
                  disabled={busy}
                  required
                  type="url"
                  value={repository}
                  placeholder="https://github.com/owner/repository"
                  onChange={(e) => setRepository(e.target.value)}
                />
              </label>
            )}
            <fieldset className="repo-profiles" disabled={busy}>
              <legend>Профиль проверки</legend>
              {profiles.map((p) => (
                <label className="repo-profile" key={p.id}>
                  <input
                    type="radio"
                    name="profile"
                    checked={profile === p.id}
                    onChange={() => setProfile(p.id)}
                  />
                  <span>
                    <strong>{p.name}</strong>
                    <small>{p.description}</small>
                  </span>
                </label>
              ))}
            </fieldset>
            {importError && (
              <p role="alert" className="errorline">
                {importError}
              </p>
            )}
            {busy && (
              <p role="status">
                {mode === "archive" && progress < 100
                  ? "Загрузка " + progress + "%"
                  : "Импортируем исходники и создаём запуск…"}
              </p>
            )}
            <Button
              disabled={
                busy ||
                (mode === "archive"
                  ? !archive || !!fileError
                  : !repository.trim())
              }
            >
              <Play size={16} />
              Запустить проверку
            </Button>
          </form>
        </Modal>
      )}
      <div className="metrics">
        {[
          [data.projects, "Сессии", "/projects", Folder],
          [data.workflows, "Сценарии", "/workflows", Workflow],
          [data.runs, "Запуски", "/runs", Activity],
          [data.findings, "Находки", "/findings", ScanLine],
        ].map(([n, label, path, icon]) => {
          const I = icon as typeof Folder;
          return (
            <Link key={String(path)} to={String(path)}>
              <span>
                <I size={16} />
                {String(label)}
              </span>
              <b>{String(n)}</b>
              <ArrowUpRight size={16} />
            </Link>
          );
        })}
      </div>
      <div className="dashgrid">
        <section className="panel">
          <div className="sectionHead">
            <h2>Последние запуски</h2>
            <Link to="/runs">
              История <ChevronRight size={14} />
            </Link>
          </div>
          <RunsTable rows={data.recent} />
        </section>
        <section className="panel">
          <div className="sectionHead">
            <h2>Критичность</h2>
          </div>
          <div className="riskList">
            {levels.map((l) => (
              <Link key={l} to={"/findings?severity=" + l}>
                <i className={l} />
                <span>{l}</span>
                <div>
                  <em
                    className={l}
                    style={{
                      width:
                        (100 * (data.levels[l] || 0)) /
                          Math.max(1, data.findings) +
                        "%",
                    }}
                  />
                </div>
                <b>{data.levels[l] || 0}</b>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
function ProjectForm({
  project,
  close,
}: {
  project?: Project;
  close: () => void;
}) {
  const [source, type] = useState("ZIP");
  const [file, setFile] = useState<File>();
  const [progress, setProgress] = useState(0);
  const { act, busy } = useAction();
  const nav = useNavigate();
  const show = useNotice((s) => s.show);
  return (
    <Modal title={project ? "Изменить проект" : "Новый проект"} close={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const values = new FormData(e.currentTarget);
          void act(async () => {
            const res = project
              ? await api<Project>("/projects/" + project.id, "PATCH", {
                  name: values.get("name"),
                  description: values.get("description"),
                })
              : await uploadProject(values, setProgress);
            show("Проект сохранён");
            close();
            nav("/projects/" + res.id);
          });
        }}
      >
        <label>
          Название
          <input
            name="name"
            autoFocus
            required
            maxLength={100}
            defaultValue={project?.name}
            placeholder="Например, Repair Desk"
          />
        </label>
        <label>
          Описание
          <textarea
            name="description"
            maxLength={2000}
            defaultValue={project?.description}
            placeholder="Что проверяем в этом проекте"
          />
        </label>
        {!project && (
          <>
            <div className="seg">
              {["ZIP", "GitHub"].map((s) => (
                <button
                  type="button"
                  key={s}
                  className={s === source ? "on" : ""}
                  onClick={() => type(s)}
                >
                  {s}
                </button>
              ))}
            </div>
            {source === "ZIP" ? (
              <label className="upload">
                <Upload />
                {file
                  ? file.name + " · " + Math.ceil(file.size / 1024) + " КБ"
                  : "Выберите ZIP с проектом"}
                <small>Gradle Kotlin DSL · до 24 МБ</small>
                <input
                  required
                  type="file"
                  name="archive"
                  accept=".zip"
                  onChange={(e) => setFile(e.target.files?.[0])}
                />
              </label>
            ) : (
              <label>
                Ссылка на учебный репозиторий
                <input
                  required
                  type="url"
                  name="repository"
                  defaultValue="https://github.com/TBagirov/training"
                />
              </label>
            )}
          </>
        )}
        {busy && !project && (
          <label>
            {progress < 100
              ? "Загрузка " + progress + "%"
              : "Проверяем исходники…"}
            <progress max={100} value={progress} />
          </label>
        )}
        <button className="primary" disabled={busy}>
          {busy ? "Сохраняем…" : project ? "Сохранить" : "Создать проект"}
        </button>
      </form>
    </Modal>
  );
}
export function Projects() {
  const list = useData<Project[]>("/projects");
  const [query, set] = useState("");
  const [kind, filter] = useState("");
  const [params] = useSearchParams();
  const [open, toggle] = useState(params.has("new"));
  const rows = list.filter(
    (p) =>
      (!kind || p.source_type === kind) &&
      (p.name + " " + p.description)
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <>
      <Heading
        title="Сессии"
        sub="Исходники и история проверок каждого проекта."
        action={
          <button className="primary" onClick={() => toggle(true)}>
            <Plus />
            Новый проект
          </button>
        }
      />
      <div className="filters">
        <label className="search">
          <Search />
          <input
            aria-label="Поиск проектов"
            placeholder="Поиск проектов"
            value={query}
            onChange={(e) => set(e.target.value)}
          />
        </label>
        <select
          aria-label="Тип источника"
          value={kind}
          onChange={(e) => filter(e.target.value)}
        >
          <option value="">Все источники</option>
          <option>ZIP</option>
          <option>Архив</option>
          <option>GitHub</option>
        </select>
      </div>
      <section className="panel">
        {rows.length ? (
          rows.map((p) => (
            <Link className="projectrow" key={p.id} to={"/projects/" + p.id}>
              <span className="bigicon">
                <FolderGit2 />
              </span>
              <div>
                <b>{p.name}</b>
                <small>{p.description || p.source}</small>
              </div>
              <span className="tag">{p.source_type}</span>
              <span>{p.file_count} файлов</span>
              <ChevronRight />
            </Link>
          ))
        ) : (
          <Empty
            title={
              list.length ? "Сессии не найдены" : "Добавьте первую сессию"
            }
          >
            Загрузите ZIP или подключите учебный репозиторий GitHub.
          </Empty>
        )}
      </section>
      {open && <ProjectForm close={() => toggle(false)} />}
    </>
  );
}
export function ProjectDetail() {
  const { id } = useParams();
  const p = useData<Project>("/projects/" + id);
  const runs = useData<Run[]>("/runs?project_id=" + id);
  const [edit, setEdit] = useState(false);
  const { act } = useAction();
  const nav = useNavigate();
  return (
    <>
      <Heading
        title={p.name}
        sub={p.description || "Проект статического анализа"}
        action={
          <button onClick={() => setEdit(true)}>
            <Settings2 />
            Изменить
          </button>
        }
      />
      <section className="panel detailgrid">
        <div>
          <small>Источник</small>
          <b>{p.source_type}</b>
          <code>{p.source}</code>
        </div>
        <div>
          <small>Файлы для проверки</small>
          <b>{p.file_count}</b>
        </div>
        <div>
          <small>Последний запуск</small>
          <b>{date(p.last_run)}</b>
        </div>
      </section>
      <div className="toolbar">
        <Link
          className="button primary"
          to={"/workflows?project=" + id + "&new=1"}
        >
          <Plus />
          Создать сценарий
        </Link>
        <Link className="button" to={"/workflows?project=" + id}>
          Сценарии сессии
        </Link>
        <Link className="button" to={"/findings/" + p.id}>
          Открыть находки
        </Link>
        <button
          className="danger"
          onClick={() => {
            if (
              confirm(
                "Удалить проект и его сценарии? История проверок сохранится.",
              )
            )
              void act(async () => {
                await api("/projects/" + id, "DELETE");
                nav("/projects");
              });
          }}
        >
          <Trash2 />
          Удалить
        </button>
      </div>
      <section className="panel">
        <div className="sectionHead">
          <h2>Проверки сессии</h2>
        </div>
        <RunsTable rows={runs} />
      </section>
      {edit && <ProjectForm project={p} close={() => setEdit(false)} />}
    </>
  );
}
function NewFlow({
  projects,
  project,
  close,
}: {
  projects: Project[];
  project: string;
  close: () => void;
}) {
  const registry = useData<Registry>("/registry");
  const [start, setStart] = useState("base");
  const { act, busy } = useAction();
  const nav = useNavigate();
  return (
    <Modal title="Новый сценарий" close={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const v = new FormData(e.currentTarget);
          void act(async () => {
            let graph: Graph = registry.default_graph;
            if (v.get("start") === "blank")
              graph = { nodes: [graph.nodes[0]], edges: [] };
            if (v.get("start") === "ai" && registry.ai_graph)
              graph = registry.ai_graph;
            if (start === "prompt")
              graph = await api<Graph>("/workflow-drafts", "POST", {
                description: v.get("prompt"),
              });
            const f = await api<Flow>("/workflows", "POST", {
              name: v.get("name"),
              description: v.get("description"),
              project_id: v.get("project"),
              graph,
            });
            close();
            nav("/workflows/" + f.id);
          });
        }}
      >
        <label>
          Название
          <input
            name="name"
            required
            maxLength={100}
            defaultValue="Проверка исходного кода"
          />
        </label>
        <label>
          Описание
          <textarea name="description" maxLength={2000} />
        </label>
        <label>
          Проект
          <select
            required
            name="project"
            defaultValue={project || projects[0]?.id}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Начальный граф
          <select
            name="start"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          >
            <option value="base">Три анализатора и отчёт</option>
            {registry.ai_graph && (
              <option value="ai">Три анализатора, AI и отчёт</option>
            )}
            <option value="blank">Только триггер</option>
            <option value="prompt">По описанию с AI</option>
          </select>
        </label>
        {start === "prompt" && (
          <label>
            Что проверить
            <textarea
              name="prompt"
              required
              minLength={3}
              maxLength={2000}
              placeholder="По будням в 9 утра проверяй зависимости и присылай критические находки по почте"
            />
            <small>
              Модель получит текст задания. Проверьте черновик в редакторе.
              Расписание включается вручную.
            </small>
          </label>
        )}
        {!projects.length && (
          <Link to="/projects?new=1">Сначала добавьте проект</Link>
        )}
        <button className="primary" disabled={busy || !projects.length}>
          {busy && start === "prompt"
            ? "Подготавливаем схему…"
            : "Открыть редактор"}
        </button>
      </form>
    </Modal>
  );
}
export function Workflows() {
  const flows = useData<Flow[]>("/workflows");
  const projects = useData<Project[]>("/projects");
  const [params] = useSearchParams();
  const [project, setProject] = useState(params.get("project") || "");
  const [open, toggle] = useState(params.has("new"));
  const { act, busy } = useAction();
  const nav = useNavigate();
  const rows = flows.filter((f) => !project || f.project_id === project);
  return (
    <>
      <Heading
        title="Сценарии"
        sub="Графы анализа и правила передачи результатов."
        action={
          <button className="primary" onClick={() => toggle(true)}>
            <Plus />
            Новый сценарий
          </button>
        }
      />
      <div className="filters">
        <select
          aria-label="Фильтр проекта"
          value={project}
          onChange={(e) => setProject(e.target.value)}
        >
          <option value="">Все проекты</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
      <section className="panel">
        {rows.length ? (
          rows.map((f) => (
            <article className="flowrow" key={f.id}>
              <div className="bigicon">
                <Network />
              </div>
              <div className="grow">
                <Link to={"/workflows/" + f.id}>
                  <b>{f.name}</b>
                </Link>
                {f.description && <p>{f.description}</p>}
                <small>
                  {projects.find((p) => p.id === f.project_id)?.name} ·{" "}
                  {f.graph.nodes.length} узлов · v{f.revision}
                </small>
                <small>
                  Изменён {date(f.updated)} · запуск {date(f.last_run)}
                </small>
              </div>
              <Status value={f.last_status} />
              <button
                className="icon"
                title="Скопировать"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    const copy = await api<Flow>("/workflows", "POST", {
                      ...f,
                      name: f.name.slice(0, 90) + " (копия)",
                    });
                    nav("/workflows/" + copy.id);
                  })
                }
              >
                <Copy />
              </button>
              <button
                className="icon"
                title="Удалить сценарий"
                disabled={busy}
                onClick={() => {
                  if (confirm("Удалить сценарий?"))
                    void act(async () => {
                      await api("/workflows/" + f.id, "DELETE");
                    });
                }}
              >
                <Trash2 />
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    const r = await api<Run>(
                      "/workflows/" + f.id + "/runs",
                      "POST",
                    );
                    nav("/runs/" + r.id);
                  })
                }
              >
                <Play />
                Запуск
              </button>
            </article>
          ))
        ) : (
          <Empty title="Сценариев пока нет">
            Создайте граф из базовой проверки или начните с одного триггера.
          </Empty>
        )}
      </section>
      <TemplateLibrary flows={flows} projects={projects} project={project} />
      {open && (
        <NewFlow
          projects={projects}
          project={project}
          close={() => toggle(false)}
        />
      )}
    </>
  );
}
function CISettings({ flows }: { flows: Flow[] }) {
  const [selected, select] = useState(
    () => localStorage.getItem("ci-flow") || "",
  );
  const [gate, setGate] = useState(() => localStorage.getItem("ci-gate") || "");
  const [timeout, setTimeoutValue] = useState(
    () => Number(localStorage.getItem("ci-timeout")) || 180,
  );
  const flow = flows.find((f) => f.id === selected) || flows[0];
  const { act } = useAction();
  const show = useNotice((s) => s.show);
  const command =
    flow &&
    `python scripts/ci_scan.py --workflow ${flow.id} --url ${location.origin} --timeout ${timeout}${gate ? " --fail-on " + gate : ""}`;
  return (
    <section className="panel padded">
      <h2>CI/CD</h2>
      {flow ? (
        <>
          <label>
            Сценарий для CI
            <select
              value={flow.id}
              onChange={(e) => {
                select(e.target.value);
                localStorage.setItem("ci-flow", e.target.value);
              }}
            >
              {flows.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Завершать CI с ошибкой
            <select
              value={gate}
              onChange={(e) => {
                setGate(e.target.value);
                localStorage.setItem("ci-gate", e.target.value);
              }}
            >
              <option value="">Только при сбое запуска</option>
              {["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"].map((l) => (
                <option key={l} value={l}>
                  {l} и выше
                </option>
              ))}
            </select>
          </label>
          <label>
            Ожидание, секунд
            <input
              type="number"
              min="1"
              max="86400"
              value={timeout}
              onChange={(e) => {
                const n = Math.min(
                  86400,
                  Math.max(1, Number(e.target.value) || 1),
                );
                setTimeoutValue(n);
                localStorage.setItem("ci-timeout", String(n));
              }}
            />
          </label>
          <pre
            className="block"
            style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
          >
            {command}
          </pre>
          <button
            onClick={() =>
              void act(async () => {
                await navigator.clipboard.writeText(command!);
                show("Команда скопирована");
              })
            }
          >
            Скопировать команду
          </button>
          <p>
            Выполните из корня репозитория на runner с доступом к этому адресу.
            Параметры сохраняются в этом браузере. Файлы результата появятся в
            reports.
          </p>
        </>
      ) : (
        <p>Создайте сценарий, чтобы подготовить команду запуска.</p>
      )}
    </section>
  );
}

function ThemeSettings() {
  const [theme, setTheme] = useState(
    document.documentElement.dataset.theme || "system",
  );
  return (
    <section className="panel padded theme-settings">
      <h2>Внешний вид</h2>
      <label>
        Тема
        <select
          value={theme}
          onChange={(event) => {
            const preference = event.target.value;
            setTheme(preference);
            if (preference === "system")
              delete document.documentElement.dataset.theme;
            else document.documentElement.dataset.theme = preference;
            try {
              localStorage.setItem("centerai-theme", preference);
            } catch {}
          }}
        >
          <option value="light">Светлая</option>
          <option value="dark">Тёмная</option>
          <option value="system">Как в системе</option>
        </select>
      </label>
    </section>
  );
}

export function SettingsPage() {
  const s = useData<Settings>("/settings");
  const flows = useData<Flow[]>("/workflows");
  const { act, busy } = useAction();
  const show = useNotice((n) => n.show);
  return (
    <>
      <Heading
        title="Настройки"
        sub="Доставка отчётов и параметры рабочего пространства."
      />
      <ThemeSettings />
      <div className="settingsgrid">
        <section className="panel padded">
          <Send />
          <h2>Telegram</h2>
          <p>
            {s.telegram
              ? "Параметры бота сохранены."
              : "Подключите бота для отправки отчётов из сценариев."}
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = e.currentTarget;
              const v = new FormData(form);
              void act(async () => {
                await api(
                  "/integrations/telegram",
                  "PUT",
                  Object.fromEntries(v),
                );
                form.reset();
                show("Настройки сохранены");
              });
            }}
          >
            <label>
              Токен бота
              <input
                name="token"
                type="password"
                autoComplete="new-password"
                required={!s.telegram}
                placeholder={
                  s.telegram ? "•••••••• (сохранён)" : "Токен BotFather"
                }
              />
            </label>
            <label>
              Идентификатор чата
              <input required name="chat" placeholder="Например, -100…" />
            </label>
            <div className="toolbar">
              <button className="primary" disabled={busy}>
                Сохранить
              </button>
              <button
                type="button"
                disabled={busy || !s.telegram}
                onClick={() =>
                  void act(async () => {
                    await api("/integrations/telegram/test", "POST");
                    show("Telegram подтвердил доставку");
                  })
                }
              >
                Тест доставки
              </button>
            </div>
          </form>
        </section>
        <div>
          <section className="panel padded">
            <h2>Электронная почта</h2>
            {s.demo_mailbox && (
              <p>
                <a
                  href="http://127.0.0.1:8025"
                  target="_blank"
                  rel="noreferrer"
                >
                  Открыть тестовый почтовый ящик
                </a>
                . В этом режиме все письма остаются на компьютере.
              </p>
            )}
            <p>
              {s.smtp
                ? "SMTP задан на сервере."
                : "Для отправки задайте SMTP_HOST и параметры почтового сервера."}
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const recipient = new FormData(e.currentTarget).get(
                  "recipient",
                );
                void act(async () => {
                  await api("/integrations/email", "PUT", { recipient });
                  show("Получатель сохранён");
                });
              }}
            >
              <label>
                Адрес получателя
                <input
                  name="recipient"
                  required
                  type="email"
                  defaultValue={s.email_recipient}
                />
              </label>
              <div className="toolbar">
                <button disabled={busy}>Сохранить адрес</button>
                <button
                  type="button"
                  disabled={busy || !s.smtp || !s.email_recipient}
                  onClick={() =>
                    void act(async () => {
                      await api("/integrations/email/test", "POST");
                      show("SMTP-сервер принял письмо");
                    })
                  }
                >
                  Тестовое письмо
                </button>
              </div>
            </form>
          </section>
          <CISettings flows={flows} />
          <section className="panel padded">
            <CalendarClock />
            <h2>Расписание</h2>
            <ScheduleSettings flows={flows} />
          </section>
          <section className="panel padded">
            <Archive />
            <h2>Источники GitHub</h2>
            {s.repositories.map((r) => (
              <code key={r}>{r}</code>
            ))}
          </section>
        </div>
      </div>
    </>
  );
}
