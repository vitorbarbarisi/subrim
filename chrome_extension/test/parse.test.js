// cd chrome_extension && node --test   (ou: node --test chrome_extension/test/parse.test.js)
const test = require("node:test");
const assert = require("node:assert/strict");
const {
  parsePinyinTranslations,
  displayPairs,
  displayItems,
  json3ToCues,
  findActiveCue,
} = require("../render.js");

test("parser: string no formato do base.txt", () => {
  assert.deepEqual(parsePinyinTranslations('["三 (sān): três", "號 (hào): número", "碼頭 (mǎ tóu): cais"]'), [
    ["三", "sān", "três"],
    ["號", "hào", "número"],
    ["碼頭", "mǎ tóu", "cais"],
  ]);
});

test("parser: lista vinda do servidor", () => {
  assert.deepEqual(parsePinyinTranslations(["我們 (wǒ men): nós", "去 (qù) :  ir, partir "]), [
    ["我們", "wǒ men", "nós"],
    ["去", "qù", "ir, partir"],
  ]);
});

test("parser: item fora do formato vira só hanzi", () => {
  assert.deepEqual(parsePinyinTranslations(["的", "好 sem parênteses", "(x): y"]), [
    ["的", "", ""],
    ["好", "", ""],
  ]);
});

test("parser: entrada inválida", () => {
  assert.deepEqual(parsePinyinTranslations("não é lista"), []);
  assert.deepEqual(parsePinyinTranslations(null), []);
  assert.deepEqual(parsePinyinTranslations("[]"), []);
});

test("dominadas perdem pinyin/tradução mas continuam tokenizando", () => {
  const pairs = [["我們", "wǒ men", "nós"], ["去", "qù", "ir"]];
  assert.deepEqual(displayPairs(pairs, new Set(["我們"])), [["我們", "", ""], ["去", "qù", "ir"]]);
  assert.deepEqual(displayPairs(pairs, new Set()), pairs);
});

test("casamento: termo mais longo vence", () => {
  const glossary = [["碼", "mǎ", "código"], ["頭", "tóu", "cabeça"], ["碼頭", "mǎ tóu", "cais"], ["三", "sān", "três"]];
  assert.deepEqual(displayItems("三號碼頭", glossary), [
    ["三", "sān", "três"],
    ["號", "", ""],
    ["碼頭", "mǎ tóu", "cais"],
  ]);
});

test("casamento: remove espaços e pontuação como _display_items", () => {
  const glossary = [["你好", "nǐ hǎo", "olá"]];
  assert.deepEqual(displayItems(" 你 好.《》（）\"　", glossary), [["你好", "nǐ hǎo", "olá"]]);
  // vírgula chinesa não é removida (igual ao Python)
  assert.deepEqual(displayItems("你好，", glossary), [["你好", "nǐ hǎo", "olá"], ["，", "", ""]]);
});

test("casamento: empate de tamanho respeita a ordem do glossário", () => {
  const glossary = [["一個", "yí ge", "um"], ["一個", "yī gè", "um (outro)"]];
  assert.deepEqual(displayItems("一個", glossary), [["一個", "yí ge", "um"]]);
});

test("casamento: caractere fora do BMP conta como um só", () => {
  assert.deepEqual(displayItems("𠮷好", [["好", "hǎo", "bom"]]), [["𠮷", "", ""], ["好", "hǎo", "bom"]]);
});

test("json3 -> cues, cortando sobreposição e ignorando eventos vazios", () => {
  const json = {
    events: [
      { tStartMs: 0, dDurationMs: 5000, segs: [{ utf8: "你好" }] },
      { tStartMs: 1000, dDurationMs: 100, aAppend: 1, segs: [{ utf8: "\n" }] },
      { tStartMs: 2000, dDurationMs: 2000, segs: [{ utf8: "我們" }, { utf8: "\n去" }] },
      { tStartMs: 9000 },
    ],
  };
  assert.deepEqual(json3ToCues(JSON.stringify(json)), [
    { start: 0, end: 2, zh: "你好" },
    { start: 2, end: 4, zh: "我們去" },
  ]);
});

test("busca binária da cue ativa", () => {
  const cues = [
    { start: 0, end: 2 },
    { start: 2, end: 4 },
    { start: 6, end: 8 },
  ];
  assert.equal(findActiveCue(cues, -1), -1);
  assert.equal(findActiveCue(cues, 0), 0);
  assert.equal(findActiveCue(cues, 1.99), 0);
  assert.equal(findActiveCue(cues, 2), 1);
  assert.equal(findActiveCue(cues, 5), -1);
  assert.equal(findActiveCue(cues, 7), 2);
  assert.equal(findActiveCue(cues, 8), -1);
  assert.equal(findActiveCue([], 1), -1);
});
