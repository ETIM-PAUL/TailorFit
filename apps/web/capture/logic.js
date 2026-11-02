/* Pure helpers for the capture page. Loaded as window.TF in the browser, required in Node tests. */
(function (root) {
  var MIN_CM = 100, MAX_CM = 230, LEVEL_DEGREES = 5;

  // unit: "cm" (a = cm) or "ftin" (a = feet, b = inches). Returns {cm} or {error}.
  function parseHeight(unit, a, b) {
    var cm;
    if (unit === "cm") {
      cm = Number(a);
    } else {
      var ft = Number(a), inch = Number(b || 0);
      if (!isFinite(ft) || !isFinite(inch) || ft < 0 || inch < 0) return { error: "Enter your height in feet and inches." };
      cm = (ft * 12 + inch) * 2.54;
    }
    if (a === "" || a === null || !isFinite(cm) || cm <= 0) return { error: "Enter your height." };
    cm = Math.round(cm * 10) / 10;
    if (cm < MIN_CM || cm > MAX_CM) return { error: "Height must be between " + MIN_CM + " and " + MAX_CM + " cm (3 ft 4 in to 7 ft 7 in)." };
    return { cm: cm };
  }

  // Phone held upright in portrait reads beta = 90, gamma = 0. Returns total tilt in degrees.
  function tiltDegrees(beta, gamma) {
    if (beta === null || gamma === null || beta === undefined || gamma === undefined) return null;
    return Math.round(Math.hypot(beta - 90, gamma) * 10) / 10;
  }

  function isLevel(tilt) { return tilt !== null && tilt <= LEVEL_DEGREES; }

  // Shrink to fit max px on the long side, never enlarge. Keeps uploads small on low-end phones.
  function fitSize(w, h, max) {
    var s = Math.min(1, max / Math.max(w, h));
    return { w: Math.round(w * s), h: Math.round(h * s) };
  }

  var api = { parseHeight: parseHeight, tiltDegrees: tiltDegrees, isLevel: isLevel, fitSize: fitSize, LEVEL_DEGREES: LEVEL_DEGREES };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.TF = api;
})(typeof window !== "undefined" ? window : this);
