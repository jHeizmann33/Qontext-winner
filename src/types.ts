export type SourceRecord = {
  id: string;
  source: string;
  sourceLabel: string;
  timestamp: string;
  attributes: Record<string, string>;
};

export type AttributeValue = {
  value: string;
  source: string;
  sourceLabel: string;
  timestamp: string;
};

export type ResolvedAttribute = {
  values: AttributeValue[];
  picked: AttributeValue | null;
  conflict: boolean;
};

export type Cluster = {
  id: string;
  records: SourceRecord[];
  attributes: Record<string, ResolvedAttribute>;
  matchScore: number;
  matchReasons: string[];
  status: "auto-resolved" | "needs-review" | "singleton";
};
