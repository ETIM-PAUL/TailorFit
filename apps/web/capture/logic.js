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

  // issues: [{view, code, message}] from a photo_rejected response. Front is retaken first.
  function rejectionViews(issues) {
    var seen = {}, out = [];
    (issues || []).forEach(function (i) { seen[i.view] = true; });
    ["front", "side"].forEach(function (v) { if (seen[v]) out.push(v); });
    return out;
  }

  function rejectionText(issues, view) {
    return (issues || []).filter(function (i) { return i.view === view; })
      .map(function (i) { return i.message; }).join(" ");
  }

  // Messages for the live "is your whole body in view?" check.
  var FRAMING = {
    ok: ["✓ Whole body in view. This distance is fine.", "ok"],
    too_small: ["✓ Whole body in view. You can step closer.", "ok"],
    head_cut: ["Your head is cut off. Step back a little.", "warn"],
    feet_cut: ["Your feet are cut off. Step back a little.", "warn"],
    both_cut: ["Head and feet are cut off. Step back.", "warn"],
    sides_cut: ["Your body touches the side of the frame. Move to the middle.", "warn"],
    no_person: ["Stand in front of the camera so we can see you.", "info"]
  };
  function framingMessage(status) { var m = FRAMING[status]; return m ? { text: m[0], level: m[1] } : null; }

  var api = { framingMessage: framingMessage, rejectionViews: rejectionViews, rejectionText: rejectionText, parseHeight: parseHeight, tiltDegrees: tiltDegrees, isLevel: isLevel, fitSize: fitSize, LEVEL_DEGREES: LEVEL_DEGREES };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.TF = api;
})(typeof window !== "undefined" ? window : this);
