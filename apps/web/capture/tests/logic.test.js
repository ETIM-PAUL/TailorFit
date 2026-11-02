const test = require("node:test");
const assert = require("node:assert");
const { parseHeight, tiltDegrees, isLevel, fitSize, rejectionViews, rejectionText } = require("../logic.js");

test("cm height", () => assert.deepStrictEqual(parseHeight("cm", "170"), { cm: 170 }));
test("feet and inches", () => assert.deepStrictEqual(parseHeight("ftin", "5", "7"), { cm: 170.2 }));
test("feet only", () => assert.deepStrictEqual(parseHeight("ftin", "6", ""), { cm: 182.9 }));
test("blank rejected", () => assert.ok(parseHeight("cm", "").error));
test("too short rejected", () => assert.ok(parseHeight("cm", "60").error));
test("too tall rejected", () => assert.ok(parseHeight("ftin", "8", "0").error));
test("non-number rejected", () => assert.ok(parseHeight("cm", "abc").error));
test("negative inches rejected", () => assert.ok(parseHeight("ftin", "5", "-3").error));

test("upright phone is level", () => {
  assert.strictEqual(tiltDegrees(90, 0), 0);
  assert.ok(isLevel(tiltDegrees(92, 2)));
});
test("tilted phone is not level", () => {
  assert.ok(!isLevel(tiltDegrees(75, 0)));
  assert.ok(!isLevel(tiltDegrees(90, 12)));
});
test("no sensor gives null and not level", () => {
  assert.strictEqual(tiltDegrees(null, null), null);
  assert.ok(!isLevel(null));
});

test("fitSize shrinks the long side", () => assert.deepStrictEqual(fitSize(3000, 4000, 1600), { w: 1200, h: 1600 }));
test("fitSize never enlarges", () => assert.deepStrictEqual(fitSize(800, 600, 1600), { w: 800, h: 600 }));

const issues = [
  { view: "side", code: "posture", message: "Stand straight." },
  { view: "front", code: "lighting", message: "Too dim." },
  { view: "front", code: "occlusion", message: "Something is blocking you." },
];
test("rejected views come back front first, without duplicates", () => assert.deepStrictEqual(rejectionViews(issues), ["front", "side"]));
test("only the failing view is listed", () => assert.deepStrictEqual(rejectionViews([issues[0]]), ["side"]));
test("no issues, no views", () => assert.deepStrictEqual(rejectionViews(undefined), []));
test("messages for one view are joined", () => assert.strictEqual(rejectionText(issues, "front"), "Too dim. Something is blocking you."));
