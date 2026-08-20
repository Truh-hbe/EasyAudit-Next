export type HttpResult = Readonly<{
  status: number;
  headers: Readonly<Record<string, string>>;
  body: string;
}>;

const concepts = [
  "Scenario",
  "ReviewPlan",
  "ReviewCase",
  "Finding",
  "ActionItem",
  "CaseMember",
  "FindingParticipant",
  "Activity",
  "Submission",
] as const;

function json(status: number, payload: unknown): HttpResult {
  return {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify(payload),
  };
}

export function route(method: string, url: string): HttpResult {
  if (method === "GET" && url === "/health") {
    return json(200, { status: "ok", stage: "M0" });
  }

  if (method === "GET" && url === "/api/v1/meta/domain-model") {
    return json(200, {
      stage: "M0",
      concepts,
      next: "M1 Identity & Organization and persistence",
    });
  }

  return json(404, {
    error: { code: "NOT_FOUND", message: "Route not found" },
  });
}
