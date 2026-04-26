/**
 * React Query hooks for the conflict queue.
 *
 * Falls back to the bundled mocks when:
 *   - VITE_USE_MOCKS=true is set (explicit dev opt-in), or
 *   - the backend request fails (so the UI still renders during demos).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listConflicts,
  resolveConflict,
  USE_MOCKS,
  type BackendConflict,
} from "./api";
import {
  adaptBackendConflict,
  decisionToBackendWinner,
} from "./conflict-adapter";
import { CONFLICTS, type Conflict, type Decision } from "./qontext-data";

const CONFLICTS_KEY = ["conflicts", "pending_review"] as const;

async function fetchConflictList(): Promise<Conflict[]> {
  if (USE_MOCKS) return CONFLICTS;
  try {
    const res = await listConflicts("pending_review");
    return res.conflicts.map((raw: BackendConflict, i: number) =>
      adaptBackendConflict(raw, i),
    );
  } catch (err) {
    console.warn("[qontext] /conflicts request failed, falling back to mocks", err);
    return CONFLICTS;
  }
}

export function useConflictsQuery() {
  return useQuery({
    queryKey: CONFLICTS_KEY,
    queryFn: fetchConflictList,
    // Conflicts evolve slowly; no aggressive refetch needed.
    staleTime: 30_000,
  });
}

export function useResolveConflictMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: {
      conflict: Conflict;
      decision: Decision | "skip";
      reason?: string;
    }) => {
      // skip / escalate stay client-side for now (no backend slot)
      if (vars.decision === "skip" || vars.decision === "escalate") {
        return { local: true } as const;
      }
      const winner = decisionToBackendWinner(vars.decision);
      if (winner === null || vars.conflict.backendIndex === undefined) {
        return { local: true } as const;
      }
      await resolveConflict(
        vars.conflict.backendIndex,
        winner,
        vars.reason ?? `UI decision: ${vars.decision}`,
      );
      return { local: false } as const;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: CONFLICTS_KEY });
    },
  });
}
