import { t as translateText, useLanguage } from "./locale";
import { useTheme, type ThemePreference } from "./theme";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  Archive,
  Braces,
  ChevronRight,
  Copy,
  FileOutput,
  FolderGit2,
  KeyRound,
  Layers3,
  Network,
  Play,
  Plus,
  Search,
  Settings2,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { api, date, Flow, Graph, Project, Registry, Run, useData } from "./api";
import { Button } from "./components/button";
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

const SessionResults = lazy(() =>
  import("./results").then((module) => ({ default: module.SessionResults })),
);

const archiveAccept = ".zip,.rar,.7z,.tar,.tar.gz,.tgz";
function archiveError(file?: File) {
  if (!file) return "";
  if (!/\.(zip|rar|7z|tar|tar\.gz|tgz)$/i.test(file.name))
    return translateText("Выберите ZIP, RAR, 7Z, TAR, TAR.GZ или TGZ.");
  return file.size > 24 * 1024 * 1024
    ? translateText("Архив превышает 24 МБ.")
    : "";
}

function Pipeline() {
  return (
    <div
      className="pipeline"
      aria-label={translateText(
        "Граф проверки: исходники, три анализатора и отчёт",
      )}
    >
      <div className="pipeSource">
        <FolderGit2 />
        <span>{translateText("Исходники")}</span>
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
        <span>{translateText("Отчёт")}</span>
      </div>
    </div>
  );
}

function DeleteSessionButton({
  id,
  onDelete,
  iconOnly = false,
  sessionName,
}: {
  id?: string;
  onDelete?: () => void;
  iconOnly?: boolean;
  sessionName?: string;
}) {
  const { act, busy } = useAction();
  const show = useNotice((state) => state.show);
  const label = translateText(
    id ? "Удалить сессию" : "Очистить историю сессий",
  );
  return (
    <button
      type="button"
      className={
        id
          ? iconOnly
            ? "icon danger session-remove"
            : "danger"
          : "danger session-clear"
      }
      aria-label={iconOnly ? label + " · " + sessionName : undefined}
      title={iconOnly ? label : undefined}
      disabled={busy}
      onClick={() => {
        const prompt = id
          ? "Удалить сессию вместе с исходниками, сценариями и отчётами? Это действие нельзя отменить."
          : "Очистить историю сессий? Завершённые запуски и их отчёты будут удалены. Сессии, исходники и сценарии сохранятся.";
        if (!window.confirm(translateText(prompt))) return;
        void act(async () => {
          await api(id ? "/projects/" + id : "/runs", "DELETE");
          onDelete?.();
          show(translateText(id ? "Сессия удалена" : "История сессий очищена"));
        });
      }}
    >
      <Trash2 size={16} />
      {!iconOnly && label}
    </button>
  );
}

export function Dashboard() {
  const data = useData<{
    projects: number;
    runs: number;
    recent: Run[];
  }>("/dashboard");
  const [dialog, setDialog] = useState(false);
  const [profileForm, setProfileForm] = useState(false);
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
    {
      id: "full",
      name: translateText("Полная проверка"),
      description: translateText("Secrets, SCA и SAST"),
    },
    {
      id: "sca",
      name: translateText("Только зависимости"),
      description: translateText(
        "Версии библиотек Gradle и известные уязвимости",
      ),
    },
    {
      id: "secrets",
      name: translateText("Только секреты"),
      description: translateText("Пароли, токены и ключи в исходниках"),
    },
    {
      id: "sast",
      name: translateText("Только код"),
      description: translateText("Статические правила для Kotlin и Spring"),
    },
    {
      id: "ai",
      name: translateText("Полная проверка с AI"),
      description: translateText("Три анализатора и пояснения модели"),
    },
    ...templates.map((t) => ({
      id: t.workflow_id + ":" + t.revision,
      name: t.name + " · v" + t.revision,
      description: t.description || "Опубликованный шаблон",
    })),
  ];
  useEffect(() => {
    if (profileForm) return;
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
  }, [busy, profileForm]);
  const fileError = archiveError(archive);
  return (
    <>
      <Heading title={translateText("Главная")} />
      <section className="hero import-hero">
        <div className="heroText">
          <h2>{translateText("Проверить репозиторий")}</h2>
          <p>
            {translateText(
              "Загрузите архив или вставьте ссылку GitHub, затем выберите профиль проверки Kotlin-проекта.",
            )}
          </p>
          <Button className="button light" onClick={() => setDialog(true)}>
            <Upload size={16} />
            {translateText("Загрузить репозиторий")}
          </Button>
        </div>
        <Pipeline />
      </section>
      {dragging && !dialog && (
        <div className="repo-drop">
          <Upload size={36} />
          <strong>{translateText("Отпустите архив")}</strong>
          <span>{translateText("Затем выберите профиль проверки")}</span>
        </div>
      )}
      {dialog && (
        <Modal
          title={translateText("Загрузить репозиторий")}
          close={() => {
            if (!busy) setDialog(false);
          }}
        >
          {dragging && (
            <div className="repo-drop">
              <Upload size={36} />
              <strong>{translateText("Отпустите архив")}</strong>
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
                  nav("/runs/" + run.id, { state: { presentStages: true } });
                } catch (error) {
                  setImportError(
                    error instanceof Error
                      ? error.message
                      : translateText("Ошибка импорта"),
                  );
                }
              });
            }}
          >
            <div
              className="seg"
              aria-label={translateText("Источник репозитория")}
            >
              <button
                type="button"
                disabled={busy}
                aria-pressed={mode === "archive"}
                className={mode === "archive" ? "on" : ""}
                onClick={() => setMode("archive")}
              >
                {translateText("Архив")}
              </button>
              <button
                type="button"
                disabled={busy}
                aria-pressed={mode === "link"}
                className={mode === "link" ? "on" : ""}
                onClick={() => setMode("link")}
              >
                {translateText("По ссылке")}
              </button>
            </div>
            {mode === "archive" ? (
              <>
                <label className="repo-file">
                  <Archive size={18} />
                  <span>
                    {archive?.name || translateText("Выбрать архив")}
                    <small>
                      {translateText(
                        "ZIP, RAR, 7Z, TAR, TAR.GZ, TGZ · до 24 МБ",
                      )}
                    </small>
                  </span>
                  <input
                    aria-label={translateText("Выбрать архив")}
                    type="file"
                    disabled={busy}
                    accept={archiveAccept}
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
                {translateText("Ссылка на публичный GitHub-репозиторий")}
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
              <legend>{translateText("Профиль проверки")}</legend>
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
              <button
                type="button"
                className="repo-profile repo-new-profile"
                disabled={busy}
                onClick={() => {
                  setDialog(false);
                  setProfileForm(true);
                }}
              >
                <Plus size={16} />
                {translateText("Новый профиль")}
              </button>
            </fieldset>
            {importError && (
              <p role="alert" className="errorline">
                {translateText(importError)}
              </p>
            )}
            {busy && (
              <p role="status">
                {mode === "archive" && progress < 100
                  ? translateText("Загрузка ") + progress + "%"
                  : translateText("Импортируем исходники и создаём запуск…")}
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
              {translateText("Запустить проверку")}
            </Button>
          </form>
        </Modal>
      )}
      {profileForm && (
        <ProjectForm
          initialSource={{ mode, file: archive, repository }}
          close={() => setProfileForm(false)}
        />
      )}
      <div className="home-summary" aria-label={translateText("Сводка")}>
        <Link to="/projects">
          {data.projects} {translateText("· сессии")}
        </Link>
        <Link to="/runs">
          {data.runs} {translateText("· запуски")}
        </Link>
      </div>
      <section className="panel">
        <div className="sectionHead session-history-head">
          <h2>{translateText("Последние запуски")}</h2>
          <div className="toolbar">
            {data.runs > 0 && <DeleteSessionButton />}
            <Link to="/runs">
              {translateText("Вся история")} <ChevronRight size={14} />
            </Link>
          </div>
        </div>
        <RunsTable rows={data.recent} compact />
      </section>
    </>
  );
}
function ProjectForm({
  project,
  initialSource,
  onSave,
  close,
}: {
  project?: Project;
  initialSource?: { mode: string; file?: File; repository: string };
  onSave?: (session: Project) => void;
  close: () => void;
}) {
  const [source, type] = useState(
    initialSource?.mode === "link" ? "GitHub" : "archive",
  );
  const [file, setFile] = useState(initialSource?.file);
  const fileError = archiveError(file);
  const [progress, setProgress] = useState(0);
  const { act, busy } = useAction();
  const nav = useNavigate();
  const show = useNotice((s) => s.show);
  return (
    <Modal
      title={
        project
          ? translateText("Изменить проект")
          : translateText("Новая сессия")
      }
      close={close}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const values = new FormData(e.currentTarget);
          if (!project && source === "archive" && file)
            values.set("archive", file);
          if (initialSource && source === "GitHub")
            values.set("public_repository", "true");
          void act(async () => {
            const res = project
              ? await api<Project>("/projects/" + project.id, "PATCH", {
                  name: values.get("name"),
                  description: values.get("description"),
                })
              : await uploadProject(values, setProgress);
            show(translateText("Сессия сохранена"));
            if (onSave) {
              onSave(res);
              return;
            }
            close();
            nav(
              initialSource
                ? "/workflows?project=" + res.id + "&new=1&start=personal"
                : "/projects/" + res.id,
            );
          });
        }}
      >
        <label>
          {translateText("Название")}
          <input
            name="name"
            autoFocus
            required
            maxLength={100}
            defaultValue={project?.name}
            placeholder={translateText("Например, Repair Desk")}
          />
        </label>
        <label>
          {translateText("Описание")}
          <textarea
            name="description"
            maxLength={2000}
            defaultValue={project?.description}
            placeholder={translateText("Что проверяем в этом проекте")}
          />
        </label>
        {!project && (
          <>
            <div className="seg">
              {["archive", "GitHub"].map((s) => (
                <button
                  type="button"
                  key={s}
                  className={s === source ? "on" : ""}
                  onClick={() => type(s)}
                >
                  {s === "archive" ? translateText("Загрузить архив") : s}
                </button>
              ))}
            </div>
            {source === "archive" ? (
              <label className="upload">
                <Upload />
                {file
                  ? file.name +
                    " · " +
                    Math.ceil(file.size / 1024) +
                    translateText(" КБ")
                  : translateText("Выберите архив с проектом")}
                <small>
                  {translateText("ZIP, RAR, 7Z, TAR, TAR.GZ, TGZ · до 24 МБ")}
                </small>
                <input
                  required={!file}
                  type="file"
                  name="archive"
                  accept={archiveAccept}
                  onChange={(e) => setFile(e.target.files?.[0])}
                />
              </label>
            ) : (
              <label>
                {translateText(
                  initialSource
                    ? "Ссылка на публичный GitHub-репозиторий"
                    : "Ссылка на учебный репозиторий",
                )}
                <input
                  required
                  type="url"
                  name="repository"
                  defaultValue={
                    initialSource?.repository ||
                    "https://github.com/TBagirov/training"
                  }
                />
              </label>
            )}
            {source === "archive" && fileError && (
              <p role="alert" className="errorline">
                {fileError}
              </p>
            )}
          </>
        )}
        {busy && !project && (
          <label>
            {progress < 100
              ? translateText("Загрузка ") + progress + "%"
              : translateText("Проверяем исходники…")}
            <progress max={100} value={progress} />
          </label>
        )}
        <button
          className="primary"
          disabled={busy || (!project && source === "archive" && !!fileError)}
        >
          {busy
            ? translateText("Сохраняем…")
            : project
              ? translateText("Сохранить")
              : translateText("Создать сессию")}
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
        title={translateText("Сессии")}
        sub={translateText("Исходники и история проверок каждого проекта.")}
        action={
          <button className="primary" onClick={() => toggle(true)}>
            <Plus />
            {translateText("Новая сессия")}
          </button>
        }
      />
      <div className="filters">
        <label className="search">
          <Search />
          <input
            aria-label={translateText("Поиск проектов")}
            placeholder={translateText("Поиск проектов")}
            value={query}
            onChange={(e) => set(e.target.value)}
          />
        </label>
        <select
          aria-label={translateText("Тип источника")}
          value={kind}
          onChange={(e) => filter(e.target.value)}
        >
          <option value="">{translateText("Все источники")}</option>
          <option>ZIP</option>
          <option value="Архив">{translateText("Архив")}</option>
          <option>GitHub</option>
        </select>
      </div>
      <section className="panel session-list">
        {rows.length ? (
          <>
            <div className="session-list-labels" aria-hidden="true">
              <span>{translateText("Сессия")}</span>
              <span>{translateText("Последняя проверка")}</span>
              <span>{translateText("Критические и высокие")}</span>
            </div>
            {rows.map((p) => (
              <div className="session-list-item" key={p.id}>
                <Link
                  className="projectrow session-row"
                  to={"/projects/" + p.id}
                >
                  <b>{p.name}</b>
                  <small>
                    {p.latest_completed?.finished
                      ? date(p.latest_completed.finished)
                      : translateText("Нет завершённых проверок")}
                  </small>
                  <span
                    className="session-list-risk"
                    aria-label={translateText("Критические и высокие")}
                  >
                    {p.latest_completed
                      ? (p.latest_completed.levels.CRITICAL || 0) +
                        (p.latest_completed.levels.HIGH || 0)
                      : "—"}
                    <span className="session-risk-label">
                      {" "}
                      {translateText("· серьёзные")}
                    </span>
                  </span>
                  <ChevronRight aria-hidden />
                </Link>
                <DeleteSessionButton id={p.id} iconOnly sessionName={p.name} />
              </div>
            ))}
          </>
        ) : (
          <Empty
            title={
              list.length
                ? translateText("Сессии не найдены")
                : translateText("Добавьте первую сессию")
            }
          >
            {translateText(
              "Загрузите архив или подключите учебный репозиторий GitHub.",
            )}
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
  const [params, setParams] = useSearchParams();
  const completed = runs.filter((r) =>
    ["success", "failed", "cancelled"].includes(r.status),
  );
  const runId =
    params.get("run_id") || p.latest_completed?.id || completed[0]?.id;
  const [edit, setEdit] = useState(false);
  const nav = useNavigate();
  return (
    <>
      <Heading
        title={p.name}
        sub={p.description || "Проект статического анализа"}
        action={
          <div className="toolbar">
            <button onClick={() => setEdit(true)}>
              <Settings2 />
              {translateText("Изменить")}
            </button>
            <DeleteSessionButton
              id={p.id}
              onDelete={() => nav("/projects", { replace: true })}
            />
          </div>
        }
      />
      <section
        className="session-results"
        aria-label={translateText("Результаты сессии")}
      >
        <div className="session-results-head">
          <h2>{translateText("Результаты проверки")}</h2>
          {runId && (
            <div className="session-run-controls">
              <label>
                <span>{translateText("Запуск")}</span>
                <select
                  aria-label={translateText("Запуск")}
                  value={runId}
                  onChange={(e) => setParams({ run_id: e.target.value })}
                >
                  {!completed.some((r) => r.id === runId) && (
                    <option value={runId}>
                      {translateText("Выбранный запуск")}
                    </option>
                  )}
                  {completed.map((r) => (
                    <option key={r.id} value={r.id}>
                      {date(r.finished || r.created)} ·{" "}
                      {translateText(r.workflow_name)}
                    </option>
                  ))}
                </select>
              </label>
              <Link className="button" to={"/runs/" + runId}>
                {translateText("Граф и журнал")}
              </Link>
            </div>
          )}
        </div>
        {runId ? (
          <Suspense
            fallback={
              <p role="status">{translateText("Загружаем результаты…")}</p>
            }
          >
            <SessionResults key={runId} sessionId={p.id} runId={runId} />
          </Suspense>
        ) : (
          <section className="panel">
            <Empty title={translateText("Нет завершённых проверок")}>
              {translateText(
                "Если проверка уже запущена, её ход виден в истории.",
              )}
              <div>
                <Link to={"/workflows?project=" + id + "&new=1"}>
                  {translateText("Создать сценарий")}
                </Link>
              </div>
            </Empty>
          </section>
        )}
      </section>
      <details className="panel session-details">
        <summary>{translateText("История запусков")}</summary>
        <RunsTable rows={runs} />
      </details>
      <details className="panel session-details">
        <summary>{translateText("Источник и сценарии")}</summary>
        <section className="detailgrid">
          <div>
            <small>{translateText("Источник")}</small>
            <b>{translateText(p.source_type)}</b>
            <code>{p.source}</code>
          </div>
          <div>
            <small>{translateText("Файлы для проверки")}</small>
            <b>{p.file_count}</b>
          </div>
          <div>
            <small>{translateText("Последний запуск")}</small>
            <b>{date(p.last_run)}</b>
          </div>
        </section>
        <div className="toolbar">
          <Link
            className="button primary"
            to={"/workflows?project=" + id + "&new=1"}
          >
            <Plus />
            {translateText("Создать сценарий")}
          </Link>
          <Link className="button" to={"/workflows?project=" + id}>
            {translateText("Сценарии сессии")}
          </Link>
        </div>
      </details>
      {edit && <ProjectForm project={p} close={() => setEdit(false)} />}
    </>
  );
}
type InitialWorkflow = "base" | "personal" | "prompt";

function NewFlow({
  projects,
  project,
  initial,
  close,
}: {
  projects: Project[];
  project: string;
  initial: InitialWorkflow;
  close: () => void;
}) {
  const registry = useData<Registry>("/registry");
  const [start, setStart] = useState<string>(initial);
  const normalName = translateText("Проверка исходного кода");
  const personalName = translateText("Личный сценарий");
  const [name, setName] = useState(
    initial === "personal" ? personalName : normalName,
  );
  const { act, busy } = useAction();
  const show = useNotice((state) => state.show);
  const nav = useNavigate();
  const [addingSession, setAddingSession] = useState(false);
  const [createdSession, setCreatedSession] = useState<Project>();
  const sessions =
    createdSession && !projects.some((item) => item.id === createdSession.id)
      ? [createdSession, ...projects]
      : projects;

  if (addingSession) {
    return (
      <ProjectForm
        close={() => setAddingSession(false)}
        onSave={(session) => {
          setCreatedSession(session);
          setAddingSession(false);
        }}
      />
    );
  }

  if (!sessions.length) {
    return (
      <Modal title={translateText("Новый сценарий")} close={close}>
        <Empty title={translateText("У вас пока нет сессий")}>
          <button className="primary" onClick={() => setAddingSession(true)}>
            <Plus size={16} />
            {translateText("Создать сессию")}
          </button>
        </Empty>
      </Modal>
    );
  }

  const selectedSession =
    createdSession?.id ??
    sessions.find((item) => item.id === project)?.id ??
    sessions[0].id;
  return (
    <Modal title={translateText("Новый сценарий")} close={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const v = new FormData(e.currentTarget);
          void act(async () => {
            let graph: Graph = registry.default_graph;
            let warnings: string[] = [];
            if (v.get("start") === "blank")
              graph = { nodes: [graph.nodes[0]], edges: [] };
            if (start === "personal") graph = { nodes: [], edges: [] };
            if (v.get("start") === "ai" && registry.ai_graph)
              graph = registry.ai_graph;
            if (start === "prompt") {
              const draft = await api<Graph & { warnings?: string[] }>(
                "/workflow-drafts",
                "POST",
                {
                  description: v.get("prompt"),
                },
              );
              graph = { nodes: draft.nodes, edges: draft.edges };
              warnings = draft.warnings ?? [];
            }
            const f = await api<Flow>("/workflows", "POST", {
              name: v.get("name"),
              description: v.get("description"),
              project_id: v.get("project"),
              graph,
            });
            close();
            nav("/workflows/" + f.id);
            if (warnings.length) show(warnings.map(translateText).join(" "));
          });
        }}
      >
        <label>
          {translateText("Название")}
          <input
            name="name"
            required
            maxLength={100}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          {translateText("Описание")}
          <textarea name="description" maxLength={2000} />
        </label>
        <label>
          {translateText("Сессия")}
          <select required name="project" defaultValue={selectedSession}>
            {sessions.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {translateText("Начальный граф")}
          <select
            name="start"
            value={start}
            onChange={(e) => {
              const next = e.target.value;
              setName((current) =>
                current === (start === "personal" ? personalName : normalName)
                  ? next === "personal"
                    ? personalName
                    : normalName
                  : current,
              );
              setStart(next);
            }}
          >
            <option value="base">
              {translateText("Три анализатора и отчёт")}
            </option>
            {registry.ai_graph && (
              <option value="ai">
                {translateText("Три анализатора, AI и отчёт")}
              </option>
            )}
            <option value="blank">{translateText("Только триггер")}</option>
            <option value="personal">
              {translateText("Личный сценарий (пустой граф)")}
            </option>
            <option value="prompt">{translateText("По описанию с AI")}</option>
          </select>
        </label>
        {start === "prompt" && (
          <label>
            {translateText("Что проверить")}
            <textarea
              name="prompt"
              required
              minLength={3}
              maxLength={2000}
              placeholder={translateText(
                "По будням в 9 утра проверяй зависимости и присылай критические результаты в Telegram",
              )}
            />
            <small>
              {translateText(
                "AI соберёт черновик сценария из текста. Проверьте блоки и стрелки в редакторе. Расписание включается вручную.",
              )}
            </small>
          </label>
        )}
        <button className="primary" disabled={busy}>
          {busy && start === "prompt"
            ? translateText("Подготавливаем схему…")
            : translateText(
                start === "prompt"
                  ? "Сгенерировать сценарий"
                  : "Открыть редактор",
              )}
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
  const [initial, setInitial] = useState<InitialWorkflow | null>(() => {
    if (!params.has("new")) return null;
    const start = params.get("start");
    return start === "personal" || start === "prompt" ? start : "base";
  });
  const { act, busy } = useAction();
  const nav = useNavigate();
  const rows = flows.filter((f) => !project || f.project_id === project);
  return (
    <>
      <Heading
        title={translateText("Сценарии")}
        sub={translateText("Графы анализа и правила передачи результатов.")}
        action={
          <div className="toolbar">
            <button onClick={() => setInitial("prompt")}>
              <Sparkles />
              {translateText("Собрать с AI")}
            </button>
            <button className="primary" onClick={() => setInitial("base")}>
              <Plus />
              {translateText("Новый сценарий")}
            </button>
          </div>
        }
      />
      <div className="filters">
        <select
          aria-label={translateText("Фильтр сессий")}
          value={project}
          onChange={(e) => setProject(e.target.value)}
        >
          <option value="">{translateText("Все сессии")}</option>
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
                  {f.graph.nodes.length} {translateText("узлов · v")}
                  {f.revision}
                </small>
                <small>
                  {translateText("Изменён")} {date(f.updated)}{" "}
                  {translateText("· запуск")} {date(f.last_run)}
                </small>
              </div>
              <Status value={f.last_status} />
              <button
                className="icon"
                title={translateText("Скопировать")}
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    const copy = await api<Flow>("/workflows", "POST", {
                      ...f,
                      name: f.name.slice(0, 90) + translateText(" (копия)"),
                    });
                    nav("/workflows/" + copy.id);
                  })
                }
              >
                <Copy />
              </button>
              <button
                className="icon"
                title={translateText("Удалить сценарий")}
                disabled={busy}
                onClick={() => {
                  if (confirm(translateText("Удалить сценарий?")))
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
                    nav("/runs/" + r.id, { state: { presentStages: true } });
                  })
                }
              >
                <Play />
                {translateText("Запуск")}
              </button>
            </article>
          ))
        ) : (
          <Empty title={translateText("Сценариев пока нет")}>
            {translateText(
              "Создайте граф из базовой проверки или начните с одного триггера.",
            )}
          </Empty>
        )}
      </section>
      <TemplateLibrary flows={flows} projects={projects} project={project} />
      {initial && (
        <NewFlow
          projects={projects}
          project={project}
          initial={initial}
          close={() => setInitial(null)}
        />
      )}
    </>
  );
}
function ThemeSettings() {
  const { language, setLanguage } = useLanguage();
  const { theme, setTheme } = useTheme();
  return (
    <section className="panel padded theme-settings">
      <h2>{translateText("Внешний вид")}</h2>
      <label>
        {translateText("Тема")}
        <select
          value={theme}
          onChange={(event) => setTheme(event.target.value as ThemePreference)}
        >
          <option value="light">{translateText("Светлая")}</option>
          <option value="dark">{translateText("Тёмная")}</option>
          <option value="system">{translateText("Как в системе")}</option>
        </select>
      </label>
      <label>
        {translateText("Язык")}
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value === "en" ? "en" : "ru")}
        >
          <option value="ru">Русский</option>
          <option value="en">English</option>
        </select>
      </label>
    </section>
  );
}

export function SettingsPage() {
  return (
    <>
      <Heading title={translateText("Настройки")} />
      <div className="settings-stack">
        <ThemeSettings />
      </div>
    </>
  );
}
