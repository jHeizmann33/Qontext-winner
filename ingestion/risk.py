"""
risk.py — Risk-based decision framework for the LLM resolver.

The simple "act if confidence >= 0.85" policy treats every action as having
the same downside. That's wrong: removing a wrongly-added `same_as` edge is
trivially reversible, but merging two nodes is destructive — once the alias
is gone, its edges are rewired and its provenance fused, you can't unbake
that without restoring from a snapshot.

This module computes, for every (LLM decision, graph context) pair:

    error_probability  = how likely the LLM is wrong, given confidence
                         and risk modifiers (small model, large cluster,
                         identifier conflicts, ...)
    cost_of_error      = how bad it would be if the action turned out wrong,
                         given the action's reversibility
    risk_score         = error_probability × cost_of_error  (lower = safer)

Decision policy: act autonomously only when risk_score is below a configurable
threshold; otherwise escalate to human review with the assessment attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Cost model — what each action would cost us if it turned out wrong
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ActionCost:
    """The downside of taking an action that later proves wrong.

    `base_cost` is on a 0-100 scale; multipliers stack on top.
    """
    base_cost: float
    reversibility: str         # "trivial" | "easy" | "medium" | "hard"
    description: str


ACTION_COSTS: dict[str, ActionCost] = {
    "remove_same_as_edges": ActionCost(
        base_cost=15,
        reversibility="trivial",
        description=(
            "Remove false-positive same_as edges between two nodes. If wrong, "
            "we lose a real cross-source link until someone notices and the "
            "next pipeline run re-detects it. No data is destroyed."
        ),
    ),
    "upgrade_to_auto_linked": ActionCost(
        base_cost=40,
        reversibility="medium",
        description=(
            "Promote a `same_as` edge from `needs_review` to `auto_linked`. "
            "If wrong, downstream queries will treat two distinct entities as "
            "linked. Reversible by downgrading status, but downstream "
            "consumers may have cached the link."
        ),
    ),
    "merge_nodes": ActionCost(
        base_cost=90,
        reversibility="hard",
        description=(
            "Collapse two same-type nodes into one canonical node: properties "
            "combined, edges rewired, alias node deleted. Reversal requires "
            "snapshot restore or manual reconstruction. The most destructive "
            "action the resolver can take."
        ),
    ),
    "no_action": ActionCost(
        base_cost=0,
        reversibility="trivial",
        description="No autonomous mutation; conflict stays in queue.",
    ),

    # Actions for employee_name_inconsistency conflicts
    "mark_alias": ActionCost(
        base_cost=10,
        reversibility="trivial",
        description=(
            "Record the foreign signature as an `aliases` property on the "
            "Employee node. If wrong, just remove from the list — no data "
            "destroyed."
        ),
    ),
    "mark_shared_mailbox": ActionCost(
        base_cost=25,
        reversibility="easy",
        description=(
            "Set `is_shared_mailbox=True` on the Employee node. Downstream "
            "queries treat this emp_id as a team mailbox, not a person. "
            "Reversible by clearing the flag, but downstream may have "
            "already adjusted reports."
        ),
    ),
    "flag_email_reassignment": ActionCost(
        base_cost=50,
        reversibility="medium",
        description=(
            "Mark the affected emails as `_sender_assignment_disputed=True` "
            "and record the suggested correct sender. Does NOT actually "
            "rewire the sent_email edges (too risky autonomous). A human "
            "or a follow-up job applies the rewire after review."
        ),
    ),
}


def derive_action(decision: str, same_type: bool = True) -> str:
    """Map the LLM's verdict + cluster shape to the concrete action we'd take.

    Handles both entity_match_review decisions and employee_name_inconsistency
    decisions in the same dispatch.
    """
    # entity_match_review verdicts
    if decision == "different":
        return "remove_same_as_edges"
    if decision == "same_entity":
        return "merge_nodes" if same_type else "upgrade_to_auto_linked"
    # employee_name_inconsistency verdicts
    if decision == "alias":
        return "mark_alias"
    if decision == "shared_mailbox":
        return "mark_shared_mailbox"
    if decision == "wrong_assignment":
        return "flag_email_reassignment"
    # uncertain (or any unknown decision)
    return "no_action"


# ---------------------------------------------------------------------------
# Risk modifiers — context that makes a wrong call more or less likely
# ---------------------------------------------------------------------------

# Small models hallucinate more on borderline calls.
SMALL_MODEL_PATTERNS = ("3b", "1b", "0.5b", "phi3", "gemma2:2b")


def _is_small_model(model_name: str) -> bool:
    n = (model_name or "").lower()
    return any(p in n for p in SMALL_MODEL_PATTERNS)


@dataclass
class RiskAssessment:
    decision: str                                  # the LLM's verdict
    confidence: float                              # the LLM's stated confidence
    action: str                                    # what we'd do if we acted
    reversibility: str                             # how recoverable that action is
    base_cost: float                               # 0-100 baseline for the action
    cost_modifiers: list[tuple[str, float]] = field(default_factory=list)
    final_cost: float = 0.0                        # base × modifiers
    error_probability: float = 0.0                 # 1 - confidence (with floor)
    risk_score: float = 0.0                        # error_prob × final_cost
    risk_threshold: float = 5.0                    # below this we act autonomously
    recommended: str = "escalate"                  # "auto_act" | "escalate"
    rationale: str = ""                            # short human-readable summary

    def as_dict(self) -> dict:
        return {
            "decision": self.decision,
            "confidence": round(self.confidence, 3),
            "action": self.action,
            "reversibility": self.reversibility,
            "base_cost": round(self.base_cost, 2),
            "cost_modifiers": [
                {"reason": r, "multiplier": round(m, 2)} for r, m in self.cost_modifiers
            ],
            "final_cost": round(self.final_cost, 2),
            "error_probability": round(self.error_probability, 3),
            "risk_score": round(self.risk_score, 2),
            "risk_threshold": self.risk_threshold,
            "recommended": self.recommended,
            "rationale": self.rationale,
        }


def assess_risk(
    decision: str,
    confidence: float,
    same_type: bool,
    cluster_size: int = 2,
    has_identifier_conflict: bool = False,
    model: str = "",
    risk_threshold: float = 5.0,
) -> RiskAssessment:
    """Compute the per-conflict risk assessment.

    Returns a `RiskAssessment` with `recommended` set to either `"auto_act"`
    (safe to execute autonomously) or `"escalate"` (route to human queue).
    """
    action = derive_action(decision, same_type)
    cost_def = ACTION_COSTS[action]

    modifiers: list[tuple[str, float]] = []

    if cluster_size > 3:
        modifiers.append((f"Cluster has {cluster_size} members (>3)", 1.3))
    if has_identifier_conflict and decision == "same_entity":
        # The rules layer already flagged the identifier disagreement; the LLM
        # is overriding it. Down-weight that.
        modifiers.append(("LLM overriding identifier disagreement", 1.6))
    if _is_small_model(model):
        modifiers.append((f"Small LLM ({model}) — known to hallucinate corroborations", 1.25))
    if decision == "uncertain":
        modifiers.append(("LLM itself reported uncertainty", 2.0))

    final_cost = cost_def.base_cost
    for _, mult in modifiers:
        final_cost *= mult

    error_prob = max(0.0, min(1.0, 1.0 - confidence))
    risk = error_prob * final_cost

    recommended = "auto_act" if (action != "no_action" and risk < risk_threshold) else "escalate"

    if action == "no_action":
        rationale = "Decision is uncertain; no autonomous action defined."
    elif recommended == "auto_act":
        rationale = (
            f"risk={risk:.2f} < threshold={risk_threshold}. "
            f"Action `{action}` is {cost_def.reversibility} to reverse, "
            f"and at confidence={confidence:.2f} the expected damage is acceptable."
        )
    else:
        rationale = (
            f"risk={risk:.2f} >= threshold={risk_threshold}. "
            f"Action `{action}` would be {cost_def.reversibility} to undo if wrong; "
            f"with error_probability={error_prob:.2f} and cost={final_cost:.1f} "
            f"the expected damage exceeds the autonomous budget. Escalating."
        )

    return RiskAssessment(
        decision=decision,
        confidence=confidence,
        action=action,
        reversibility=cost_def.reversibility,
        base_cost=cost_def.base_cost,
        cost_modifiers=modifiers,
        final_cost=round(final_cost, 2),
        error_probability=round(error_prob, 3),
        risk_score=round(risk, 2),
        risk_threshold=risk_threshold,
        recommended=recommended,
        rationale=rationale,
    )
