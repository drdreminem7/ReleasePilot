import assert from "node:assert/strict";
import test from "node:test";
import { statusLabel } from "./contract.js";

test("unknown status is explicit", () => {
  assert.equal(statusLabel("unknown"), "Lab status unknown");
});

