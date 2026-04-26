import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowRight, ChevronDown, ChevronRight, History } from "lucide-react";
import { CONFLICTS, QUEUE_STATS, type ConflictItem, type Verdict } from "@/lib/review-data";
import { AvatarChip, Breadcrumb, DSButton, Kbd, MonoBadge, SeverityBadge } from "@/components/ds";

const VERDICT_COLOR: Record<Verdict, string> = {
  Reject: "text-coral",
  Accept: "text-mint",
  Escalate: "text-amber",
};

/** Render a quote string with `{hl}…{/hl}` markers as highlight pills. */
function HighlightedQuote({ text }: { text: string }) {
  const parts = useMemo(() => {
    const out: { kind: "text" | "hl"; value: string }[] = [];
    const re = /\{hl\}([\s\S]*?)\{\/hl\}/g;
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) out.push({ kind: "text", value: text.slice(last, m.index) });
      out.push({ kind: "hl", value: m[1] });
      last = re.lastIndex;
    }
    if (last < text.length) out.push({ kind: "text", value: text.slice(last) });
    return out;
  }, [text]);
  return (
    <span className="text-meta text-ink-muted leading-relaxed">
      {parts.map((p, i) =>
        p.kind === "hl" ? (
          <span key={i} className="highlight-pill">{p.value}</span>
        ) : (
          <span key={i}>{p.value}</span>
        )
      )}
    </span>
  );
}

export default function Review() {
  const navigate = useNavigate();

  const [selectedId, setSelectedId] = useState<string>(CONFLICTS[0].id);
  const [reviewedCount, setReviewedCount] = useState<number>(QUEUE_STATS.reviewed);
  const [confirmedIds, setConfirmedIds] = useState<Set<string>>(new Set());
  const [showMatching, setShowMatching] = useState<boolean>(false);

  const selectedIndex = CONFLICTS.findIndex((c) => c.id === selectedId);
  const item = CONFLICTS[selectedIndex] ?? CONFLICTS[0];

  const navigatingRef = useRef(false);

  const handleSkip = () => {
    if (navigatingRef.current) return;
    toast("Skipped");
    const next = (selectedIndex + 1) % CONFLICTS.length;
    setSelectedId(CONFLICTS[next].id);
    setShowMatching(false);
  };

  const handleConfirm = () => {
    if (navigatingRef.current) return;
    navigatingRef.current = true;
    toast(`Verdict confirmed: ${item.verdict}`);
    setReviewedCount((c) => c + 1);
    setConfirmedIds((s) => {
      const next = new Set(s);
      next.add(item.id);
      return next;
    });
    setTimeout(() => {
      navigate("/lens", {
        state: {
          conflictId: item.id,
          verdict: item.verdict,
          confidence: item.confidence,
          focusId: item.lensFocusId,
          timestamp: Date.now(),
        },
      });
    }, 600);
  };

  // Keyboard shortcuts — ignore if focus is on an input/textarea
  useEffect(() => {
    const isTyping = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null;
      if (!tgt) return false;
      const tag = tgt.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tgt.isContentEditable;
    };
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e)) return;
      if (e.key === "a" || e.key === "A") {
        e.preventDefault();
        handleConfirm();
      } else if (e.code === "Space" || e.key === " ") {
        e.preventDefault();
        handleSkip();
      } else if (e.key === "j" || e.key === "J") {
        e.preventDefault();
        const next = (selectedIndex + 1) % CONFLICTS.length;
        setSelectedId(CONFLICTS[next].id);
        setShowMatching(false);
      } else if (e.key === "k" || e.key === "K") {
        e.preventDefault();
        const prev = (selectedIndex - 1 + CONFLICTS.length) % CONFLICTS.length;
        setSelectedId(CONFLICTS[prev].id);
        setShowMatching(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedIndex, item]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-bg text-ink">
      {/* ---------------- HEADER ---------------- */}
      <header className="shrink-0 border-b border-hairline bg-bg relative">
        <div className="flex items-center px-5 py-3">
          {/* Left */}
          <div className="flex items-center gap-3 flex-1">
            <span className="inline-flex items-center justify-center w-3 h-3 rounded-full bg-coral/30 border border-coral/60" />
            <Breadcrumb segments={["qontext", "review", "conflicts"]} />
            <span className="ml-3 text-ink-faint text-meta hidden md:inline">Open sidebar <Kbd>Ctrl B</Kbd></span>
          </div>

          {/* Center */}
          <div className="text-center">
            <div className="text-meta text-ink">{reviewedCount} / {QUEUE_STATS.total} reviewed</div>
            <div className="text-micro text-ink-faint mt-0.5">blocking {QUEUE_STATS.blockingWorkflows} active workflows</div>
          </div>

          {/* Right */}
          <div className="flex items-center gap-3 flex-1 justify-end">
            <div className="flex items-center gap-1 surface-card px-1 py-1">
              <button className="px-3 py-1 text-meta text-ink bg-surface-2 rounded-sm">⊞ Review</button>
              <button
                className="px-3 py-1 text-meta text-ink-muted hover:text-ink rounded-sm"
                onClick={() =>
                  toast("Confirm a verdict to open the Lens", { description: "Press A on any conflict" })
                }
              >
                ◎ Lens
              </button>
            </div>
            <AvatarChip initials="JM" />
          </div>
        </div>
      </header>

      {/* ---------------- BODY ---------------- */}
      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <aside className="w-[300px] shrink-0 flex flex-col border-r border-hairline bg-bg">
          <div className="px-5 py-4 border-b border-hairline shrink-0">
            <div className="flex items-baseline justify-between">
              <span className="text-micro text-ink-faint">Queue</span>
              <span className="text-meta text-ink-muted">{QUEUE_STATS.open} open</span>
            </div>
            <div className="text-micro text-ink-faint mt-1.5 normal-case tracking-normal">
              Avg resolution time: {QUEUE_STATS.avgResolutionSeconds}s · saving {QUEUE_STATS.agentHoursSavedToday} agent-hours today
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {CONFLICTS.map((c) => {
              const isActive = c.id === item.id;
              const isConfirmed = confirmedIds.has(c.id);
              return (
                <button
                  key={c.id}
                  onClick={() => {
                    setSelectedId(c.id);
                    setShowMatching(false);
                  }}
                  className={[
                    "w-full text-left px-5 py-4 border-b border-hairline transition-colors",
                    isActive
                      ? "bg-surface border-l-2 border-l-coral pl-[18px]"
                      : "hover:bg-surface",
                  ].join(" ")}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-meta text-ink">{c.id}</span>
                    <SeverityBadge sev={c.severity} />
                  </div>
                  <div className="mt-2 text-meta text-ink leading-snug line-clamp-2 font-medium">
                    {c.title}
                  </div>
                  <div className="mt-1 text-meta text-ink-muted">
                    {c.parties[0]} ⇌ {c.parties[1]}
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 text-micro text-ink-faint normal-case tracking-normal">
                      <span
                        className={[
                          "w-1.5 h-1.5 rounded-full",
                          c.pausedAgentsCount > 0 ? "bg-amber" : "bg-hairline",
                        ].join(" ")}
                      />
                      {c.pausedAgentsCount} agents paused
                    </span>
                    <span className="text-micro text-ink-faint normal-case tracking-normal">
                      {isConfirmed ? <span className="text-mint">✓ reviewed</span> : c.ageLabel}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        {/* Detail pane */}
        <main className="flex-1 min-w-0 overflow-y-auto px-12 py-8 space-y-10">
          {/* Header row */}
          <div className="flex items-start justify-between gap-6">
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-3">
                <span className="text-meta text-ink-muted">{item.id}</span>
                <SeverityBadge sev={item.severity} />
              </div>
              <h1 className="text-h1 text-ink">
                {item.parties[0]} <span className="text-ink-faint mx-1">⇌</span> {item.parties[1]}
              </h1>
            </div>
            <div className="surface-card px-3 py-1.5 text-meta text-ink-muted shrink-0">
              {item.similarStat}
            </div>
          </div>

          {/* Paused agents */}
          <section>
            <div className="text-micro text-ink-faint">PAUSED AGENTS · WAITING FOR RESOLUTION</div>
            <div className="mt-3 space-y-1">
              {item.pausedAgents.length === 0 ? (
                <div className="text-meta text-ink-faint">No agents currently paused on this conflict.</div>
              ) : (
                item.pausedAgents.map((a) => (
                  <div key={a.id} className="flex items-center justify-between py-1">
                    <div className="flex items-center gap-3">
                      <span className="w-1.5 h-1.5 rounded-full bg-amber" />
                      <span className="text-meta text-ink">{a.id}</span>
                      <span className="text-meta text-ink-muted">{a.task}</span>
                    </div>
                    <span className="text-micro text-ink-faint normal-case tracking-normal">
                      paused {a.pausedFor}
                    </span>
                  </div>
                ))
              )}
            </div>
            <div className="mt-3 text-meta text-ink-muted">{item.unblockSummary}</div>
          </section>

          {/* AI Verdict */}
          <section>
            <div className="text-micro text-ink-faint">
              AI VERDICT · {Math.round(item.confidence * 100)}% CONFIDENCE
            </div>
            <h2 className={`text-verdict mt-2 ${VERDICT_COLOR[item.verdict]}`}>{item.verdict}</h2>
            <p className="text-body text-ink-muted max-w-2xl mt-3">{item.rationale}</p>
          </section>

          {/* Conflict fields */}
          <section>
            <div className="text-micro text-ink-faint">CONFLICT</div>
            <div className="mt-4 space-y-3">
              {item.conflicts.map((f) => (
                <div key={f.label} className="surface-nested p-5">
                  <div className="text-micro text-ink-faint">{f.label}</div>
                  <div className="grid grid-cols-2 gap-8 mt-3">
                    <div>
                      <div className="text-micro text-ink-faint normal-case tracking-normal">Source A</div>
                      <div className={`text-body mt-1 ${item.severity === "HIGH" ? "text-coral" : "text-ink"}`}>
                        {f.sourceA.value}
                      </div>
                    </div>
                    <div>
                      <div className="text-micro text-ink-faint normal-case tracking-normal">Source B</div>
                      <div className={`text-body mt-1 ${item.severity === "HIGH" ? "text-coral" : "text-ink"}`}>
                        {f.sourceB.value}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <button
              onClick={() => setShowMatching((v) => !v)}
              className="mt-3 inline-flex items-center gap-1.5 text-meta text-ink-muted hover:text-ink"
            >
              {showMatching ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              {item.collapsedMatchCount} other fields match
            </button>

            {showMatching && (
              <ul className="mt-3 ml-5 text-meta text-ink-faint space-y-1">
                {Array.from({ length: item.collapsedMatchCount }).map((_, i) => (
                  <li key={i}>· field-{i + 1}: matched across both sources</li>
                ))}
              </ul>
            )}
          </section>

          {/* Evidence */}
          <section>
            <div className="text-micro text-ink-faint">EVIDENCE</div>
            <div className="grid grid-cols-2 gap-4 mt-4">
              {item.evidence.map((doc) => (
                <div key={doc.filename} className="surface-nested p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-micro text-ink-faint">SOURCE {doc.side}</span>
                    <span className="text-meta text-ink-muted">{doc.party}</span>
                  </div>
                  <div className="text-meta text-ink mt-2">{doc.filename}</div>
                  <div className="text-micro text-ink-faint normal-case tracking-normal mt-1">
                    {doc.pages}pp · {doc.date} · {doc.uploader}
                  </div>
                  <div className="surface-card p-3 mt-3">
                    <HighlightedQuote text={doc.quote} />
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Audit trail */}
          <section>
            <div className="text-micro text-ink-faint inline-flex items-center gap-1.5">
              <History className="w-3 h-3" /> AUDIT TRAIL
            </div>
            <div className="surface-nested p-5 mt-3">
              <div className="grid grid-cols-[auto_auto_1fr] gap-x-6 gap-y-1.5">
                {item.audit.map((e, i) => (
                  <div key={i} className="contents">
                    <span className="text-meta text-ink-muted">{e.ts}</span>
                    <span className="text-meta text-ink">{e.actor}</span>
                    <span className="text-meta text-ink-muted">{e.action}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* Bottom padding so footer doesn't crowd content */}
          <div className="h-4" />
        </main>
      </div>

      {/* ---------------- FOOTER ---------------- */}
      <footer className="shrink-0 border-t border-hairline bg-bg px-5 py-3 flex items-center justify-between">
        <div className="flex items-center gap-5 text-meta text-ink-faint">
          <span className="inline-flex items-center gap-2"><Kbd>A</Kbd> confirm</span>
          <span>·</span>
          <span className="inline-flex items-center gap-2"><Kbd>_</Kbd> skip</span>
          <span>·</span>
          <span className="inline-flex items-center gap-2"><Kbd>J/K</Kbd> navigate</span>
        </div>
        <div className="flex items-center gap-3">
          <DSButton variant="secondary" onClick={handleSkip}>Skip</DSButton>
          <DSButton variant="primary" onClick={handleConfirm}>
            Confirm {item.verdict} <ArrowRight className="w-3.5 h-3.5" />
          </DSButton>
        </div>
      </footer>
    </div>
  );
}
