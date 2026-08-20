import assert from "node:assert/strict";
import test from "node:test";

import { route } from "../src/app.ts";

test("health endpoint reports M0 readiness", () => {
  const result = route("GET", "/health");
  assert.equal(result.status, 200);
  assert.deepEqual(JSON.parse(result.body), { status: "ok", stage: "M0" });
});

test("domain metadata exposes the nine frozen concepts", () => {
  const result = route("GET", "/api/v1/meta/domain-model");
  const body = JSON.parse(result.body);

  assert.equal(result.status, 200);
  assert.equal(body.concepts.length, 9);
  assert.ok(body.concepts.includes("ReviewCase"));
  assert.ok(body.concepts.includes("Submission"));
});

test("unknown endpoint uses a stable error envelope", () => {
  const result = route("GET", "/missing");
  assert.equal(result.status, 404);
  assert.equal(JSON.parse(result.body).error.code, "NOT_FOUND");
});
