import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import ForceGraph3D from "react-force-graph-3d";
import * as THREE from "three";
import SpriteText from "three-spritetext";
import { FALLBACK_PAYLOAD, STORY_PRESETS } from "../lib/storyQueries.js";
import "../graph-view.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const VIEW_MODES = [
  { id: "constellation", label: "Constellation" },
  { id: "relations", label: "Relations" },
  { id: "proof", label: "Proof" },
];

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function formatModeLabel(mode) {
  return (mode || "auto").replace(/_/g, " ");
}

function buildFallbackStatus() {
  return {
    local: {
      available: true,
      documents: FALLBACK_PAYLOAD.index.documents,
      unique_terms: FALLBACK_PAYLOAD.index.unique_terms,
    },
    cognee: {
      enabled: false,
      package_available: false,
      configured: false,
      connected: false,
    },
    cognee_export: {
      enabled: false,
      package_available: false,
    },
  };
}

function parseNodeId(nodeId) {
  if (!nodeId || !nodeId.includes(":")) {
    return { nodeType: "Unknown", nodeKey: nodeId || "unknown" };
  }
  const [nodeType, ...rest] = nodeId.split(":");
  return {
    nodeType,
    nodeKey: rest.join(":"),
  };
}

function pickNodeTitle(nodeId, properties = {}) {
  const candidates = [
    properties.name,
    properties.business_name,
    properties.subject,
    properties.issue,
    properties.product_name,
    properties.title,
    properties.department,
    properties.team,
    properties.customer_id,
    properties.vendor_name,
    properties.client_name,
    properties.email,
  ];

  const title = candidates.find((value) => typeof value === "string" && value.trim());
  if (title) {
    return title;
  }

  return parseNodeId(nodeId).nodeKey || nodeId;
}

function summarizeProperties(properties = {}, limit = 3) {
  const hiddenKeys = new Set(["id", "record_id", "guid", "uid"]);
  const entries = Object.entries(properties)
    .filter(([key, value]) => !hiddenKeys.has(key) && value !== null && value !== undefined && value !== "")
    .slice(0, limit)
    .map(([key, value]) => `${key}: ${String(value)}`);

  return entries.join(" | ");
}

function toFocusEntityFromResult(result) {
  if (!result) {
    return null;
  }

  return {
    node_id: result.node_id,
    node_type: result.node_type,
    title: result.title,
    summary: result.summary,
    properties: result.properties || {},
    provenance: result.provenance || [],
  };
}

function normalizeNodeResponse(node) {
  if (!node) {
    return null;
  }

  return {
    node_id: node.id,
    node_type: node.type,
    title: pickNodeTitle(node.id, node.properties || {}),
    summary: summarizeProperties(node.properties || {}),
    properties: node.properties || {},
    provenance: node.provenance || [],
  };
}

function normalizeNeighbor(sourceId, neighbor) {
  return {
    source_id: sourceId,
    node_id: neighbor.node_id,
    node_type: neighbor.node_type,
    rel_type: neighbor.rel_type,
    direction: neighbor.direction,
    title: pickNodeTitle(neighbor.node_id, neighbor.properties || {}),
    summary: summarizeProperties(neighbor.properties || {}),
    properties: neighbor.properties || {},
  };
}

function buildFallbackNeighborhood(focusEntity, focusResult, payload) {
  const firstDegree = (focusResult?.related || []).map((item) => ({
    source_id: focusEntity.node_id,
    node_id: item.node_id,
    node_type: item.node_type,
    rel_type: item.rel_type,
    direction: item.direction,
    title: item.title,
    summary: item.summary,
    properties: item.properties || {},
  }));

  const anchorNodes = firstDegree.length ? firstDegree : [{ node_id: focusEntity.node_id }];
  const secondDegree = (payload?.results || [])
    .filter((result) => result.node_id !== focusEntity.node_id)
    .slice(0, 12)
    .map((result, index) => ({
      source_id: anchorNodes[index % anchorNodes.length].node_id,
      node_id: result.node_id,
      node_type: result.node_type,
      rel_type: "context_match",
      direction: "outgoing",
      title: result.title,
      summary: result.summary,
      properties: result.properties || {},
    }));

  const ambientDegree = secondDegree.flatMap((result, index) =>
    Array.from({ length: 6 }, (_, pointIndex) => ({
      source_id: result.node_id,
      node_id: `${result.node_id}:ambient:${index}:${pointIndex}`,
      node_type: result.node_type,
      rel_type: "ambient_context",
      direction: "outgoing",
      title: `${result.title} context ${pointIndex + 1}`,
      summary: result.summary,
      properties: result.properties || {},
    })),
  );

  return {
    firstDegree,
    secondDegree,
    ambientDegree,
  };
}

function seedPoint(index, total, radius, verticalScale = 0.78, twist = 0) {
  if (!total) {
    return { x: 0, y: 0, z: radius };
  }

  const t = (index + 0.5) / total;
  const phi = Math.acos(1 - 2 * t);
  const theta = Math.PI * (3 - Math.sqrt(5)) * (index + 1 + twist);

  return {
    x: Math.cos(theta) * Math.sin(phi) * radius,
    y: Math.cos(phi) * radius * verticalScale,
    z: Math.sin(theta) * Math.sin(phi) * radius,
  };
}

function buildLayeredGraph(focusEntity, neighborhood, viewMode, showProvenance) {
  if (!focusEntity) {
    return {
      nodes: [],
      links: [],
      counts: { core: 0, direct: 0, context: 0, ambient: 0, proof: 0 },
    };
  }

  const nodes = new Map();
  const links = new Map();

  const firstDegree = neighborhood?.firstDegree || [];
  const secondDegree = (neighborhood?.secondDegree || []).slice(0, 96);
  const ambientDegree = (neighborhood?.ambientDegree || []).slice(0, 220);

  nodes.set(focusEntity.node_id, {
    id: focusEntity.node_id,
    label: focusEntity.title,
    shortLabel: focusEntity.title,
    nodeType: focusEntity.node_type,
    summary: focusEntity.summary,
    properties: focusEntity.properties || {},
    provenance: focusEntity.provenance || [],
    layer: 0,
    x: 0,
    y: 0,
    z: 0,
    fx: 0,
    fy: 0,
    fz: 0,
  });

  firstDegree.forEach((item, index) => {
    const point = seedPoint(index, Math.max(firstDegree.length, 1), 86, 0.72, 1.6);
    const existing = nodes.get(item.node_id);
    nodes.set(item.node_id, {
      ...(existing || {}),
      id: item.node_id,
      label: item.title,
      shortLabel: item.title.length > 22 ? `${item.title.slice(0, 20)}...` : item.title,
      nodeType: item.node_type,
      summary: item.summary,
      properties: item.properties || {},
      layer: 1,
      x: existing?.x ?? point.x,
      y: existing?.y ?? point.y,
      z: existing?.z ?? point.z,
    });

    links.set(`${focusEntity.node_id}-${item.node_id}-${item.rel_type}`, {
      id: `${focusEntity.node_id}-${item.node_id}-${item.rel_type}`,
      source: focusEntity.node_id,
      target: item.node_id,
      relType: item.rel_type,
      layer: 1,
      isProof: item.rel_type === "same_as",
    });
  });

  secondDegree.forEach((item, index) => {
    if (item.node_id === focusEntity.node_id) {
      return;
    }

    const point = seedPoint(index, Math.max(secondDegree.length, 1), 176, 0.92, 0.4);
    const existing = nodes.get(item.node_id);
    const targetLayer = existing?.layer ?? 2;
    nodes.set(item.node_id, {
      ...(existing || {}),
      id: item.node_id,
      label: existing?.label || item.title,
      shortLabel:
        (existing?.label || item.title).length > 20
          ? `${(existing?.label || item.title).slice(0, 18)}...`
          : existing?.label || item.title,
      nodeType: existing?.nodeType || item.node_type,
      summary: existing?.summary || item.summary,
      properties: existing?.properties || item.properties || {},
      layer: Math.min(targetLayer, 2),
      x: existing?.x ?? point.x,
      y: existing?.y ?? point.y,
      z: existing?.z ?? point.z,
    });

    const sourceId = nodes.has(item.source_id) ? item.source_id : focusEntity.node_id;
    links.set(`${sourceId}-${item.node_id}-${item.rel_type}-${index}`, {
      id: `${sourceId}-${item.node_id}-${item.rel_type}-${index}`,
      source: sourceId,
      target: item.node_id,
      relType: item.rel_type,
      layer: nodes.get(sourceId)?.layer === 0 ? 1 : 2,
      isProof: item.rel_type === "same_as",
    });
  });

  ambientDegree.forEach((item, index) => {
    if (item.node_id === focusEntity.node_id) {
      return;
    }

    const point = seedPoint(index, Math.max(ambientDegree.length, 1), 300, 1.08, 2.4);
    const existing = nodes.get(item.node_id);
    nodes.set(item.node_id, {
      ...(existing || {}),
      id: item.node_id,
      label: existing?.label || item.title,
      shortLabel:
        (existing?.label || item.title).length > 18
          ? `${(existing?.label || item.title).slice(0, 16)}...`
          : existing?.label || item.title,
      nodeType: existing?.nodeType || item.node_type,
      summary: existing?.summary || item.summary,
      properties: existing?.properties || item.properties || {},
      layer: 3,
      x: existing?.x ?? point.x,
      y: existing?.y ?? point.y,
      z: existing?.z ?? point.z,
    });

    const sourceId = nodes.has(item.source_id) ? item.source_id : focusEntity.node_id;
    links.set(`${sourceId}-${item.node_id}-${item.rel_type}-${index}`, {
      id: `${sourceId}-${item.node_id}-${item.rel_type}-${index}`,
      source: sourceId,
      target: item.node_id,
      relType: item.rel_type,
      layer: 3,
      isProof: false,
    });
  });

  const proofNodeIds = new Set();
  links.forEach((link) => {
    if (link.isProof) {
      proofNodeIds.add(link.source);
      proofNodeIds.add(link.target);
    }
  });

  const graphNodes = Array.from(nodes.values()).map((node) => {
    let opacity = 0.3;

    if (viewMode === "constellation") {
      opacity =
        node.layer === 0
          ? 1
          : node.layer === 1
            ? 0.98
            : node.layer === 2
              ? 0.72
              : 0.4;
    } else if (viewMode === "relations") {
      opacity =
        node.layer === 0
          ? 1
          : node.layer === 1
            ? 1
            : node.layer === 2
              ? 0.58
              : 0.3;
    } else {
      opacity =
        node.layer === 0
          ? 1
          : proofNodeIds.has(node.id)
            ? 0.94
            : node.layer === 1
              ? 0.74
              : node.layer === 2
                ? 0.46
                : 0.28;
    }

    return {
      ...node,
      isProofNode: proofNodeIds.has(node.id),
      opacity,
    };
  });

  const graphLinks = Array.from(links.values()).map((link) => {
    const isProof = showProvenance && link.isProof;
    let opacity = 0.2;

    if (viewMode === "constellation") {
      opacity = link.layer === 1 ? 0.7 : link.layer === 2 ? 0.34 : 0.18;
    } else if (viewMode === "relations") {
      opacity = link.layer === 1 ? 0.82 : link.layer === 2 ? 0.26 : 0.14;
    } else {
      opacity = isProof ? 0.92 : link.layer === 1 ? 0.38 : link.layer === 2 ? 0.2 : 0.12;
    }

    return {
      ...link,
      opacity,
      isProof,
    };
  });

  return {
    nodes: graphNodes,
    links: graphLinks,
    counts: {
      core: 1,
      direct: firstDegree.length,
      context: Array.from(nodes.values()).filter((node) => node.layer === 2).length,
      ambient: Array.from(nodes.values()).filter((node) => node.layer === 3).length,
      proof: graphLinks.filter((link) => link.isProof).length,
    },
  };
}

function makeNodeObject(node) {
  const group = new THREE.Group();
  const opacity = clamp(node.opacity ?? 1, 0.05, 1);
  const palette =
    node.layer === 0
      ? { core: "#fff5da", halo: "#ffe8a6" }
      : node.layer === 1
        ? { core: "#ebe1b8", halo: "#f2e8c4" }
        : node.layer === 2
          ? { core: "#bdb48f", halo: "#d7cfab" }
          : { core: "#8d8671", halo: "#bdb48f" };

  const size =
    node.layer === 0 ? 9.5 : node.layer === 1 ? 4.6 : node.layer === 2 ? 2.7 : 1.6;

  const core = new THREE.Mesh(
    new THREE.SphereGeometry(size, 20, 20),
    new THREE.MeshBasicMaterial({
      color: new THREE.Color(palette.core),
      transparent: true,
      opacity,
    }),
  );
  group.add(core);

  const aura = new THREE.Mesh(
    new THREE.SphereGeometry(size * (node.layer === 0 ? 1.7 : 1.35), 16, 16),
    new THREE.MeshBasicMaterial({
      color: new THREE.Color(palette.halo),
      transparent: true,
      opacity:
        node.layer === 0 ? opacity * 0.16 : node.layer === 1 ? opacity * 0.12 : opacity * 0.08,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  group.add(aura);

  if (node.layer === 0) {
    const glow = new THREE.Mesh(
      new THREE.SphereGeometry(size * 2.25, 18, 18),
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(palette.halo),
        transparent: true,
        opacity: 0.18,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    group.add(glow);

    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(size * 1.9, 0.15, 12, 64),
      new THREE.MeshBasicMaterial({
        color: new THREE.Color("#fff2c2"),
        transparent: true,
        opacity: 0.82,
        depthWrite: false,
      }),
    );
    ring.rotation.x = Math.PI / 2;
    group.add(ring);
  }

  if (node.isHovered || node.layer === 0 || node.layer === 1) {
    const label = new SpriteText(node.shortLabel || node.label);
    label.color = "#f8f4ea";
    label.textHeight = node.layer === 0 ? 4.1 : 1.85;
    label.position.set(0, size * 2.05, 0);
    label.material.depthWrite = false;
    label.material.transparent = true;
    label.material.opacity = opacity;
    group.add(label);
  }

  return group;
}

function ScenarioPill({ scenario, active, onSelect }) {
  return (
    <button
      type="button"
      className={`scenario-pill${active ? " is-active" : ""}`}
      onClick={onSelect}
    >
      <span>{scenario.shortLabel}</span>
      <strong>{scenario.label}</strong>
    </button>
  );
}

function FocusOptionCard({ result, active, onSelect }) {
  return (
    <button
      type="button"
      className={`focus-option${active ? " is-active" : ""}`}
      onClick={onSelect}
    >
      <div className="focus-option__topline">
        <span>#{result.rank}</span>
        <em>{result.node_type}</em>
      </div>
      <strong>{result.title}</strong>
      <p>{result.summary}</p>
    </button>
  );
}

function GraphView() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const focusFromUrl = searchParams.get("focus");
  const graphRef = useRef(null);
  const stageRef = useRef(null);
  const [presetId, setPresetId] = useState(STORY_PRESETS[0].id);
  const [query, setQuery] = useState(STORY_PRESETS[0].query);
  const [payload, setPayload] = useState(FALLBACK_PAYLOAD);
  const [status, setStatus] = useState(buildFallbackStatus());
  const [source, setSource] = useState("fallback");
  const [viewMode, setViewMode] = useState("constellation");
  const [showProvenance, setShowProvenance] = useState(true);
  const [focusEntity, setFocusEntity] = useState(() => toFocusEntityFromResult(FALLBACK_PAYLOAD.results[0]));
  const [focusApiData, setFocusApiData] = useState(null);
  const [focusNeighborhood, setFocusNeighborhood] = useState(() =>
    buildFallbackNeighborhood(
      toFocusEntityFromResult(FALLBACK_PAYLOAD.results[0]),
      FALLBACK_PAYLOAD.results[0],
      FALLBACK_PAYLOAD,
    ),
  );
  const [focusLoading, setFocusLoading] = useState(false);
  const [hoveredNodeId, setHoveredNodeId] = useState(null);
  const [hoveredNodeLabel, setHoveredNodeLabel] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [stageSize, setStageSize] = useState({ width: 1200, height: 720 });

  const currentScenario =
    STORY_PRESETS.find((preset) => preset.id === presetId) || STORY_PRESETS[0];

  const focusResult = useMemo(
    () => payload.results.find((result) => result.node_id === focusEntity?.node_id) || null,
    [focusEntity?.node_id, payload.results],
  );

  const mergedFocusEntity = useMemo(() => {
    if (!focusEntity) {
      return null;
    }

    return {
      ...focusEntity,
      title: focusApiData?.title || focusEntity.title,
      summary: focusApiData?.summary || focusEntity.summary,
      properties: focusApiData?.properties || focusEntity.properties || {},
      provenance: focusApiData?.provenance || focusEntity.provenance || [],
      node_type: focusApiData?.node_type || focusEntity.node_type,
    };
  }, [focusApiData, focusEntity]);

  const graphModel = useMemo(
    () => buildLayeredGraph(mergedFocusEntity, focusNeighborhood, viewMode, showProvenance),
    [focusNeighborhood, mergedFocusEntity, showProvenance, viewMode],
  );

  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/retrieval/status`);
      if (!response.ok) {
        throw new Error(`status ${response.status}`);
      }
      const data = await response.json();
      setStatus(data);
    } catch {
      setStatus(buildFallbackStatus());
    }
  }, []);

  const runQuery = useCallback(async (nextQuery) => {
    setLoading(true);
    setError("");

    try {
      const response = await fetch(
        `${API_BASE}/retrieve?q=${encodeURIComponent(nextQuery)}&mode=auto&top_k=5`,
      );
      if (!response.ok) {
        throw new Error(`retrieve ${response.status}`);
      }
      const data = await response.json();
      if (!data.results || data.results.length === 0) {
        throw new Error("empty results");
      }

      setPayload(data);
      setSource("live");
      setFocusApiData(null);
      setFocusEntity(toFocusEntityFromResult(data.results[0]));
      setFocusNeighborhood(
        buildFallbackNeighborhood(toFocusEntityFromResult(data.results[0]), data.results[0], data),
      );
    } catch {
      const fallbackPayload = {
        ...FALLBACK_PAYLOAD,
        query: nextQuery,
      };

      setPayload(fallbackPayload);
      setSource("fallback");
      setFocusApiData(null);
      setFocusEntity(toFocusEntityFromResult(fallbackPayload.results[0]));
      setFocusNeighborhood(
        buildFallbackNeighborhood(
          toFocusEntityFromResult(fallbackPayload.results[0]),
          fallbackPayload.results[0],
          fallbackPayload,
        ),
      );
      setError("Backend unavailable - showing object-centric fallback mode.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    runQuery(query);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // If we landed here via a "?focus=Type:key" deep-link from a conflict,
  // override the default focus once the initial query has settled.
  useEffect(() => {
    if (!focusFromUrl) return;
    setFocusApiData(null);
    setFocusEntity({
      node_id: focusFromUrl,
      node_type: parseNodeId(focusFromUrl).nodeType,
      title: parseNodeId(focusFromUrl).nodeKey,
      summary: "Loading focus from conflict drilldown…",
      properties: {},
      provenance: [],
    });
  }, [focusFromUrl]);

  useEffect(() => {
    if (!stageRef.current) {
      return undefined;
    }

    const element = stageRef.current;

    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      setStageSize({
        width: Math.max(320, Math.round(rect.width)),
        height: Math.max(320, Math.round(rect.height)),
      });
    };

    updateSize();

    const observer = new ResizeObserver(() => updateSize());
    observer.observe(element);

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!focusEntity?.node_id) {
      return undefined;
    }

    let cancelled = false;

    async function loadFocusNeighborhood() {
      setFocusLoading(true);

      try {
        const { nodeType, nodeKey } = parseNodeId(focusEntity.node_id);
        const [nodeResponse, neighborsResponse] = await Promise.all([
          fetch(`${API_BASE}/graph/node/${encodeURIComponent(nodeType)}/${encodeURIComponent(nodeKey)}`),
          fetch(`${API_BASE}/graph/neighbors/${encodeURIComponent(nodeType)}/${encodeURIComponent(nodeKey)}`),
        ]);

        if (!nodeResponse.ok || !neighborsResponse.ok) {
          throw new Error("graph focus unavailable");
        }

        const nodeData = await nodeResponse.json();
        const neighborData = await neighborsResponse.json();
        const firstDegree = (neighborData.neighbors || []).map((item) =>
          normalizeNeighbor(focusEntity.node_id, item),
        );

        const expansionSeeds = firstDegree.slice(0, 12);
        const secondDegreeResponses = await Promise.all(
          expansionSeeds.map(async (seed) => {
            const parsed = parseNodeId(seed.node_id);
            const response = await fetch(
              `${API_BASE}/graph/neighbors/${encodeURIComponent(parsed.nodeType)}/${encodeURIComponent(parsed.nodeKey)}`,
            );
            if (!response.ok) {
              return [];
            }
            const data = await response.json();
            return (data.neighbors || [])
              .map((item) => normalizeNeighbor(seed.node_id, item))
              .filter((item) => item.node_id !== focusEntity.node_id);
          }),
        );

        const secondDegree = secondDegreeResponses.flat();
        const ambientSeeds = secondDegree.slice(0, 18);
        const ambientResponses = await Promise.all(
          ambientSeeds.map(async (seed) => {
            const parsed = parseNodeId(seed.node_id);
            const response = await fetch(
              `${API_BASE}/graph/neighbors/${encodeURIComponent(parsed.nodeType)}/${encodeURIComponent(parsed.nodeKey)}`,
            );
            if (!response.ok) {
              return [];
            }
            const data = await response.json();
            return (data.neighbors || [])
              .map((item) => normalizeNeighbor(seed.node_id, item))
              .filter((item) => item.node_id !== focusEntity.node_id && item.node_id !== seed.source_id)
              .slice(0, 14);
          }),
        );

        if (cancelled) {
          return;
        }

        setFocusApiData(normalizeNodeResponse(nodeData));
        setFocusNeighborhood({
          firstDegree,
          secondDegree,
          ambientDegree: ambientResponses.flat(),
        });
      } catch {
        if (cancelled) {
          return;
        }
        setFocusApiData(null);
        setFocusNeighborhood(buildFallbackNeighborhood(focusEntity, focusResult, payload));
      } finally {
        if (!cancelled) {
          setFocusLoading(false);
        }
      }
    }

    loadFocusNeighborhood();

    return () => {
      cancelled = true;
    };
  }, [focusEntity, focusResult, payload]);

  useEffect(() => {
    if (!graphRef.current) {
      return;
    }

    const graph = graphRef.current;
    const charge = graph.d3Force("charge");
    const linkForce = graph.d3Force("link");

        if (charge) {
      charge.strength((node) => {
        if (node.layer === 0) {
          return -620;
        }
        if (node.layer === 1) {
          return -360;
        }
        if (node.layer === 2) {
          return -180;
        }
        return -70;
      });
    }

    if (linkForce) {
      linkForce.distance((link) => {
        if (link.layer === 1) {
          return 118;
        }
        if (link.layer === 2) {
          return 210;
        }
        return 320;
      });
      linkForce.strength((link) => {
        if (link.layer === 1) {
          return 0.36;
        }
        if (link.layer === 2) {
          return 0.11;
        }
        return 0.05;
      });
    }

    graph.d3ReheatSimulation();
  }, [graphModel.nodes.length, graphModel.links.length, viewMode]);

  useEffect(() => {
    if (!graphRef.current || !graphModel.nodes.length) {
      return undefined;
    }

    const graph = graphRef.current;
    const timer = window.setTimeout(() => {
      graph.cameraPosition(
        { x: 0, y: 20, z: viewMode === "proof" ? 155 : 185 },
        { x: 0, y: 0, z: 0 },
        1200,
      );
    }, 220);

    return () => window.clearTimeout(timer);
  }, [graphModel.nodes, viewMode]);

  const handleSubmit = (event) => {
    event.preventDefault();
    runQuery(query);
  };

  const nodeThreeObject = useCallback(
    (node) => makeNodeObject({ ...node, isHovered: node.id === hoveredNodeId }),
    [hoveredNodeId],
  );

  const liveDocuments = status?.local?.documents || payload?.index?.documents || 0;
  const liveTerms = status?.local?.unique_terms || payload?.index?.unique_terms || 0;
  const focusProperties = Object.entries(mergedFocusEntity?.properties || {}).slice(0, 6);

  return (
    <div className="app-shell">
      <div className="ambient ambient--left" />
      <div className="ambient ambient--right" />
      <div className="noise-layer" />

      <header className="hero-bar glass-panel">
        <div className="hero-copy">
          <button
            type="button"
            onClick={() => navigate("/")}
            style={{
              background: "transparent",
              border: "1px solid rgba(255,255,255,0.18)",
              color: "rgba(255,255,255,0.78)",
              borderRadius: 999,
              padding: "4px 12px",
              fontSize: 12,
              cursor: "pointer",
              marginBottom: 10,
            }}
          >
            ← Conflicts
          </button>
          <div className="eyebrow">Qontext Object Lens</div>
          <h1>One data object at the center. Every surrounding layer readable.</h1>
          <p>{currentScenario.focusTitle}</p>
        </div>

        <div className="hero-controls">
          <div className="scenario-strip">
            {STORY_PRESETS.map((scenario) => (
              <ScenarioPill
                key={scenario.id}
                scenario={scenario}
                active={scenario.id === presetId}
                onSelect={() => {
                  setPresetId(scenario.id);
                  setQuery(scenario.query);
                  runQuery(scenario.query);
                }}
              />
            ))}
          </div>

          <form className="query-form" onSubmit={handleSubmit}>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ask a business question..."
            />
            <button type="submit" className="primary-button" disabled={loading}>
              {loading ? "Reading memory..." : "Run retrieval"}
            </button>
          </form>

          <div className="hero-stats">
            <span className={`status-pill status-pill--${source}`}>
              {source === "live" ? "live graph" : "story mode"}
            </span>
            <span className="status-pill">{formatModeLabel(payload.mode)}</span>
            <span className="status-pill">{liveDocuments} docs</span>
            <span className="status-pill">{liveTerms} terms</span>
          </div>
        </div>
      </header>

      <main ref={stageRef} className="stage-shell glass-panel">
        <div className="graph-backdrop">
          <ForceGraph3D
            ref={graphRef}
            width={stageSize.width}
            height={stageSize.height}
            graphData={graphModel}
            backgroundColor="#04060b"
            showNavInfo={false}
            enableNodeDrag={false}
            enableNavigationControls
            nodeResolution={16}
            cooldownTicks={140}
            nodeThreeObject={nodeThreeObject}
            linkWidth={(link) => {
              if (link.isProof) {
                return 1.55;
              }
              if (link.layer === 1) {
                return 1.1;
              }
              if (link.layer === 2) {
                return 0.62;
              }
              return 0.36;
            }}
            linkColor={(link) => {
              if (link.isProof) {
                return `rgba(255, 232, 167, ${link.opacity})`;
              }
              if (link.layer === 1) {
                return `rgba(236, 230, 208, ${link.opacity})`;
              }
              if (link.layer === 2) {
                return `rgba(198, 192, 172, ${link.opacity})`;
              }
              return `rgba(163, 160, 148, ${link.opacity})`;
            }}
            linkOpacity={1}
            onEngineStop={() => {
              graphRef.current?.zoomToFit(900, 18);
            }}
            onNodeHover={(node) => {
              setHoveredNodeId(node?.id || null);
              setHoveredNodeLabel(node?.label || "");
            }}
            onNodeClick={(node) => {
              if (!node) {
                return;
              }
              setFocusApiData(null);
              setFocusEntity({
                node_id: node.id,
                node_type: node.nodeType,
                title: node.label,
                summary: node.summary,
                properties: node.properties || {},
                provenance: node.provenance || [],
              });
            }}
          />
        </div>

        <div className="stage-overlay stage-overlay--top">
          <div className="glass-float focus-hero-card">
            <div className="eyebrow">Centered object</div>
            <h2>{mergedFocusEntity?.title || "No object selected"}</h2>
            <p>{mergedFocusEntity?.summary || "Select a retrieved object to center the graph."}</p>
            <div className="meta-row">
              <span className="type-chip">{mergedFocusEntity?.node_type || "Unknown"}</span>
              <span className="soft-pill">{focusLoading ? "loading live neighborhood" : "object neighborhood"}</span>
            </div>
          </div>

          <div className="glass-float layer-card">
            <div className="eyebrow">Graph layers</div>
            <div className="layer-list">
              <div className="layer-row">
                <span>Layer 0</span>
                <strong>Core object</strong>
                <em>{graphModel.counts.core}</em>
              </div>
              <div className="layer-row">
                <span>Layer 1</span>
                <strong>Direct relations</strong>
                <em>{graphModel.counts.direct}</em>
              </div>
              <div className="layer-row">
                <span>Layer 2</span>
                <strong>Wider context</strong>
                <em>{graphModel.counts.context}</em>
              </div>
              <div className="layer-row">
                <span>Layer 3</span>
                <strong>Ambient cloud</strong>
                <em>{graphModel.counts.ambient}</em>
              </div>
              <div className="layer-row">
                <span>Proof</span>
                <strong>same_as edges</strong>
                <em>{graphModel.counts.proof}</em>
              </div>
            </div>

            <div className="view-mode-strip">
              {VIEW_MODES.map((mode) => (
                <button
                  key={mode.id}
                  type="button"
                  className={`chip chip--ghost${viewMode === mode.id ? " is-selected" : ""}`}
                  onClick={() => setViewMode(mode.id)}
                >
                  {mode.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="stage-overlay stage-overlay--bottom">
          <div className="glass-float object-rail">
            <div className="eyebrow">Recenter on a retrieved object</div>
            <div className="object-rail__list">
              {payload.results.map((result) => (
                <FocusOptionCard
                  key={result.node_id}
                  result={result}
                  active={result.node_id === mergedFocusEntity?.node_id}
                  onSelect={() => {
                    setFocusApiData(null);
                    setFocusEntity(toFocusEntityFromResult(result));
                  }}
                />
              ))}
            </div>
          </div>

          <div className="glass-float interaction-card">
            <div className="eyebrow">Interaction</div>
            <p>Drag to rotate, scroll to zoom, click any node to bring that object into the center.</p>
            <label className="switch-row">
              <span>Show proof edges</span>
              <button
                type="button"
                className={`chip chip--ghost${showProvenance ? " is-selected" : ""}`}
                onClick={() => setShowProvenance((value) => !value)}
              >
                {showProvenance ? "On" : "Off"}
              </button>
            </label>
          </div>
        </div>
      </main>

      <aside className="inspector">
        <section className="glass-panel inspector-card inspector-card--headline">
          <div className="panel-head panel-head--stacked">
            <div>
              <div className="eyebrow">Focused object</div>
              <h2>{mergedFocusEntity?.title || "No object selected"}</h2>
            </div>
            <p className="panel-copy">{currentScenario.caption}</p>
          </div>

          <div className="meta-row meta-row--wrap">
            <span className="type-chip">{mergedFocusEntity?.node_type || "Unknown"}</span>
            {focusResult ? <span className="soft-pill">retrieval score {focusResult.score?.toFixed(2)}</span> : null}
            <span className="soft-pill">{hoveredNodeLabel || "hover any node"}</span>
          </div>

          <p className="inspector-summary">{mergedFocusEntity?.summary || "No summary available."}</p>

          <div className="property-grid">
            {focusProperties.length ? (
              focusProperties.map(([key, value]) => (
                <div key={key} className="property-card">
                  <span>{key}</span>
                  <strong>{String(value)}</strong>
                </div>
              ))
            ) : (
              <div className="property-card property-card--empty">
                <span>Properties</span>
                <strong>No structured fields available</strong>
              </div>
            )}
          </div>
        </section>

        <section className="glass-panel inspector-card">
          <div className="panel-head">
            <div>
              <div className="eyebrow">Why it surfaced</div>
              <h3>Retrieval explanation</h3>
            </div>
          </div>

          {focusResult ? (
            <>
              <div className="score-strip">
                <div className="score-chip">
                  <span>Total</span>
                  <strong>{focusResult.score?.toFixed(2)}</strong>
                </div>
                <div className="score-chip">
                  <span>Graph</span>
                  <strong>{focusResult.graph_score?.toFixed(2)}</strong>
                </div>
                <div className="score-chip">
                  <span>Vector</span>
                  <strong>{focusResult.vector_score?.toFixed(2)}</strong>
                </div>
              </div>

              <ul className="drawer-list">
                {(focusResult.evidence || []).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          ) : (
            <p className="panel-copy">
              This object is currently centered from the graph itself, not from the top retrieval list.
            </p>
          )}
        </section>

        <section className="glass-panel inspector-card">
          <div className="panel-head">
            <div>
              <div className="eyebrow">Layer 1</div>
              <h3>Direct relations</h3>
            </div>
          </div>

          <div className="relation-list">
            {(focusNeighborhood.firstDegree || []).slice(0, 8).map((item) => (
              <div key={`${item.node_id}-${item.rel_type}`} className="relation-card">
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.node_type}</span>
                </div>
                <em>{item.rel_type}</em>
              </div>
            ))}
          </div>
        </section>

        <section className="glass-panel inspector-card">
          <div className="panel-head">
            <div>
              <div className="eyebrow">Source anchors</div>
              <h3>Where the object came from</h3>
            </div>
          </div>

          <div className="provenance-list">
            {(mergedFocusEntity?.provenance || []).length ? (
              (mergedFocusEntity.provenance || []).map((item) => (
                <div key={`${item.source_system}-${item.record_id}`} className="provenance-card">
                  <strong>{item.source_system}</strong>
                  <span>{item.file}</span>
                  <span>{item.record_id}</span>
                </div>
              ))
            ) : (
              <div className="provenance-card provenance-card--empty">
                <strong>No provenance available</strong>
                <span>The centered object did not expose source anchors yet.</span>
              </div>
            )}
          </div>
        </section>

        {error ? <div className="error-banner">{error}</div> : null}
      </aside>
    </div>
  );
}

export default GraphView;
