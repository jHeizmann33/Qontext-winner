# UI Storytelling Plan

## Goal

Build a **60-second demo-first interface** that makes Qontext feel like a live
company memory, not a dashboard.

The UI should optimize for:

- immediate visual intrigue
- crisp narrative progression
- believable explainability
- minimal operator friction during the demo

Primary visual engine:

- `react-force-graph-3d` for the hero graph scene

Primary narrative frame:

- retrieval-driven storytelling from the canonical Qontext graph

This is not a general-purpose enterprise console. It is a **showpiece** that
proves:

1. fragmented company data can be unified
2. retrieval can surface the right business context fast
3. every answer stays grounded in explicit relationships and provenance

---

## North Star

The audience should feel:

- "this looks premium"
- "this system understands the company"
- "this is more than search"

The UI has to communicate three things within seconds:

1. **Scale**: there is a living graph behind the scenes
2. **Precision**: this is not fuzzy chatbot magic
3. **Story**: the system can move from question -> answer -> evidence -> source

---

## Demo Structure

### Act 1: The graph wakes up (0-12s)

Visual goal:

- create a striking first impression
- establish the graph as alive, dimensional, and explorable

What is on screen:

- full-bleed 3D graph stage
- one oversized headline
- one compact query input or command chip
- ambient node motion, then gradual settle

Narration:

- "Qontext turns fragmented company data into a structured company memory."

Interaction:

- graph slowly rotates
- highlighted node clusters pulse by entity type
- camera drifts toward the area relevant to the demo query

### Act 2: Retrieval cuts through the graph (12-40s)

Visual goal:

- show that retrieval is intentional, ranked, and grounded

What is on screen:

- 3D graph remains visible as the stage
- left-side retrieval rail slides in with ranked hits
- active result expands
- graph focuses on the active node and its neighborhood

Narration:

- "We can ask a business question and immediately retrieve the most relevant entities and relationships."

Interaction:

- query executes
- 3 to 5 result cards appear in sequence
- active card syncs to graph focus
- edges animate along the selected path

### Act 3: Evidence and provenance land the point (40-60s)

Visual goal:

- make the answer trustworthy
- end on clarity, not motion overload

What is on screen:

- right-side detail drawer opens
- evidence bullets
- related entities
- provenance badges
- optional source/VFS excerpt

Narration:

- "The answer is not just generated. It is grounded in explicit company facts and traceable to source records."

Interaction:

- motion calms down
- one result is pinned
- the graph fades surrounding noise and spotlights the proof path

---

## Experience Architecture

### 1. Hero Graph Stage

Purpose:

- emotional hook
- live spatial context
- camera-driven storytelling

Behavior:

- full-screen or near full-screen canvas
- graph starts in wide shot
- auto-focus transitions to relevant subgraph
- force simulation runs at load, then cools and mostly freezes

Content rules:

- never render the whole company graph in the live demo
- use a curated subgraph of roughly `20-45` nodes
- keep links readable
- show layers of relevance, not raw volume

### 2. Retrieval Rail

Purpose:

- show ranked reasoning, not generic search

Position:

- left side on desktop
- bottom sheet on smaller screens

Card contents:

- title
- entity type
- short summary
- total score
- graph score vs vector score
- 2 to 4 evidence bullets
- provenance pill count

Animation:

- cards stagger in
- active card grows slightly
- inactive cards dim, not disappear

### 3. Evidence Drawer

Purpose:

- convert intrigue into trust

Position:

- right side

Sections:

- `Overview`
- `Why this matched`
- `Related entities`
- `Provenance`
- `Source excerpt`

### 4. Story Controls

Purpose:

- make the demo operator confident

Controls:

- next scene
- previous scene
- auto-play
- focus node
- reset camera
- show provenance

This should feel like a hidden presenter layer, not a visible admin panel.

---

## Visual Direction

### Tone

- cinematic
- sharp
- intelligent
- slightly futuristic, but still business-legible

### Look

Avoid:

- generic SaaS purple gradients
- plain black backgrounds with default neon
- crowded force-graph screenshots

Prefer:

- dark mineral background with subtle texture
- warm metallic highlights plus one cool accent
- crisp typography with real hierarchy
- fog, glow, and depth cues used sparingly

### Suggested palette

```css
:root {
  --bg-0: #07111a;
  --bg-1: #0d1b25;
  --bg-2: #152737;
  --panel: rgba(9, 19, 29, 0.74);
  --line: rgba(173, 205, 226, 0.18);
  --text-0: #f6f2e8;
  --text-1: #cbd6df;
  --text-2: #7f94a6;
  --accent-cyan: #57d3ff;
  --accent-lime: #bbff5c;
  --accent-coral: #ff8e72;
  --accent-gold: #ffd27a;
}
```

### Typography

Use expressive but practical type:

- headlines: `Space Grotesk`
- body: `IBM Plex Sans`
- data/provenance: `IBM Plex Mono`

### Background treatment

- radial gradient with faint noise
- soft volumetric glow behind the active graph cluster
- slow parallax particles or dust, but only if performance stays clean

---

## 3D Graph Design With `react-force-graph-3d`

### Why it fits

`react-force-graph-3d` is the right tool here because we want:

- a fast route to a cinematic 3D graph
- React integration
- camera control
- hover/click interactivity
- custom node rendering without building a 3D stack from scratch

### Node language

Encode types clearly:

- `Employee`: cool cyan sphere with a faint orbit ring
- `Customer`: lime rounded cube
- `Client`: gold hex node
- `Product`: coral capsule
- `EmailThread`: thin luminous disc
- `ITTicket`: red shard / diamond silhouette
- `Policy`: pale vertical plate

Visual cues:

- active node gets a halo
- related nodes get moderate glow
- non-relevant nodes drop to `15-25%` opacity

### Edge language

- default edges: thin, translucent, cool gray-blue
- highlighted path: brighter, slightly thicker, animated particles
- provenance-critical links: dotted or pulsing

### Camera choreography

For the demo, the camera should be scripted.

Sequence:

1. wide reveal
2. drift toward active cluster
3. orbit 15-20 degrees around selected node
4. settle into readable side angle

Do not allow the graph to tumble endlessly during explanation.

### Label strategy

Never show all labels at once.

Show labels only for:

- hovered node
- active node
- first-degree highlighted nodes

Use:

- short labels in-scene
- fuller text in DOM overlays

---

## Retrieval View Design

### Retrieval should look like curation, not raw search

The ideal visual hierarchy:

1. one active result
2. surrounding alternatives
3. visible explanation for why the active result won

### Result card anatomy

- rank number
- title
- entity type badge
- one-sentence summary
- total score bar
- graph/vector split bar
- evidence bullets
- action chips

Example card structure:

```text
#1  Raj Patel
Employee
Engineering lead connected to 2 client relationships and 4 recent ticket threads

Score 0.91
Graph 0.82 | Vector 0.77

- property `department` matched query terms
- outgoing `represents_client` to Acme Ltd
- outgoing `assigned_ticket` to Laptop login failure
```

### Detail drawer anatomy

- title + type + score
- primary explanation sentence
- related entities list
- provenance chips
- source excerpt or VFS snippet

### Recommended transitions

- query submit: graph pulse + cards slide in
- card hover: graph previews node
- card select: camera flies to node, evidence drawer opens
- provenance toggle: links recolor to emphasize source chain

---

## Best Demo Query Patterns

The UI will look best when the query produces a compact, narratable subgraph.

Best query styles:

- "Which engineering employee is closest to this client relationship?"
- "Show me the support and account context for this customer"
- "Who is connected to this issue across tickets, emails, and clients?"
- "What company context do we have around this customer?"

Avoid in the demo:

- huge undirected multi-hop queries
- broad "tell me everything" prompts
- queries that explode to dozens of equally plausible results

---

## Demo-Optimized Data Strategy

For the 1-minute demo, prepare a **curated retrieval payload** rather than
hitting the entire graph cold and hoping the visuals behave.

Use:

- one featured query
- one backup query
- a preselected subgraph
- fixed camera anchor targets

Recommended live data bundle:

- top `3-5` retrieval results
- selected result neighborhood of `1-2` hops
- node positions persisted once the layout stabilizes
- provenance snippets pretrimmed for display

This keeps the demo dramatic and avoids layout chaos.

---

## React Component Plan

### Top-level components

```text
DemoShell
StoryStage
GraphScene3D
RetrievalRail
ResultCard
EvidenceDrawer
StoryControls
SceneCaption
```

### Component roles

#### `DemoShell`

- owns selected story scene
- owns active query
- loads retrieval payload
- coordinates timing and transitions

#### `StoryStage`

- full-screen layout wrapper
- places graph canvas, side rails, captions, overlays

#### `GraphScene3D`

- wraps `react-force-graph-3d`
- receives filtered nodes/edges
- handles camera scripts
- exposes `focusNode(nodeId)`

#### `RetrievalRail`

- renders ranked retrieval cards
- controls active result

#### `EvidenceDrawer`

- renders explanation, related nodes, provenance, source excerpt

#### `StoryControls`

- demo-only controls
- hidden by default, visible on presenter hover or keyboard shortcut

---

## State Model

Minimal demo state:

```ts
type StoryScene = "intro" | "retrieve" | "prove";

type UIState = {
  scene: StoryScene;
  query: string;
  results: RetrievalResult[];
  activeNodeId: string | null;
  hoveredNodeId: string | null;
  focusedNodeIds: string[];
  showProvenance: boolean;
  autoplay: boolean;
};
```

---

## Motion Rules

### Use motion to direct attention, not decorate everything

Good motion:

- staggered card reveal
- camera easing
- edge pulse on selected path
- panel blur/fade transitions

Bad motion:

- constantly moving graph
- bouncing UI
- endless rotations
- multiple simultaneous attention cues

Rule:

- every motion should answer "where should the viewer look now?"

---

## Sound Design

Optional, but if used:

- soft rise on intro
- subtle confirmation click on scene change
- no sci-fi beeps

Mute-safe design is required. The demo must still work perfectly without audio.

---

## Mobile / Laptop Safety

The primary target is desktop/laptop demo recording, but it should not break on
smaller screens.

Fallback layout:

- graph on top
- retrieval rail as bottom sheet
- evidence as slide-over panel

---

## Implementation Order

### Phase 1

- set up `StoryStage`
- build `GraphScene3D`
- render curated static subgraph
- implement node colors, glow, selection

### Phase 2

- hook to `/retrieve`
- build retrieval rail
- wire active card <-> graph focus

### Phase 3

- build evidence drawer
- add provenance view
- add intro/retrieve/prove scene choreography

### Phase 4

- refine typography, gradients, motion, camera timing
- freeze layout
- polish for recording

---

## Recommendation

For the 1-minute demo:

- make the **3D graph the hero**
- make **retrieval the narrative spine**
- make **provenance the closing proof**

The right vibe is:

- bold opening
- elegant focus
- undeniable evidence

If we execute that well, the UI will feel less like "here is a graph viewer" and
more like "the company memory just came alive."
