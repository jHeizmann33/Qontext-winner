import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeftRight, ArrowRight, ChevronDown, FileText, Network } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  CONFLICTS,
  PAST_DECISIONS,
  type Conflict,
  type Decision,
  type Risk,
  type SourceDocument,
  type SourceField,
} from "@/lib/qontext-data";
import {
  useConflictsQuery,
  useResolveConflictMutation,
} from "@/lib/useConflicts";

const RISK_STYLES: Record<Risk, string> = {
  high: "bg-[#450A0A]/30 text-[#FCA5A5]",
  med: "bg-[#422006]/30 text-[#FCD34D]",
  low: "bg-[#1E293B]/30 text-[#94A3B8]",
};

const FIELD_LABELS: Record<SourceField, string> = {
  party: "Party",
  date: "Date",
  amount: "Amount",
  clause: "Clause",
  jurisdiction: "Jurisdiction",
};

const FIELD_ORDER: SourceField[] = [
  "party",
  "date",
  "amount",
  "clause",
  "jurisdiction",
];

const VERDICT_COLOR: Record<Decision, string> = {
  approve: "text-[#6EE7B7]",
  reject: "text-[#FCA5A5]",
  escalate: "text-[#FCD34D]",
};

const VERDICT_DOT: Record<Decision, string> = {
  approve: "bg-[#6EE7B7]",
  reject: "bg-[#FCA5A5]",
  escalate: "bg-[#FCD34D]",
};

const VERDICT_LABEL: Record<Decision, string> = {
  approve: "Approve",
  reject: "Reject",
  escalate: "Escalate",
};

function RiskBadge({ risk }: { risk: Risk }) {
  return (
    <span
      className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${RISK_STYLES[risk]}`}
    >
      {risk === "med" ? "medium" : risk}
    </span>
  );
}

function Kbd({ children, dark = false }: { children: React.ReactNode; dark?: boolean }) {
  return (
    <span
      className={`font-mono text-[10px] font-semibold rounded px-1.5 py-0.5 leading-none ${
        dark ? "bg-black/15 text-black/60" : "bg-[#18181B] text-[#A1A1AA] border border-[#2A2A2F]"
      }`}
    >
      {children}
    </span>
  );
}

function decisionPill(d: Decision) {
  const map: Record<Decision, string> = {
    approve: "bg-[#064E3B]/40 text-[#6EE7B7]",
    reject: "bg-[#450A0A]/40 text-[#FCA5A5]",
    escalate: "bg-[#422006]/40 text-[#FCD34D]",
  };
  return (
    <span
      className={`font-mono text-[10px] uppercase tracking-wide rounded px-1.5 py-0.5 ${map[d]}`}
    >
      {d}
    </span>
  );
}

function splitRationale(text: string): string[] {
  // Split on sentence boundaries, keep up to 2 lines
  const parts = text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.length <= 1) return parts;
  return parts.slice(0, 2);
}

function computeAmountDelta(a: string, b: string): string | null {
  const num = (s: string) => {
    const m = s.match(/[\d.,]+/);
    if (!m) return NaN;
    return parseFloat(m[0].replace(/,/g, ""));
  };
  const av = num(a);
  const bv = num(b);
  if (!isFinite(av) || !isFinite(bv) || av === 0) return null;
  const diff = bv - av;
  const pct = (diff / av) * 100;
  const sign = diff >= 0 ? "+" : "−";
  const absDiff = Math.abs(diff);
  let formatted: string;
  if (absDiff >= 1000) {
    formatted = `${Math.round(absDiff / 1000)}k`;
  } else {
    formatted = absDiff.toFixed(0);
  }
  return `${sign}${formatted} / ${sign}${pct.toFixed(1)}%`;
}

const Index = () => {
  const navigate = useNavigate();
  const { data: serverConflicts } = useConflictsQuery();
  const resolveMutation = useResolveConflictMutation();

  // Local queue state mirrors React Query data so action UX (filter, advance,
  // toast) stays instantaneous. The query is the source of truth on (re)load
  // and after invalidation; user actions update the local copy optimistically.
  const [queue, setQueue] = useState<Conflict[]>(CONFLICTS);
  const [selectedId, setSelectedId] = useState<string>(CONFLICTS[0]?.id ?? "");
  const [reviewedCount, setReviewedCount] = useState(12);
  const [expandedAll, setExpandedAll] = useState(false);
  const totalToday = 47;

  useEffect(() => {
    if (!serverConflicts) return;
    setQueue(serverConflicts);
    setSelectedId((current) => {
      if (serverConflicts.some((c) => c.id === current)) return current;
      return serverConflicts[0]?.id ?? "";
    });
  }, [serverConflicts]);

  const selected = useMemo(
    () => queue.find((c) => c.id === selectedId) ?? queue[0],
    [queue, selectedId],
  );

  const advance = useCallback(
    (dir: 1 | -1) => {
      if (!selected) return;
      const idx = queue.findIndex((c) => c.id === selected.id);
      const next = queue[idx + dir];
      if (next) setSelectedId(next.id);
    },
    [queue, selected],
  );

  const act = useCallback(
    (decision: Decision | "skip") => {
      if (!selected) return;
      const id = selected.id;
      const idx = queue.findIndex((c) => c.id === id);

      if (decision === "skip") {
        const next = queue[idx + 1] ?? queue[0];
        if (next && next.id !== id) setSelectedId(next.id);
        toast(`Skipped ${id}`, {
          icon: <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#52525B]" />,
        });
        return;
      }

      const verb =
        decision === "approve" ? "Approved" : decision === "reject" ? "Rejected" : "Escalated";
      const dotColor =
        decision === "approve" ? "#6EE7B7" : decision === "reject" ? "#FCA5A5" : "#FCD34D";

      const newQueue = queue.filter((c) => c.id !== id);
      const nextSelected = newQueue[idx] ?? newQueue[idx - 1] ?? newQueue[0];
      setQueue(newQueue);
      if (nextSelected) setSelectedId(nextSelected.id);
      setReviewedCount((n) => Math.min(totalToday, n + 1));
      setExpandedAll(false);
      toast(`${verb} ${id}`, {
        icon: (
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: dotColor }}
          />
        ),
      });

      // Fire-and-forget the backend resolve. Failure simply leaves the local
      // optimistic update in place; the next refetch will reconcile.
      resolveMutation.mutate({ conflict: selected, decision });
    },
    [queue, selected, resolveMutation],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      const k = e.key.toLowerCase();
      if (k === "j") {
        e.preventDefault();
        advance(1);
      } else if (k === "k") {
        e.preventDefault();
        advance(-1);
      } else if (k === "a") {
        e.preventDefault();
        // Primary button = confirm AI's recommended action when high confidence;
        // when low confidence, A still maps to approve.
        if (selected && selected.aiSuggestion.confidence >= 0.7) {
          act(selected.aiSuggestion.action);
        } else {
          act("approve");
        }
      } else if (k === "r") {
        e.preventDefault();
        act("reject");
      } else if (k === "e") {
        e.preventDefault();
        act("escalate");
      } else if (e.code === "Space") {
        e.preventDefault();
        act("skip");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [advance, act, selected]);

  const progressPct = Math.round((reviewedCount / totalToday) * 100);

  return (
    <div className="h-screen w-full flex flex-col bg-[#0A0A0B] text-[#E4E4E7] overflow-hidden">
      {/* Top bar */}
      <header className="h-14 shrink-0 flex items-center justify-between px-5 border-b border-[#1F1F23]">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-sm bg-[#E4E4E7]" />
          <h1 className="text-sm font-semibold tracking-tight text-[#E4E4E7]">qontext</h1>
        </div>

        <div className="flex flex-col items-center gap-1">
          <div className="flex items-center gap-2 rounded-full bg-[#111113] border border-[#1F1F23] px-3 py-1">
            <span className="font-mono text-xs text-[#D4D4D8]">
              {reviewedCount} / {totalToday}
            </span>
            <span className="text-xs text-[#52525B]">reviewed today</span>
          </div>
          <div className="h-px w-44 bg-[#1F1F23] overflow-hidden">
            <div
              className="h-full bg-[#E4E4E7] transition-all duration-150"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        <div className="h-8 w-8 rounded-full bg-[#18181B] border border-[#1F1F23] flex items-center justify-center font-mono text-xs text-[#A1A1AA]">
          JM
        </div>
      </header>

      <div className="flex-1 flex min-h-0">
        {/* Left rail */}
        <aside className="w-[280px] shrink-0 border-r border-[#1F1F23] flex flex-col min-h-0 bg-[#111113]">
          <div className="px-4 py-3 border-b border-[#1F1F23] flex items-center justify-between">
            <span className="text-xs uppercase tracking-wide text-[#52525B]">Queue</span>
            <span className="font-mono text-xs text-[#A1A1AA]">{queue.length}</span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {queue.map((c) => {
              const active = c.id === selected?.id;
              return (
                <button
                  key={c.id}
                  onClick={() => setSelectedId(c.id)}
                  className={`w-full text-left px-4 py-3 border-b border-[#1F1F23] transition-colors duration-150 border-l-2 ${
                    active
                      ? "bg-[#18181B] border-l-[#E4E4E7]"
                      : "border-l-transparent hover:bg-[#18181B]/60"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-mono text-xs text-[#A1A1AA]">{c.id}</span>
                    <RiskBadge risk={c.risk} />
                  </div>
                  <p className="text-sm text-[#E4E4E7] leading-snug line-clamp-2 mb-1.5">
                    {c.title}
                  </p>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-[#52525B] truncate pr-2">
                      {c.parties[0]} ⇄ {c.parties[1]}
                    </span>
                    <span className="font-mono text-[10px] text-[#52525B] shrink-0">{c.age}</span>
                  </div>
                </button>
              );
            })}
            {queue.length === 0 && (
              <div className="px-4 py-8 text-center text-sm text-[#52525B]">
                Queue cleared.
              </div>
            )}
          </div>
        </aside>

        {/* Main panel */}
        <main className="flex-1 flex flex-col min-w-0 min-h-0 bg-[#0A0A0B]">
          {selected ? (
            <MainPanel
              key={selected.id}
              conflict={selected}
              expandedAll={expandedAll}
              setExpandedAll={setExpandedAll}
              onAct={act}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center text-[#52525B] text-sm">
              All conflicts reviewed.
            </div>
          )}
        </main>
      </div>
    </div>
  );
};

interface MainPanelProps {
  conflict: Conflict;
  expandedAll: boolean;
  setExpandedAll: (v: boolean) => void;
  onAct: (d: Decision | "skip") => void;
}

function MainPanel({ conflict, expandedAll, setExpandedAll, onAct }: MainPanelProps) {
  const navigate = useNavigate();
  const ai = conflict.aiSuggestion;
  const confidencePct = Math.round(ai.confidence * 100);
  const isHighConfidence = ai.confidence >= 0.7;
  const rationale = splitRationale(ai.reasoning);
  const showEvidence =
    isHighConfidence && (ai.action === "reject" || ai.action === "escalate");

  const matchingFields = FIELD_ORDER.filter((f) => !conflict.conflictFields.includes(f));

  // Document viewer sheet state
  const [openDoc, setOpenDoc] = useState<"A" | "B" | null>(null);
  const [reviewedDocs, setReviewedDocs] = useState<Set<"A" | "B">>(new Set());

  const openSheet = useCallback((side: "A" | "B") => {
    setOpenDoc(side);
    setReviewedDocs((prev) => {
      if (prev.has(side)) return prev;
      const next = new Set(prev);
      next.add(side);
      return next;
    });
  }, []);

  // Numeric shortcuts 1/2 to open source documents
  useEffect(() => {
    if (!showEvidence) return;
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "1" && conflict.sourceA.document) {
        e.preventDefault();
        openSheet("A");
      } else if (e.key === "2" && conflict.sourceB.document) {
        e.preventDefault();
        openSheet("B");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showEvidence, openSheet, conflict.sourceA.document, conflict.sourceB.document]);

  const activeDoc: SourceDocument | undefined =
    openDoc === "A"
      ? conflict.sourceA.document
      : openDoc === "B"
        ? conflict.sourceB.document
        : undefined;

  return (
    <>
      <div className="flex-1 overflow-y-auto px-10 pt-6 pb-6">
        {/* Breadcrumb row */}
        <div className="flex items-start justify-between mb-8">
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs text-[#52525B]">{conflict.id}</span>
            <RiskBadge risk={conflict.risk} />
            <div className="flex items-center gap-1.5 text-xs text-[#A1A1AA]">
              <span>{conflict.parties[0]}</span>
              <ArrowLeftRight className="h-3 w-3 text-[#52525B]" />
              <span>{conflict.parties[1]}</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                const target = conflict.entityId
                  ? `/lens?focus=${encodeURIComponent(conflict.entityId)}`
                  : "/lens";
                navigate(target);
              }}
              className="flex items-center gap-1.5 rounded-full bg-[#111113] border border-[#1F1F23] px-3 py-1 text-xs text-[#A1A1AA] hover:bg-[#18181B] hover:border-[#2A2A2F] hover:text-[#E4E4E7] transition-colors duration-150"
              title={
                conflict.entityId
                  ? `Open ${conflict.entityId} in 3D graph`
                  : "Open 3D graph view"
              }
            >
              <Network className="h-3 w-3" />
              <span>Open in graph</span>
            </button>

          <Popover>
            <PopoverTrigger asChild>
              <button className="flex items-center gap-2 rounded-full bg-[#111113] border border-[#1F1F23] px-3 py-1 text-xs text-[#A1A1AA] hover:bg-[#18181B] hover:border-[#2A2A2F] hover:text-[#E4E4E7] transition-colors duration-150">
                <span className="font-mono">4 similar</span>
                <span className="text-[#52525B]">·</span>
                <span className="text-[#FCA5A5]">75% rejected</span>
              </button>
            </PopoverTrigger>
            <PopoverContent
              align="end"
              className="w-[360px] bg-[#111113] border-[#1F1F23] p-0"
            >
              <div className="px-4 py-3 border-b border-[#1F1F23]">
                <div className="text-xs uppercase tracking-wide text-[#52525B]">
                  Similar past decisions
                </div>
              </div>
              <ul className="py-1">
                {PAST_DECISIONS.map((p) => (
                  <li
                    key={p.id}
                    className="flex items-center justify-between px-4 py-2 hover:bg-[#18181B] transition-colors duration-150"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="font-mono text-xs text-[#D4D4D8]">{p.id}</span>
                      {decisionPill(p.decision)}
                    </div>
                    <div className="flex items-center gap-2 text-[#52525B]">
                      <span className="font-mono text-[10px]">{p.reviewer}</span>
                      <span className="font-mono text-[10px] text-[#52525B]">{p.date}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </PopoverContent>
          </Popover>
          </div>
        </div>

        {/* Verdict hero */}
        <div className="mb-10">
          <div className="flex items-center gap-2.5 mb-3">
            <ConfidenceRing confidence={ai.confidence} />
            <div className="text-xs uppercase tracking-wide text-[#52525B]">
              {isHighConfidence ? (
                <>AI Verdict · {confidencePct}% confidence</>
              ) : (
                <>AI Notes · {confidencePct}% confidence</>
              )}
            </div>
          </div>
          {isHighConfidence ? (
            <h2
              className={`text-5xl font-semibold tracking-tight leading-none mb-5 ${VERDICT_COLOR[ai.action]}`}
            >
              {VERDICT_LABEL[ai.action]}
            </h2>
          ) : (
            <h2 className="text-3xl font-semibold tracking-tight leading-tight mb-5 text-[#E4E4E7]">
              Review required —{" "}
              <span className="text-[#A1A1AA]">AI uncertain ({confidencePct}% confidence)</span>
            </h2>
          )}
          <div className="space-y-1 text-[#A1A1AA] text-base leading-relaxed max-w-3xl">
            {!isHighConfidence && (
              <div className="text-xs uppercase tracking-wide text-[#52525B] mb-1">
                AI notes:
              </div>
            )}
            {rationale.map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>
        </div>

        {showEvidence ? (
          <EvidenceSection
            conflict={conflict}
            onOpenDoc={openSheet}
          />
        ) : (
          // Approve / low-confidence: keep the original compact diff
          <div className="mb-6">
            <div className="text-xs uppercase tracking-wide text-[#52525B] mb-3">
              Conflicting fields
            </div>
            <div className="divide-y divide-[#1F1F23] border-y border-[#1F1F23]">
              {conflict.conflictFields.map((f) => {
                const a = conflict.sourceA[f];
                const b = conflict.sourceB[f];
                const delta = f === "amount" ? computeAmountDelta(a, b) : null;
                return (
                  <div
                    key={f}
                    className="grid grid-cols-[140px_1fr_auto_1fr_auto] items-center gap-4 py-3"
                  >
                    <div className="font-mono text-xs uppercase tracking-wide text-[#52525B]">
                      {FIELD_LABELS[f]}
                    </div>
                    <div className="font-mono text-sm text-[#FCA5A5] break-words">{a}</div>
                    <ArrowRight className="h-3.5 w-3.5 text-[#52525B]" />
                    <div className="font-mono text-sm text-[#FCA5A5] break-words">{b}</div>
                    <div className="min-w-[140px] text-right">
                      {delta && (
                        <span className="inline-flex items-center font-mono text-[11px] rounded px-2 py-0.5 bg-[#18181B] border border-[#2A2A2F] text-[#FCA5A5]">
                          {delta}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {matchingFields.length > 0 && (
              <Collapsible open={expandedAll} onOpenChange={setExpandedAll}>
                <CollapsibleTrigger className="mt-3 inline-flex items-center gap-1.5 text-xs text-[#52525B] hover:text-[#A1A1AA] transition-colors duration-150">
                  <ChevronDown
                    className={`h-3 w-3 transition-transform duration-150 ${
                      expandedAll ? "rotate-180" : ""
                    }`}
                  />
                  <span>
                    ✓ {matchingFields.length} other field
                    {matchingFields.length === 1 ? "" : "s"} match (
                    {matchingFields.map((f) => FIELD_LABELS[f]).join(", ")})
                  </span>
                </CollapsibleTrigger>
                <CollapsibleContent className="mt-4">
                  <div className="grid grid-cols-2 gap-4">
                    {(["sourceA", "sourceB"] as const).map((key, i) => {
                      const rec = conflict[key];
                      return (
                        <div
                          key={key}
                          className="rounded-md bg-[#111113] border border-[#1F1F23]"
                        >
                          <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#1F1F23]">
                            <span className="text-xs font-semibold uppercase tracking-wide text-[#A1A1AA]">
                              Source {i === 0 ? "A" : "B"}
                            </span>
                            <span className="font-mono text-[10px] text-[#52525B]">
                              sys.{i === 0 ? "primary" : "ledger"}
                            </span>
                          </div>
                          <dl className="divide-y divide-[#1F1F23]">
                            {FIELD_ORDER.map((f) => {
                              const isConflict = conflict.conflictFields.includes(f);
                              return (
                                <div
                                  key={f}
                                  className={`grid grid-cols-[100px_1fr] gap-3 px-4 py-2.5 ${
                                    isConflict ? "bg-[#450A0A]/25" : ""
                                  }`}
                                >
                                  <dt className="text-xs text-[#52525B] font-medium pt-0.5">
                                    {FIELD_LABELS[f]}
                                  </dt>
                                  <dd
                                    className={`font-mono text-xs leading-relaxed break-words ${
                                      isConflict ? "text-[#FCA5A5]" : "text-[#D4D4D8]"
                                    }`}
                                  >
                                    {rec[f]}
                                  </dd>
                                </div>
                              );
                            })}
                          </dl>
                        </div>
                      );
                    })}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            )}
          </div>
        )}
      </div>

      {/* Document viewer sheet */}
      <Sheet
        open={openDoc !== null}
        onOpenChange={(o) => {
          if (!o) setOpenDoc(null);
        }}
      >
        <SheetContent
          side="right"
          className="w-full sm:max-w-none sm:w-3/4 bg-[#0A0A0B] border-[#1F1F23] text-[#E4E4E7] p-0 flex flex-col"
        >
          {activeDoc && (
            <>
              <SheetHeader className="px-6 py-4 border-b border-[#1F1F23] text-left">
                <div className="text-[10px] uppercase tracking-wide text-[#52525B] mb-1 font-mono">
                  Source {openDoc} · sys.{openDoc === "A" ? "primary" : "ledger"}
                </div>
                <SheetTitle className="font-mono text-sm text-[#E4E4E7]">
                  {activeDoc.filename}
                </SheetTitle>
                <div className="text-xs text-[#52525B]">
                  {activeDoc.pages} pages · uploaded {activeDoc.uploadedAt} · last modified by{" "}
                  {activeDoc.uploadedBy}
                </div>
              </SheetHeader>
              <div className="flex-1 overflow-y-auto px-10 py-8">
                <div className="max-w-3xl mx-auto space-y-4 text-sm leading-relaxed text-[#A1A1AA] font-serif">
                  {activeDoc.body.map((para, i) => {
                    const idx = para.indexOf(activeDoc.highlight);
                    if (idx === -1) {
                      return <p key={i}>{para}</p>;
                    }
                    return (
                      <p key={i}>
                        {para.slice(0, idx)}
                        <mark className="bg-[#450A0A]/30 text-[#FCA5A5] px-1 rounded-sm">
                          {activeDoc.highlight}
                        </mark>
                        {para.slice(idx + activeDoc.highlight.length)}
                      </p>
                    );
                  })}
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>


      {/* Sticky action bar */}
      <div className="shrink-0 border-t border-[#1F1F23] bg-[#0A0A0B]">
        {isHighConfidence ? (
          <div className="p-3">
            <div className="flex gap-2">
              {/* Primary: 60% — monochrome high-contrast (Vercel/Linear) */}
              <button
                onClick={() => onAct(ai.action)}
                className="basis-[60%] h-14 rounded-md bg-[#E4E4E7] text-[#0A0A0B] font-semibold text-base flex items-center justify-center gap-3 hover:bg-[#FAFAFA] transition-colors duration-150 relative"
              >
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${VERDICT_DOT[ai.action]}`} />
                <span>Confirm {VERDICT_LABEL[ai.action]}</span>
                <span className="absolute right-4">
                  <Kbd dark>A</Kbd>
                </span>
              </button>
              {/* Secondary cluster: 40% split equally */}
              <div className="basis-[40%] grid grid-cols-3 gap-2">
                <SecondaryAction
                  label={
                    ai.action === "approve" ? "Override → Reject" : "Override → Approve"
                  }
                  onClick={() =>
                    onAct(ai.action === "approve" ? "reject" : "approve")
                  }
                  kbd={ai.action === "approve" ? "R" : "A"}
                  disabled={ai.action === "approve"}
                />
                <SecondaryAction
                  label="Escalate"
                  onClick={() => onAct("escalate")}
                  kbd="E"
                  hidden={ai.action === "escalate"}
                />
                <SecondaryAction label="Skip" onClick={() => onAct("skip")} kbd="␣" />
              </div>
            </div>
            {showEvidence && reviewedDocs.size > 0 && (
              <div className="mt-2 text-center text-[11px] text-[#52525B]">
                Reviewed evidence from {reviewedDocs.size} source
                {reviewedDocs.size === 1 ? "" : "s"}
              </div>
            )}
          </div>
        ) : (
          // Low-confidence: equal-weight 4-button row
          <div className="grid grid-cols-4 gap-2 p-3">
            <EqualAction
              label="Approve"
              onClick={() => onAct("approve")}
              kbd="A"
              tone="approve"
            />
            <EqualAction
              label="Reject"
              onClick={() => onAct("reject")}
              kbd="R"
              tone="reject"
            />
            <EqualAction
              label="Escalate"
              onClick={() => onAct("escalate")}
              kbd="E"
              tone="escalate"
            />
            <EqualAction label="Skip" onClick={() => onAct("skip")} kbd="␣" tone="ghost" />
          </div>
        )}
      </div>
    </>
  );
}

function SecondaryAction({
  label,
  onClick,
  kbd,
  hidden,
  disabled,
}: {
  label: string;
  onClick: () => void;
  kbd: string;
  hidden?: boolean;
  disabled?: boolean;
}) {
  if (hidden) return <div />;
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="h-14 rounded-md border border-[#2A2A2F] bg-transparent text-[#A1A1AA] font-medium text-sm flex items-center justify-center gap-2 hover:bg-[#18181B] hover:text-[#E4E4E7] transition-colors duration-150 disabled:opacity-30 disabled:hover:bg-transparent px-2"
    >
      <span className="truncate">{label}</span>
      <Kbd>{kbd}</Kbd>
    </button>
  );
}

function EqualAction({
  label,
  onClick,
  kbd,
  tone,
}: {
  label: string;
  onClick: () => void;
  kbd: string;
  tone: "approve" | "reject" | "escalate" | "ghost";
}) {
  const toneCls: Record<typeof tone, string> = {
    approve: "border-[#065F46] text-[#6EE7B7] hover:bg-[#064E3B]/40",
    reject: "border-[#7F1D1D] text-[#FCA5A5] hover:bg-[#450A0A]/40",
    escalate: "border-[#78350F] text-[#FCD34D] hover:bg-[#422006]/40",
    ghost: "border-[#2A2A2F] text-[#A1A1AA] hover:bg-[#18181B] hover:text-[#E4E4E7]",
  };
  return (
    <button
      onClick={onClick}
      className={`h-14 rounded-md border bg-transparent font-medium text-sm flex items-center justify-center gap-2 transition-colors duration-150 ${toneCls[tone]}`}
    >
      <span>{label}</span>
      <Kbd>{kbd}</Kbd>
    </button>
  );
}

function ConfidenceRing({ confidence }: { confidence: number }) {
  const size = 18;
  const stroke = 2;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - confidence);
  const color =
    confidence >= 0.8 ? "#6EE7B7" : confidence >= 0.7 ? "#FCD34D" : "#FCA5A5";
  return (
    <svg width={size} height={size} className="shrink-0 -rotate-90">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        stroke="#1F1F23"
        strokeWidth={stroke}
        fill="none"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        stroke={color}
        strokeWidth={stroke}
        fill="none"
        strokeDasharray={c}
        strokeDashoffset={offset}
        strokeLinecap="round"
      />
    </svg>
  );
}

function EvidenceSection({
  conflict,
  onOpenDoc,
}: {
  conflict: Conflict;
  onOpenDoc: (side: "A" | "B") => void;
}) {
  return (
    <div className="mb-6 space-y-8">
      <div className="text-xs uppercase tracking-wide text-[#52525B]">
        Evidence · review before confirming
      </div>

      {/* 1. Full field comparison */}
      <div>
        <div className="grid grid-cols-[120px_1fr_1fr_auto] items-center gap-4 pb-2 border-b border-[#1F1F23] mb-1">
          <div />
          <div className="font-mono text-[10px] uppercase tracking-wide text-[#52525B]">
            Source A · sys.primary
          </div>
          <div className="font-mono text-[10px] uppercase tracking-wide text-[#52525B]">
            Source B · sys.ledger
          </div>
          <div />
        </div>
        <div className="divide-y divide-[#1F1F23]">
          {FIELD_ORDER.map((f) => {
            const a = conflict.sourceA[f];
            const b = conflict.sourceB[f];
            const isConflict = conflict.conflictFields.includes(f);
            const delta =
              isConflict && f === "amount" ? computeAmountDelta(a, b) : null;
            return (
              <div
                key={f}
                className={`grid grid-cols-[120px_1fr_1fr_auto] items-start gap-4 px-3 py-2.5 -mx-3 ${
                  isConflict ? "bg-[#450A0A]/25 rounded" : ""
                }`}
              >
                <div className="font-mono text-xs uppercase tracking-wide text-[#52525B] pt-0.5">
                  {FIELD_LABELS[f]}
                </div>
                <div
                  className={`font-mono text-sm break-words ${
                    isConflict ? "text-[#FCA5A5]" : "text-[#D4D4D8]"
                  }`}
                >
                  {a}
                </div>
                <div
                  className={`font-mono text-sm break-words ${
                    isConflict ? "text-[#FCA5A5]" : "text-[#D4D4D8]"
                  }`}
                >
                  {b}
                </div>
                <div className="min-w-[110px] text-right">
                  {delta && (
                    <span className="inline-flex items-center font-mono text-[11px] rounded px-2 py-0.5 bg-[#18181B] border border-[#2A2A2F] text-[#FCA5A5]">
                      {delta}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 2. Source documents */}
      {(conflict.sourceA.document || conflict.sourceB.document) && (
        <div>
          <div className="text-xs uppercase tracking-wide text-[#52525B] mb-3">
            Source documents
          </div>
          <div className="grid grid-cols-2 gap-4">
            {(["A", "B"] as const).map((side) => {
              const rec = side === "A" ? conflict.sourceA : conflict.sourceB;
              const doc = rec.document;
              if (!doc) return <div key={side} />;
              return (
                <div
                  key={side}
                  className="rounded-md border border-[#1F1F23] bg-[#111113] p-4 flex flex-col gap-3 hover:border-[#2A2A2F] transition-colors duration-150"
                >
                  <div className="flex items-start gap-3">
                    <div className="h-9 w-9 shrink-0 rounded bg-[#18181B] border border-[#1F1F23] flex items-center justify-center">
                      <FileText className="h-4 w-4 text-[#A1A1AA]" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[10px] uppercase tracking-wide text-[#52525B] font-mono mb-0.5">
                        Source {side} · sys.{side === "A" ? "primary" : "ledger"}
                      </div>
                      <div className="font-mono text-sm text-[#E4E4E7] truncate">
                        {doc.filename}
                      </div>
                      <div className="text-xs text-[#52525B] mt-0.5">
                        {doc.pages} pages · uploaded {doc.uploadedAt} · last modified by{" "}
                        {doc.uploadedBy}
                      </div>
                    </div>
                  </div>
                  <div className="rounded bg-[#0A0A0B] border border-[#1F1F23] px-3 py-2 font-mono text-xs leading-relaxed text-[#A1A1AA]">
                    {(() => {
                      const idx = doc.excerpt.indexOf(doc.highlight);
                      if (idx === -1) return doc.excerpt;
                      return (
                        <>
                          {doc.excerpt.slice(0, idx)}
                          <span className="text-[#FCA5A5] bg-[#450A0A]/30 rounded px-1">
                            {doc.highlight}
                          </span>
                          {doc.excerpt.slice(idx + doc.highlight.length)}
                        </>
                      );
                    })()}
                  </div>
                  <button
                    onClick={() => onOpenDoc(side)}
                    className="self-start inline-flex items-center gap-2 text-xs text-[#A1A1AA] hover:text-[#E4E4E7] transition-colors duration-150"
                  >
                    <span>Open document →</span>
                    <Kbd>{side === "A" ? "1" : "2"}</Kbd>
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 3. Audit trail */}
      {conflict.auditTrail && conflict.auditTrail.length > 0 && (
        <div>
          <div className="text-xs uppercase tracking-wide text-[#52525B] mb-3">
            Audit trail
          </div>
          <ul className="space-y-1.5">
            {conflict.auditTrail.slice(0, 3).map((entry, i) => (
              <li key={i} className="font-mono text-xs text-[#52525B]">
                <span className="text-[#A1A1AA]">{entry.timestamp}</span>
                <span className="text-[#2A2A2F]"> · </span>
                <span className="text-[#93C5FD]">{entry.actor}</span>
                <span className="text-[#2A2A2F]"> · </span>
                <span>{entry.action}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default Index;
