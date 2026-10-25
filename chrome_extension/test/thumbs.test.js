// cd chrome_extension && node --test
const test = require("node:test");
const assert = require("node:assert/strict");
const { videoIdFromHref, badgeState } = require("../thumbs.js");

test("videoIdFromHref: watch, shorts e URL absoluta", () => {
  assert.equal(videoIdFromHref("/watch?v=LKo0rQ9Befw"), "LKo0rQ9Befw");
  assert.equal(videoIdFromHref("/watch?v=LKo0rQ9Befw&list=PL123&index=2&t=30s"), "LKo0rQ9Befw");
  assert.equal(videoIdFromHref("/shorts/pmjQ8FjUXls"), "pmjQ8FjUXls");
  assert.equal(videoIdFromHref("https://www.youtube.com/watch?v=pmjQ8FjUXls"), "pmjQ8FjUXls");
});

test("videoIdFromHref: o que não é vídeo", () => {
  assert.equal(videoIdFromHref(null), null);
  assert.equal(videoIdFromHref("/playlist?list=PL123"), null);
  assert.equal(videoIdFromHref("/watch?list=PL123"), null);
  assert.equal(videoIdFromHref("/@canal"), null);
  assert.equal(videoIdFromHref("/watch?v=<script>"), null);
});

test("badgeState: três estados", () => {
  assert.equal(badgeState(null).kind, "none");
  assert.equal(badgeState({ done: 0, total: 48 }).kind, "none");
  const p = badgeState({ done: 22, total: 56 });
  assert.equal(p.kind, "partial");
  assert.ok(Math.abs(p.pct - 22 / 56) < 1e-9);
  assert.equal(p.title, "subrim: 22 de 56 frases traduzidas");
  for (const st of [{ done: 47, total: 48 }, { done: 55, total: 56 }, { done: 56, total: 56 }]) {
    assert.equal(badgeState(st).kind, "full", JSON.stringify(st));
    assert.equal(badgeState(st).pct, 1);
  }
  assert.equal(badgeState({ done: 1, total: 2 }).kind, "partial");
  assert.equal(badgeState({ done: 90, total: 100 }).kind, "partial");
  assert.equal(badgeState({ done: 95, total: 100 }).kind, "full");
});
