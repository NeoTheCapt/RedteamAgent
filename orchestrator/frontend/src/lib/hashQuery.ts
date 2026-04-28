/**
 * Parse / encode a query string for the tail of a hash route.
 *
 * Example hash: "#/projects/1/runs/2/cases?state=finding&method=GET"
 *  path segment:  "/projects/1/runs/2/cases"
 *  query segment: "state=finding&method=GET"
 *
 * Keys with empty values are dropped; keys with `undefined` values are dropped.
 */

export type HashQuery = Record<string, string | undefined>;

export function parseHashQuery(hash: string): { path: string; query: HashQuery } {
  const raw = hash.replace(/^#/, "");
  const qIdx = raw.indexOf("?");
  if (qIdx < 0) return { path: raw, query: {} };
  const path = raw.slice(0, qIdx);
  const search = raw.slice(qIdx + 1);
  const query: HashQuery = {};
  for (const part of search.split("&")) {
    if (!part) continue;
    const eq = part.indexOf("=");
    const k = eq < 0 ? part : part.slice(0, eq);
    const v = eq < 0 ? "" : decodeURIComponent(part.slice(eq + 1));
    if (k) query[decodeURIComponent(k)] = v;
  }
  return { path, query };
}

export function encodeHashQuery(path: string, query: HashQuery): string {
  const pairs: string[] = [];
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === "") continue;
    pairs.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  }
  return pairs.length === 0 ? path : `${path}?${pairs.join("&")}`;
}
