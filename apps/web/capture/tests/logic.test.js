const test = require("node:test");
const assert = require("node:assert");
const { parseHeight, tiltDegrees, isLevel, fitSize, rejectionViews, rejectionText, framingMessage } = require("../logic.js");

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

test("framing: fine distances are green, cut-off bodies are warnings", () => {
  assert.strictEqual(framingMessage("ok").level, "ok");
  assert.ok(framingMessage("too_small").text.includes("step closer"));
  ["head_cut", "feet_cut", "both_cut", "sides_cut"].forEach((s) => assert.strictEqual(framingMessage(s).level, "warn"));
  assert.strictEqual(framingMessage("no_person").level, "info");
});
test("framing: unknown status gives no message", () => assert.strictEqual(framingMessage("???"), null));

const { cameraErrorText, canRetryCamera } = require("../logic.js");
test("blocked camera on Android explains the overlay fix", () => {
  const t = cameraErrorText("NotAllowedError", true);
  assert.ok(/bubbles/.test(t) && /Try the camera again/.test(t));
  assert.ok(!/bubbles/.test(cameraErrorText("NotAllowedError", false)));
});
test("camera busy and no camera get their own messages", () => {
  assert.ok(/Another app is using the camera/.test(cameraErrorText("NotReadableError")));
  assert.ok(/couldn't find a camera/.test(cameraErrorText("NotFoundError")));
  assert.ok(/camera app/.test(cameraErrorText(undefined)));
});
test("retry is offered unless there is no camera at all", () => {
  assert.ok(canRetryCamera("NotAllowedError") && canRetryCamera("NotReadableError"));
  assert.ok(!canRetryCamera("NotFoundError") && !canRetryCamera(undefined));
});
