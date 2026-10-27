# Component Library

Pre-built icons for system design and software architecture diagrams, stored as standard
Excalidraw libraries in `references/libraries/`. Each `.excalidrawlib` file can also be opened
directly in Excalidraw (Library → Open) for manual use.

Insert components with `library_tool.py` — don't hand-copy their JSON. Icons are multi-element
drawings with fine-tuned line paths; the tool re-IDs, positions, scales and normalizes them.

```bash
cd .claude/skills/excalidraw-diagram/references
python library_tool.py list                                   # everything
python library_tool.py list --search database                 # filter by name
python library_tool.py add diagram.excalidraw "Load Balancer" --x 400 --y 200
python library_tool.py add diagram.excalidraw "Database" --x 600 --y 180 --label "orders (Postgres)"
python library_tool.py add diagram.excalidraw "Cloud Region" --x 300 --y 80   # boundaries go to the back automatically
python library_tool.py sheet catalog.excalidraw               # contact sheet → render it to browse visually
```

`add` prints a summary:

```json
{
  "component": "system-design/Load Balancer",
  "group_id": "load_balancer_group",
  "anchor_id": "load_balancer_0",
  "label_id": "load_balancer_6",
  "bbox": [400, 200, 72, 102],
  "icon_bbox": [400, 200, 72, 72],
  "z_order": "front"
}
```

- **`icon_bbox`** is the drawing without its caption. Aim arrows at its edges (midpoint of the side
  facing the other component) so they don't cross the caption.
- **`anchor_id`** is the icon's main closed shape. Bind arrows to it (`endBinding.elementId` + add the
  arrow to that element's `boundElements`). It is `null` when no single shape represents the icon
  (e.g. Users, Database) — then use an unbound arrow ending a few px outside `icon_bbox`.
- **`label_id`** is the caption text — edit its `text`/`originalText` later if needed.
- **`--label`** replaces the caption (or adds one to icons that ship without). **`--no-label`** drops it.
- **`--scale`** resizes uniformly; the caption font scales too.
- Names are case-insensitive. If two libraries share a name, prefix it: `"software-architecture/Database"`.

---

## Libraries

### `system-design` (clean style, roughness 0, palette colors)

Colors follow the **Component Category Colors** in `color-palette.md`.

| Category | Components | Use for |
|----------|-----------|---------|
| Networking / edge | Load Balancer, API Gateway, CDN, DNS, Internet, Reverse Proxy | Traffic entry, routing, edge caching, name resolution |
| Compute | Service, Worker, Serverless Function, Container, VM Instance, Scheduler, Kubernetes Pod | Things that run code: APIs, background jobs, functions, cron |
| Data / storage | SQL Database, NoSQL Database, Cache, Object Storage, Data Warehouse, Search Index, Vector Database, Sharded Database, Read Replica | Persistence, caching, analytics, retrieval |
| Messaging / events | Queue, Event Stream, Pub/Sub Topic, Event Bus, Notification, Webhook | Async communication, fan-out, event-driven flows |
| Security | Identity Provider, Firewall, WAF, Secrets Vault, Rate Limiter | Auth, network protection, throttling, secrets |
| Observability / ops | Monitoring, Logs, Alerting, CI/CD Pipeline, Feature Flags, Circuit Breaker | Telemetry, delivery, resilience patterns |
| AI / ML | LLM, AI Agent, Embedding Model | Model inference, agents, RAG pipelines |
| External | Third-party API, Payment Gateway | Systems you don't own (dashed = outside your control) |
| Boundaries | Cloud Region, Availability Zone, Kubernetes Cluster, Trust Boundary | Large containers (420×260) with a header label — resize the rectangle to fit contents |

### `architecture-diagram-components` (clean, cross-hatched icon tiles)

| Components | Use for |
|-----------|---------|
| User, Users, Device | Actors and clients |
| Server, Email | Generic hosts, email delivery |
| Slack, Docker, GitHub | Branded integrations / tooling |
| VPC, Public subnet, Private subnet | AWS-style network boundaries (270×165, header label) |

### `software-architecture` (hand-drawn style, roughness 1, no captions)

| Components | Use for |
|-----------|---------|
| Microservice | Hexagonal service (hexagonal architecture / microservices) |
| Database | Stacked-disk database cylinder |
| Layered Stack | Layers, replicated instances, a tier |
| Message Queue | Horizontal pipe / queue |
| Documents | Files, reports, document stores |
| Web App | Browser client |
| Mobile App | Mobile client |

These ship without captions — pass `--label` to add one. Their hand-drawn style suits informal
or brainstorming diagrams; for clean technical diagrams prefer the `system-design` equivalents
(Service, SQL Database, Queue, ...).

---

## Using Components Without Losing the Argument

Icons are vocabulary, not the diagram. The rules in `SKILL.md` still apply:

- **Use an icon when recognition matters** — a reader should know at a glance "that's a queue",
  "that's the cache". Don't use icons as decoration next to text that already says the same thing.
- **The layout still carries the meaning.** Fan-out from a Pub/Sub Topic, convergence into a Data
  Warehouse, a Trust Boundary separating zones — position and arrows argue; icons only name.
- **Keep one visual style per diagram.** Don't mix the hand-drawn `software-architecture` set with
  the clean sets unless the whole diagram is hand-drawn (`roughness: 1`).
- **Evidence artifacts still matter.** An "Event Stream" icon plus a dark code block showing the
  actual event payload beats the icon alone.
- **Arrows between icons**: leave ≥ 60px of clear space between icons so arrows and their labels fit.
- **Boundaries**: add them before or after their contents — `add` puts boundary-sized components at
  the back of the z-order either way. Resize the boundary's rectangle (`width`/`height`) to wrap the
  contents with ~40px padding; the header label stays top-left.
- **Exceptions to the opacity rule**: the `architecture-diagram-components` subnets use a
  low-opacity tinted fill by design. Leave it as-is.

## Adding Your Own Components

Build the component in Excalidraw, select it, and "Add to library"; then export the library
(Library → ⋯ → Export) and drop the `.excalidrawlib` file into `references/libraries/`. Give every
item a name — unnamed items show up as `item-N`. The tool picks up new files automatically.
