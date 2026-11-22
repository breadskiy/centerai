import { t as translateText } from "./locale";
import { DragEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  BackgroundVariant,
  Connection,
  Controls,
  Edge,
  Handle,
  Node,
  NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Braces,
  CheckCheck,
  ChevronLeft,
  FileOutput,
  Filter,
  GitBranch,
  GripVertical,
  History,
  KeyRound,
  PanelLeft,
  Play,
  Plus,
  Save,
  Send,
  Settings2,
  Trash2,
  Workflow,
} from "lucide-react";
import {
  api,
  cache,
  date,
  Flow,
  Graph,
  Kind,
  levels,
  Registry,
  Run,
  useData,
} from "./api";
import { icons, Modal, Severity, Status, useAction, useNotice } from "./ui";

type Tile = Node<
  {
    spec: Kind;
    kind: string;
    config: Record<string, unknown>;
    status?: string;
    risk?: Record<string, number>;
  },
  "tile"
>;
const marks = {
  ...icons,
  secrets_scanner: KeyRound,
  sast_scanner: Braces,
  report_generator: FileOutput,
  notification: Send,
  if_else: GitBranch,
  severity_filter: Filter,
  regex_filter: Braces,
};
function TileView({ data, selected }: NodeProps<Tile>) {
  const I = marks[data.kind as keyof typeof marks] || Workflow;
  const spec = data.spec;
  return (
    <div
      className={"tile " + (selected ? "chosen " : "") + "cat" + spec.output}
    >
      {spec.input !== "—" && <Handle type="target" position={Position.Left} />}
      <div className="tileMeta" title={translateText(spec.description)}>
        <I size={15} />
        {translateText(spec.category)}
      </div>
      <b>{translateText(spec.title)}</b>
      {data.status === "success" && data.risk ? (
        <div className="risk-badges">
          {levels.some((level) => data.risk?.[level]) ? (
            levels.map((level) =>
              data.risk?.[level] ? (
                <span key={level}>
                  <Severity value={level} /> {data.risk[level]}
                </span>
              ) : null,
            )
          ) : (
            <small>{translateText("Нет находок")}</small>
          )}
        </div>
      ) : (
        data.status &&
        data.status !== "success" && <Status value={data.status} />
      )}
      {data.kind === "if_else"
        ? ["true", "false"].map((v, i) => (
            <div key={v} className={"branch branch" + i}>
              {i ? translateText("Нет") : translateText("Да")}
              <Handle id={v} type="source" position={Position.Right} />
            </div>
          ))
        : spec.output !== "receipt" && (
            <Handle type="source" position={Position.Right} />
          )}
    </div>
  );
}
const nodeTypes = { tile: TileView };
function translate(
  graph: Graph,
  registry: Registry,
  statuses: Record<string, string> = {},
  risks: Record<string, Record<string, number>> = {},
): { nodes: Tile[]; edges: Edge[] } {
  return {
    nodes: graph.nodes.map((n) => ({
      id: n.id,
      type: "tile",
      position: n.position,
      data: {
        kind: n.type,
        spec: registry.types[n.type] ?? {
          title: n.type,
          category: translateText("Неизвестный узел"),
          description: translateText("Замените неподдерживаемый тип узла."),
          input: "?",
          output: "?",
          defaults: {},
        },
        config: { ...registry.types[n.type]?.defaults, ...n.config },
        status: statuses[n.id],
        risk: risks[n.id],
      },
    })),
    edges: graph.edges.map((e, i) => ({
      id: "e" + i,
      source: e.source,
      target: e.target,
      sourceHandle: e.branch || null,
      label:
        e.branch === "true"
          ? translateText("Да")
          : e.branch === "false"
            ? translateText("Нет")
            : undefined,
      type: "smoothstep",
    })),
  };
}
export function ReadonlyGraph({
  graph,
  statuses,
  risks,
}: {
  graph: Graph;
  statuses: Record<string, string>;
  risks?: Record<string, Record<string, number>>;
}) {
  const registry = useData<Registry>("/registry");
  const data = translate(graph, registry, statuses, risks);
  return (
    <div className="readgraph">
      <ReactFlow
        nodes={data.nodes}
        edges={data.edges}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.2}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background gap={18} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
function Connections({
  picked,
  nodes,
  edges,
  setEdges,
}: {
  picked: Tile;
  nodes: Tile[];
  edges: Edge[];
  setEdges: (update: (es: Edge[]) => Edge[]) => void;
}) {
  const [parent, setParent] = useState("");
  const [branch, setBranch] = useState("true");
  const candidates = nodes.filter(
    (n) =>
      n.id !== picked.id &&
      (n.data.spec.output === picked.data.spec.input ||
        (n.data.kind.endsWith("_scanner") &&
          picked.data.kind.endsWith("_scanner"))),
  );
  const incoming = edges.filter((e) => e.target === picked.id);
  const choice = nodes.find((n) => n.id === parent);
  if (picked.data.spec.input === "—") return null;
  return (
    <details>
      <summary>{translateText("Входящие связи")}</summary>
      {incoming.map((e) => (
        <div className="linkline" key={e.id}>
          <small>
            {translateText(
              nodes.find((n) => n.id === e.source)?.data.spec.title || "",
            )}{" "}
            {e.label}
          </small>
          <button
            aria-label={translateText("Удалить связь")}
            onClick={() => setEdges((es) => es.filter((v) => v.id !== e.id))}
          >
            <Trash2 />
          </button>
        </div>
      ))}
      <label>
        {translateText("Вход из узла")}
        <select value={parent} onChange={(e) => setParent(e.target.value)}>
          <option value="">{translateText("Выберите узел")}</option>
          {candidates.map((n) => (
            <option key={n.id} value={n.id}>
              {translateText(n.data.spec.title)} · {n.id.slice(-6)}
            </option>
          ))}
        </select>
      </label>
      {choice?.data.kind === "if_else" && (
        <label>
          {translateText("Ветвь")}
          <select value={branch} onChange={(e) => setBranch(e.target.value)}>
            <option value="true">{translateText("Да")}</option>
            <option value="false">{translateText("Нет")}</option>
          </select>
        </label>
      )}
      <button
        disabled={!choice}
        onClick={() => {
          const h = choice?.data.kind === "if_else" ? branch : null;
          setEdges((es) =>
            addEdge(
              {
                id: crypto.randomUUID(),
                source: parent,
                target: picked.id,
                sourceHandle: h,
                label:
                  h === "true"
                    ? translateText("Да")
                    : h === "false"
                      ? translateText("Нет")
                      : undefined,
                type: "smoothstep",
              },
              es,
            ),
          );
          setParent("");
        }}
      >
        {translateText("Соединить")}
      </button>
    </details>
  );
}
function Config({
  node,
  update,
}: {
  node: Tile;
  update: (config: Record<string, unknown>) => void;
}) {
  const c = node.data.config;
  const set = (key: string, value: unknown) => update({ ...c, [key]: value });
  return (
    <>
      {node.data.kind === "if_else" && (
        <>
          <label>
            {translateText("Сравнить число находок")}
            <select
              value={String(c.operator)}
              onChange={(e) => set("operator", e.target.value)}
            >
              {[">", ">=", "==", "<", "<="].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            {translateText("Порог")}
            <input
              type="number"
              min="0"
              value={Number(c.count)}
              onChange={(e) => set("count", Number(e.target.value))}
            />
          </label>
        </>
      )}
      {node.data.kind === "severity_filter" && (
        <fieldset>
          <legend>{translateText("Включить уровни")}</legend>
          {levels.map((l) => (
            <label className="check" key={l}>
              <input
                type="checkbox"
                checked={(c.levels as string[]).includes(l)}
                onChange={(e) =>
                  set(
                    "levels",
                    e.target.checked
                      ? [...(c.levels as string[]), l]
                      : (c.levels as string[]).filter((v) => v !== l),
                  )
                }
              />
              {l}
            </label>
          ))}
        </fieldset>
      )}
      {node.data.kind === "ai_analysis" && (
        <label>
          {translateText("Модель")}
          <input
            value={String(c.model || "")}
            maxLength={160}
            placeholder={translateText("По умолчанию на сервере")}
            onChange={(e) => set("model", e.target.value)}
          />
        </label>
      )}
      {node.data.kind === "regex_filter" && (
        <label>
          {translateText("Выражение для пути")}
          <input
            value={String(c.pattern)}
            maxLength={200}
            onChange={(e) => set("pattern", e.target.value)}
          />
        </label>
      )}
      {node.data.kind === "schedule_trigger" && (
        <>
          <label>
            Cron
            <input
              value={String(c.cron)}
              onChange={(e) => set("cron", e.target.value)}
            />
          </label>
          <label>
            {translateText("Часовой пояс")}
            <input
              value={String(c.timezone)}
              onChange={(e) => set("timezone", e.target.value)}
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={Boolean(c.enabled)}
              onChange={(e) => set("enabled", e.target.checked)}
            />
            {translateText("Включить расписание")}
          </label>
        </>
      )}
    </>
  );
}
function Versions({
  flow,
  restore,
  close,
}: {
  flow: string;
  restore: (v: Flow) => void;
  close: () => void;
}) {
  const versions = useData<(Flow & { created: number })[]>(
    "/workflows/" + flow + "/versions",
  );
  return (
    <Modal title={translateText("Версии сценария")} close={close}>
      {versions.map((v) => (
        <div className="version" key={v.revision}>
          <div>
            <b>
              v{v.revision} · {v.name}
            </b>
            <small>
              {date(v.created)} · {v.graph.nodes.length}{" "}
              {translateText("узлов")}
            </small>
          </div>
          <button
            onClick={() => {
              restore(v);
              close();
            }}
          >
            {translateText("Загрузить")}
          </button>
        </div>
      ))}
    </Modal>
  );
}
type EditableFlow = Pick<Flow, "id" | "name" | "description" | "revision" | "graph"> & {
  repository?: string;
};

function Editor({ flow, registry, repositoryPage }: {
  flow: EditableFlow;
  registry: Registry;
  repositoryPage?: string;
}) {
  const repositoryMode = repositoryPage !== undefined;
  const resource = repositoryMode
    ? "/github-repositories/" + flow.id + "/scenario"
    : "/workflows/" + flow.id;
  const query = repositoryMode ? "?page=" + encodeURIComponent(repositoryPage) : "";
  const initial = useRef(translate(flow.graph, registry));
  const [nodes, setNodes] = useState<Tile[]>(initial.current.nodes);
  const [edges, setEdges] = useState<Edge[]>(initial.current.edges);
  const [name, setName] = useState(flow.name);
  const [description, describe] = useState(flow.description || "");
  const [options, settings] = useState(false);
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const [selected, select] = useState<string | null>(null);
  const [palette, setPalette] = useState(true);
  const [versions, history] = useState(false);
  const [message, note] = useState(translateText("Сохранено"));
  const [error, setError] = useState("");
  const revision = useRef(flow.revision);
  const nav = useNavigate();
  const screen = useReactFlow();
  const canvas = useRef<HTMLDivElement>(null);
  const show = useNotice((s) => s.show);
  const { busy, act } = useAction();
  const graph: Graph = {
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.kind,
      position: n.position,
      config: n.data.config,
    })),
    edges: edges.map((e) => ({
      source: e.source,
      target: e.target,
      branch: e.sourceHandle || "",
    })),
  };
  const serialized = JSON.stringify({ name, description, graph });
  const topology = JSON.stringify({
    nodes: graph.nodes.map(({ id, type, config }) => ({ id, type, config })),
    edges: graph.edges,
  });
  const [validation, checked] = useState({ graph: "", error: "" });
  useEffect(() => {
    let current = true;
    const timer = setTimeout(() => {
      api(
        resource + "/validate",
        "POST",
        JSON.parse(topology),
      ).then(
        () => {
          if (current) checked({ graph: topology, error: "" });
        },
        (e) => {
          if (current) checked({ graph: topology, error: e.message });
        },
      );
    }, 220);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [resource, topology]);
  const graphError = validation.graph === topology ? validation.error : "";
  const saved = useRef(serialized);
  const latest = useRef(serialized);
  latest.current = serialized;
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  function save() {
    const job = chain.current
      .catch(() => {})
      .then(async () => {
        const value = latest.current;
        if (saved.current === value) return;
        note(translateText("Сохранение…"));
        try {
          const updated = await api<EditableFlow>(resource + query, "PUT", {
            ...JSON.parse(value),
            revision: revision.current,
          });
          revision.current = updated.revision;
          saved.current = value;
          if (repositoryMode) {
            cache.setQueryData([resource + query], updated);
            void cache.invalidateQueries({ queryKey: ["/github-repositories/watches"] });
          }
          note(translateText("Сохранено"));
          setError("");
        } catch (e) {
          note(translateText("Ошибка сохранения"));
          setError((e as Error).message);
          throw e;
        }
      });
    chain.current = job;
    return job;
  }
  useEffect(() => {
    if (serialized === saved.current) return;
    note(translateText("Есть изменения"));
    if (repositoryMode) return;
    const t = setTimeout(() => {
      void save().catch(() => {});
    }, 800);
    return () => clearTimeout(t);
  }, [serialized, repositoryMode]);
  useEffect(
    () => () => {
      if (!repositoryMode && latest.current !== saved.current)
        void save().catch((e) => show(e.message, true));
    },
    [],
  );
  const picked = nodes.find((n) => n.id === selected);
  function add(kind: string, point?: { x: number; y: number }) {
    const spec = registry.types[kind];
    const bounds = canvas.current?.getBoundingClientRect();
    const pos =
      point ||
      screen.screenToFlowPosition({
        x: (bounds?.left || 0) + (bounds?.width || 600) / 2,
        y: (bounds?.top || 0) + (bounds?.height || 500) / 2,
      });
    const id = kind + "-" + crypto.randomUUID().slice(0, 6);
    setNodes((ns) => [
      ...ns,
      {
        id,
        type: "tile",
        position: pos,
        data: { spec, kind, config: structuredClone(spec.defaults) },
      },
    ]);
    select(id);
  }
  function dropped(e: DragEvent) {
    e.preventDefault();
    const type = e.dataTransfer.getData("centerai/node");
    if (type !== "email_notification" && registry.types[type])
      add(type, screen.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  }
  function connect(c: Connection) {
    setEdges((es) =>
      addEdge(
        {
          ...c,
          type: "smoothstep",
          label:
            c.sourceHandle === "true"
              ? translateText("Да")
              : c.sourceHandle === "false"
                ? translateText("Нет")
                : undefined,
        },
        es,
      ),
    );
  }
  async function validate() {
    if (!repositoryMode) await save();
    try {
      await api(resource + "/validate", "POST", repositoryMode ? graph : undefined);
      setError("");
    } catch (e) {
      setError((e as Error).message);
      throw e;
    }
  }
  return (
    <section className="editor">
      <Link className="back" to={repositoryMode ? "/repositories" : "/workflows"}>
        <ChevronLeft size={15} />
        {translateText(repositoryMode ? "Мои репозитории" : "Сценарии")}
      </Link>
      {repositoryMode && (
        <p>
          {flow.repository && <><strong>{flow.repository}</strong>{" · "}</>}
          {translateText("Сохранённый граф будет выполняться при автопроверке этого репозитория после коммита.")}
        </p>
      )}
      <div className="editorbar">
        <div>
          <input
            className="nameInput"
            aria-label={translateText("Название сценария")}
            value={name}
            maxLength={100}
            onChange={(e) => setName(e.target.value)}
          />
          <small>
            {message} · v{revision.current}
          </small>
        </div>
        <div className="toolbar">
          <button
            title={translateText("Настройки сценария")}
            onClick={() => settings(true)}
          >
            <Settings2 />
          </button>
          {!repositoryMode && <button
            aria-label={translateText("Версии")}
            title={translateText("Версии")}
            onClick={() => history(true)}
          >
            <History />
          </button>}
          <button
            className={repositoryMode ? "primary" : undefined}
            title={translateText("Сохранить")}
            disabled={busy || (repositoryMode && (!name.trim() || validation.graph !== topology || !!graphError))}
            onClick={() =>
              void act(async () => {
                await save();
                show(translateText("Граф сохранён"));
              })
            }
          >
            <Save />
            {repositoryMode && translateText("Сохранить")}
          </button>
          <button
            disabled={busy}
            onClick={() =>
              void act(async () => {
                await validate();
                show(translateText("Граф прошёл проверку"));
              })
            }
          >
            <CheckCheck />
            {translateText("Проверить")}
          </button>
          {!repositoryMode && <button
            className="primary"
            disabled={
              busy ||
              !name.trim() ||
              validation.graph !== topology ||
              !!graphError
            }
            onClick={() =>
              void act(async () => {
                await validate();
                const r = await api<Run>(
                  "/workflows/" + flow.id + "/runs",
                  "POST",
                );
                nav("/runs/" + r.id);
              })
            }
          >
            <Play />
            {translateText("Запустить")}
          </button>}
        </div>
      </div>
      {(error || graphError) && (
        <p role="alert" className="errorline">
          {error || graphError}
        </p>
      )}
      <details className="panel padded">
        <summary>{translateText("Как собрать проверку")}</summary>
        <ol>
          <li>
            {translateText(
              repositoryMode
                ? "При автопроверке граф запускается после коммита в отслеживаемой ветке GitHub."
                : "Ручной запуск и Исходники задают, когда начать и какой проект проверить.",
            )}
          </li>
          <li>
            {translateText(
              "Добавьте анализатор. Стрелка передаёт результат следующему блоку. Фильтр помогает выбрать нужные находки.",
            )}
          </li>
          <li>
            {translateText(
              "Подключите находки к Отчёту. Чтобы получить объяснения, вставьте AI-анализ между анализатором и Отчётом.",
            )}
          </li>
          <li>
            {translateText(
              repositoryMode
                ? "Нажмите «Проверить», затем «Сохранить». Для уведомления подключите Telegram после Отчёта."
                : "Нажмите «Проверить», затем «Запустить». Для уведомления подключите Telegram после Отчёта.",
            )}
          </li>
        </ol>
      </details>
      <div className="editorframe">
        <div className="canvasbar">
          <button onClick={() => setPalette(!palette)} aria-expanded={palette}>
            <PanelLeft />
            {translateText("Узлы")}
          </button>
          <span>
            {nodes.length} {translateText("узлов ·")} {edges.length}{" "}
            {translateText("связей")}
          </span>
          <button onClick={() => screen.fitView({ padding: 0.12 })}>
            {translateText("Весь граф")}
          </button>
        </div>
        <div className="graphlayout">
          {palette && (
            <aside className="palette">
              <input
                className="nodeSearch"
                aria-label={translateText("Поиск узлов")}
                placeholder={translateText("Найти узел")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {Array.from(
                new Set(Object.values(registry.types).map((t) => t.category)),
              ).map((group) => (
                <div key={group}>
                  <h3>
                    <button
                      className="categoryBtn"
                      aria-expanded={!collapsed.includes(group)}
                      onClick={() =>
                        setCollapsed((v) =>
                          v.includes(group)
                            ? v.filter((g) => g !== group)
                            : [...v, group],
                        )
                      }
                    >
                      {translateText(group)}
                    </button>
                  </h3>
                  {!collapsed.includes(group) &&
                    Object.entries(registry.types)
                      .filter(
                        ([key, t]) =>
                          key !== "email_notification" &&
                          t.category === group &&
                          t.title.toLowerCase().includes(search.toLowerCase()),
                      )
                      .map(([key, spec]) => (
                        <button
                          key={key}
                          title={translateText(spec.description)}
                          draggable
                          onDragStart={(e) =>
                            e.dataTransfer.setData("centerai/node", key)
                          }
                          onClick={() => add(key)}
                        >
                          <GripVertical size={13} />
                          {translateText(spec.title)}
                          <Plus size={13} />
                        </button>
                      ))}
                </div>
              ))}
            </aside>
          )}
          <div
            className="canvas"
            ref={canvas}
            onDragOver={(e) => e.preventDefault()}
            onDrop={dropped}
          >
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.12 }}
              minZoom={0.15}
              onNodesChange={(changes) =>
                setNodes((ns) => applyNodeChanges(changes, ns))
              }
              onEdgesChange={(changes) =>
                setEdges((es) => applyEdgeChanges(changes, es))
              }
              onConnect={connect}
              onNodeClick={(_, n) => select(n.id)}
              onPaneClick={() => select(null)}
              deleteKeyCode={["Backspace", "Delete"]}
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={17}
                color="var(--graph-dot)"
              />
              <Controls />
            </ReactFlow>
          </div>
          {picked && (
            <aside className="inspector">
              <small>{translateText("Инспектор узла")}</small>
              <button
                className="closeInspector"
                aria-label={translateText("Свернуть инспектор")}
                onClick={() => select(null)}
              >
                ×
              </button>
              <h2>{translateText(picked.data.spec.title)}</h2>
              <p>{translateText(picked.data.spec.description)}</p>
              <code>{picked.data.kind}</code>
              {graphError.includes(picked.id) && (
                <p className="errorline">{graphError}</p>
              )}
              <dl>
                <dt>{translateText("Вход")}</dt>
                <dd>{picked.data.spec.input}</dd>
                <dt>{translateText("Выход")}</dt>
                <dd>{picked.data.spec.output}</dd>
              </dl>
              <Connections
                key={picked.id}
                picked={picked}
                nodes={nodes}
                edges={edges}
                setEdges={setEdges}
              />
              <Config
                node={picked}
                update={(config) =>
                  setNodes((ns) =>
                    ns.map((n) =>
                      n.id === picked.id
                        ? { ...n, data: { ...n.data, config } }
                        : n,
                    ),
                  )
                }
              />
              <button
                className="danger"
                onClick={() => {
                  setEdges((es) =>
                    es.filter(
                      (e) => e.source !== picked.id && e.target !== picked.id,
                    ),
                  );
                  setNodes((ns) => ns.filter((n) => n.id !== picked.id));
                  select(null);
                }}
              >
                <Trash2 />
                {translateText("Удалить узел")}
              </button>
            </aside>
          )}
        </div>
      </div>
      {options && (
        <Modal
          title={translateText("Настройки сценария")}
          close={() => settings(false)}
        >
          <label>
            {translateText("Описание")}
            <textarea
              value={description}
              maxLength={2000}
              onChange={(e) => describe(e.target.value)}
            />
          </label>
          <button onClick={() => settings(false)}>
            {translateText("Готово")}
          </button>
        </Modal>
      )}
      {versions && (
        <Versions
          flow={flow.id}
          close={() => history(false)}
          restore={(v) => {
            const data = translate(v.graph, registry);
            setNodes(data.nodes);
            setEdges(data.edges);
            setName(v.name);
            describe(v.description);
          }}
        />
      )}
    </section>
  );
}
export function EditorPage() {
  const { id } = useParams();
  const flow = useData<Flow>("/workflows/" + id);
  const registry = useData<Registry>("/registry");
  return (
    <ReactFlowProvider>
      <Editor key={id} flow={flow} registry={registry} />
    </ReactFlowProvider>
  );
}

export function RepositoryEditorPage() {
  const { id } = useParams();
  const [search] = useSearchParams();
  const page = search.get("page") ?? "1";
  const flow = useData<EditableFlow>("/github-repositories/" + id + "/scenario?page=" + encodeURIComponent(page));
  const registry = useData<Registry>("/registry");
  return (
    <ReactFlowProvider>
      <Editor key={id} flow={flow} registry={registry} repositoryPage={page} />
    </ReactFlowProvider>
  );
}
