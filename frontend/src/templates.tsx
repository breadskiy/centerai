import { t as translateText } from "./locale";
import { lazy, Suspense, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Upload } from "lucide-react";
import { api, date, Flow, Graph, Project, useData } from "./api";
import { Empty, Modal, useAction, useNotice } from "./ui";

interface Published {
  workflow_id: string;
  revision: number;
  published_at: number;
  name: string;
  description: string;
  graph: Graph;
}
const Preview = lazy(() =>
  import("./editor").then((m) => ({ default: m.ReadonlyGraph })),
);

export function TemplateLibrary({
  flows,
  projects,
  project,
}: {
  flows: Flow[];
  projects: Project[];
  project: string;
}) {
  const templates = useData<Published[]>("/templates");
  const [publishing, publish] = useState(false);
  const [selected, open] = useState<Published | null>(null);
  const [source, setSource] = useState("");
  const { act, busy } = useAction();
  const show = useNotice((s) => s.show);
  const nav = useNavigate();
  return (
    <section className="panel">
      <div className="sectionHead">
        <h2>{translateText("Библиотека шаблонов")}</h2>
        <button
          disabled={!flows.length}
          onClick={() => {
            setSource(flows[0].id);
            publish(true);
          }}
        >
          <Upload />
          {translateText("Опубликовать версию")}
        </button>
      </div>
      {templates.length ? (
        templates.map((t) => (
          <article className="flowrow" key={t.workflow_id + t.revision}>
            <BookOpen />
            <div className="grow">
              <b>{t.name}</b>
              <small>
                v{t.revision} · {t.graph.nodes.length}{" "}
                {translateText("узлов ·")} {date(t.published_at)}
              </small>
            </div>
            <button onClick={() => open(t)}>
              {translateText("Посмотреть шаблон")}
            </button>
          </article>
        ))
      ) : (
        <Empty title={translateText("Опубликованных шаблонов пока нет")}>
          {translateText(
            "Сохраните версию сценария в библиотеку рабочего пространства, чтобы использовать её в другом проекте.",
          )}
        </Empty>
      )}
      {publishing && (
        <Modal
          title={translateText("Публикация версии")}
          close={() => publish(false)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const flow = flows.find((f) => f.id === source);
              if (flow)
                void act(async () => {
                  await api(
                    "/workflows/" +
                      flow.id +
                      "/versions/" +
                      flow.revision +
                      "/publish",
                    "POST",
                  );
                  publish(false);
                  show(translateText("Версия добавлена в библиотеку"));
                });
            }}
          >
            <label>
              {translateText("Сценарий")}
              <select
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                {flows.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name} · v{f.revision}
                  </option>
                ))}
              </select>
            </label>
            <p>
              {translateText(
                "В библиотеке сохранится текущая версия графа. Исходники проекта и настройки бота в шаблон не входят.",
              )}
            </p>
            <button className="primary" disabled={busy}>
              {translateText("Опубликовать")}
            </button>
          </form>
        </Modal>
      )}
      {selected && (
        <Modal title={selected.name} close={() => open(null)}>
          <p>
            {selected.description ||
              translateText("Версия ") + selected.revision}
          </p>
          <Suspense fallback={<p>{translateText("Загрузка графа…")}</p>}>
            <Preview graph={selected.graph} statuses={{}} />
          </Suspense>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const values = new FormData(e.currentTarget);
              void act(async () => {
                const f = await api<Flow>(
                  "/templates/" +
                    selected.workflow_id +
                    "/" +
                    selected.revision +
                    "/copies",
                  "POST",
                  Object.fromEntries(values),
                );
                open(null);
                nav("/workflows/" + f.id);
              });
            }}
          >
            <label>
              {translateText("Название копии")}
              <input
                name="name"
                required
                maxLength={100}
                defaultValue={selected.name}
              />
            </label>
            <label>
              {translateText("Проект для копии")}
              <select
                name="project_id"
                defaultValue={project || projects[0]?.id}
                required
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <button className="primary" disabled={busy || !projects.length}>
              {translateText("Создать из шаблона")}
            </button>
          </form>
        </Modal>
      )}
    </section>
  );
}
