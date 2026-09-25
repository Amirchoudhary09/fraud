"use client";
import type { EvidenceGraph as Graph, GraphNode } from "@/lib/types";

// Column layout: sources | candidates | attributes | target. Readable without a physics engine.
const COLUMN: Record<string, number> = { Source: 0, Candidate: 1, Company: 2, College: 2, Place: 2, Role: 2, Username: 2, Target: 3 };
const COLOR: Record<string, string> = {
  Target: "#e0567a", Candidate: "#4f7cff", Company: "#2fa37a", College: "#c7962b", Place: "#8a6cf0",
  Role: "#1f9bb5", Username: "#d06b2d", Source: "#8a93a3",
};
const W = 960, ROW = 30, PAD = 24;
const X = [110, 360, 620, 870];

function short(s: string, n = 26) { return s.length > n ? s.slice(0, n - 1) + "…" : s; }

export default function EvidenceGraph({ graph }: { graph: Graph }) {
  const cols: GraphNode[][] = [[], [], [], []];
  for (const n of graph.nodes) cols[COLUMN[n.type] ?? 2].push(n);
  const height = PAD * 2 + Math.max(...cols.map((c) => c.length), 1) * ROW;
  const pos = new Map<string, { x: number; y: number }>();
  cols.forEach((col, ci) => {
    const offset = (height - col.length * ROW) / 2;
    col.forEach((n, i) => pos.set(n.id, { x: X[ci], y: offset + i * ROW + ROW / 2 }));
  });

  return (
    <div>
      <svg className="graph-svg" viewBox={`0 0 ${W} ${height}`} role="img" aria-label="Evidence graph">
        {graph.edges.map((e, i) => {
          const a = pos.get(e.source), b = pos.get(e.target);
          if (!a || !b) return null;
          const input = e.type.startsWith("INPUT_");
          return (
            <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={input ? COLOR.Target : "#8a93a3"}
              strokeOpacity={input ? 0.5 : 0.35} strokeDasharray={input ? "4 3" : undefined}>
              <title>{e.type}{e.sources.length ? ` (${e.sources.length} source${e.sources.length > 1 ? "s" : ""})` : ""}</title>
            </line>
          );
        })}
        {graph.nodes.map((n) => {
          const p = pos.get(n.id)!;
          const left = COLUMN[n.type] === 0;
          return (
            <g key={n.id}>
              <circle cx={p.x} cy={p.y} r={n.type === "Candidate" || n.type === "Target" ? 8 : 6} fill={COLOR[n.type] ?? "#888"} />
              <text x={left ? p.x - 12 : p.x + 12} y={p.y + 3} textAnchor={left ? "end" : "start"}>
                {short(n.label)}{n.score != null ? ` (${n.score})` : ""}
              </text>
              <title>{n.type}: {n.label}{n.url ? `\n${n.url}` : ""}</title>
            </g>
          );
        })}
      </svg>
      <div className="legend">
        {Object.entries(COLOR).map(([k, c]) => <span key={k} style={{ ["--c" as string]: c }}>{k}</span>)}
        <span className="muted">dashed = what you searched for</span>
      </div>
    </div>
  );
}
