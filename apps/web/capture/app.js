(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var VIEWS = {
    front: {
      title: "Front photo",
      tips: ["Face the camera, standing straight, feet a little apart.", "Arms slightly away from your body (about a hand's width).", "Wear fitted clothes, not loose ones.", "Prop the phone upright or ask someone to hold it level, 2 to 3 metres away. Head and feet must both be in view."],
      path: "M50 14 a8 9 0 1 0 .01 0 M42 30 L28 38 L18 100 M58 30 L72 38 L82 100 M42 30 L40 110 L38 190 M58 30 L60 110 L62 190 M42 110 L58 110"
    },
    side: {
      title: "Side photo",
      tips: ["Turn a quarter turn so the camera sees your side.", "Arms down by your sides, standing straight, looking ahead.", "Same fitted clothes, same distance as the front photo.", "Head and feet must both be in view."],
      path: "M50 14 a8 9 0 1 0 .01 0 M46 30 L44 110 L46 190 M54 30 L56 110 L54 190 M44 60 L58 62 M44 110 L58 108"
    }
  };
  var STEPS = ["consent", "height", "capture", "sending", "result", "error"];
  var state = { heightCm: null, photos: {}, tilt: {}, view: "front", stream: null, facing: "environment",
                tiltNow: null, pendingBlob: null, pendingTilt: null, orientationOn: false };

  function show(step, label) {
    STEPS.forEach(function (s) { $("step-" + s).hidden = s !== step; });
    $("progress").textContent = label || "";
    window.scrollTo(0, 0);
  }

  // ---- consent: nothing touches the camera until this is accepted ----
  $("consent-box").addEventListener("change", function (e) { $("consent-btn").disabled = !e.target.checked; });
  $("consent-btn").addEventListener("click", function () {
    // iOS only grants motion access from a tap, so ask here.
    var D = window.DeviceOrientationEvent;
    if (D && typeof D.requestPermission === "function") {
      D.requestPermission().then(startOrientation, function () {}).catch(function () {});
    } else { startOrientation(); }
    show("height", "Step 1 of 3");
  });

  function startOrientation() {
    if (state.orientationOn || !window.DeviceOrientationEvent) return;
    state.orientationOn = true;
    window.addEventListener("deviceorientation", function (e) {
      state.tiltNow = TF.tiltDegrees(e.beta, e.gamma);
      renderTilt();
    });
  }

  function renderTilt() {
    var el = $("tilt"), t = state.tiltNow;
    if (t === null) { el.textContent = "Tilt sensor not available. Keep the phone upright and level."; el.className = "tilt"; }
    else if (TF.isLevel(t)) { el.textContent = "Phone is level ✓"; el.className = "tilt ok"; }
    else { el.textContent = "Hold the phone upright and level (off by " + Math.round(t) + "°)"; el.className = "tilt bad"; }
    updateShoot();
  }

  // ---- height ----
  document.querySelectorAll("input[name=unit]").forEach(function (r) {
    r.addEventListener("change", function () {
      var ft = r.value === "ftin" && r.checked;
      $("h-cm").hidden = ft; $("h-ftin").hidden = !ft;
    });
  });
  $("height-btn").addEventListener("click", function () {
    var unit = document.querySelector("input[name=unit]:checked").value;
    var res = unit === "cm" ? TF.parseHeight("cm", $("h-cm-input").value) : TF.parseHeight("ftin", $("h-ft").value, $("h-in").value);
    $("height-error").textContent = res.error || "";
    if (res.error) return;
    state.heightCm = res.cm;
    startCapture("front");
  });

  // ---- capture ----
  function startCapture(view) {
    state.view = view; state.pendingBlob = null;
    var v = VIEWS[view];
    $("cap-title").textContent = v.title;
    $("cap-tips").innerHTML = "";
    v.tips.forEach(function (t) { var li = document.createElement("li"); li.textContent = t; $("cap-tips").appendChild(li); });
    $("silhouette").setAttribute("d", v.path);
    $("cap-error").textContent = "";
    showLive();
    show("capture", view === "front" ? "Step 2 of 3" : "Step 3 of 3");
    openCamera();
    renderTilt();
  }

  function showLive() {
    $("cap-error").textContent = "";
    $("preview").hidden = true; $("video").hidden = false;
    $("live-controls").hidden = false; $("review-controls").hidden = true;
    $("inframe-box").checked = false; $("use").disabled = true;
  }

  function openCamera() {
    stopCamera();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return useFallback();
    navigator.mediaDevices.getUserMedia({ video: { facingMode: state.facing, height: { ideal: 1920 } }, audio: false })
      .then(function (s) {
        state.stream = s; $("video").srcObject = s; $("fallback").hidden = true; $("video").hidden = false;
        $("live-controls").hidden = false; updateShoot();
      }, function () { useFallback(); });
  }

  function useFallback() {
    $("video").hidden = true; $("live-controls").hidden = true; $("fallback").hidden = false;
  }

  function stopCamera() {
    if (counting()) { clearInterval(timer.id); timer.id = null; $("count").hidden = true; $("flip").disabled = false; }
    if (state.stream) { state.stream.getTracks().forEach(function (t) { t.stop(); }); state.stream = null; }
  }

  function updateShoot() {
    // Level phone required when the sensor works; without a sensor we allow the shot and note it.
    var ready = !!state.stream && $("video").videoWidth > 0 && (state.tiltNow === null || TF.isLevel(state.tiltNow));
    $("shoot").disabled = counting() ? false : !ready;
  }
  $("video").addEventListener("loadedmetadata", updateShoot);

  $("flip").addEventListener("click", function () {
    state.facing = state.facing === "environment" ? "user" : "environment"; openCamera();
  });

  // ---- self-timer: lets the person step back and pose before the photo is taken ----
  var timer = { id: null, left: 0, ctx: null };

  function beep(freq, ms) {
    try {
      var ctx = timer.ctx, o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = freq; g.gain.value = 0.2; o.connect(g); g.connect(ctx.destination);
      o.start(); o.stop(ctx.currentTime + ms / 1000);
    } catch (e) {}
  }

  function counting() { return timer.id !== null; }

  function cancelCountdown() {
    if (timer.id !== null) { clearInterval(timer.id); timer.id = null; }
    $("count").hidden = true; $("flip").disabled = false;
    $("shoot").textContent = timerDelay() ? "Start timer" : "Take photo";
    updateShoot();
  }

  function timerDelay() { return Number(document.querySelector("input[name=timer]:checked").value); }

  function tick() {
    timer.left -= 1;
    if (timer.left <= 0) { cancelCountdown(); beep(1200, 250); if (navigator.vibrate) navigator.vibrate(200); takePhoto(); return; }
    $("count").textContent = timer.left; beep(timer.left <= 2 ? 900 : 600, 120);
  }

  document.querySelectorAll("input[name=timer]").forEach(function (r) {
    r.addEventListener("change", function () { if (!counting()) cancelCountdown(); });
  });

  $("shoot").addEventListener("click", function () {
    if (counting()) return cancelCountdown();
    var delay = timerDelay();
    if (!delay) return takePhoto();
    try { timer.ctx = timer.ctx || new (window.AudioContext || window.webkitAudioContext)(); timer.ctx.resume(); } catch (e) { timer.ctx = null; }
    timer.left = delay; $("count").textContent = delay; $("count").hidden = false;
    $("flip").disabled = true; $("shoot").textContent = "Cancel"; $("shoot").disabled = false;
    beep(600, 120);
    timer.id = setInterval(tick, 1000);
  });

  function takePhoto() {
    var v = $("video"), size = TF.fitSize(v.videoWidth, v.videoHeight, 1600);
    var c = document.createElement("canvas"); c.width = size.w; c.height = size.h;
    c.getContext("2d").drawImage(v, 0, 0, size.w, size.h);
    var tilt = state.tiltNow;
    c.toBlob(function (blob) { if (blob) review(blob, tilt); }, "image/jpeg", 0.9);
  }

  $("file").addEventListener("change", function (e) {
    var f = e.target.files[0]; if (!f) return;
    review(f, null);
  });

  function review(blob, tilt) {
    state.pendingBlob = blob; state.pendingTilt = tilt;
    var img = $("preview");
    if (img.src) URL.revokeObjectURL(img.src);
    img.src = URL.createObjectURL(blob);
    img.hidden = false; $("video").hidden = true;
    $("live-controls").hidden = true; $("fallback").hidden = true; $("review-controls").hidden = false;
    $("inframe-box").checked = false; $("use").disabled = true;
    $("cap-error").textContent = tilt !== null && !TF.isLevel(tilt) ? "The phone looked tilted when this photo was taken. Retake if the photo looks slanted." : "";
  }
  $("inframe-box").addEventListener("change", function (e) { $("use").disabled = !e.target.checked; });

  $("retake").addEventListener("click", function () {
    state.pendingBlob = null; $("file").value = ""; showLive(); openCamera();
  });

  $("use").addEventListener("click", function () {
    state.photos[state.view] = state.pendingBlob; state.tilt[state.view] = state.pendingTilt;
    $("file").value = "";
    stopCamera();
    if (state.view === "front") startCapture("side"); else submit();
  });

  // ---- submit ----
  function submit() {
    show("sending", "");
    var fd = new FormData();
    fd.append("front", state.photos.front, "front.jpg");
    fd.append("side", state.photos.side, "side.jpg");
    fd.append("height_cm", String(state.heightCm));
    fd.append("consent", "true");
    ["front", "side"].forEach(function (v) { if (state.tilt[v] !== null && state.tilt[v] !== undefined) fd.append(v + "_tilt", String(state.tilt[v])); });
    var ctl = new AbortController(), timer = setTimeout(function () { ctl.abort(); }, 90000);
    fetch("/v1/measurements", { method: "POST", body: fd, signal: ctl.signal })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (body) {
          if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "The server could not process your photos (error " + r.status + ").");
          return body;
        });
      })
      .then(renderResult)
      .catch(function (err) {
        fail(err.name === "AbortError" ? "This took too long. Check your connection and try again." :
             err instanceof TypeError ? "No connection. Check your network and try again." : err.message);
      })
      .then(function () { clearTimeout(timer); });
  }

  function renderResult(sheet) {
    var tb = $("result-body"); tb.innerHTML = "";
    sheet.measurements.forEach(function (m) {
      var tr = document.createElement("tr"), name = document.createElement("td");
      name.textContent = m.name.replace(/_/g, " ");
      var cm = document.createElement("td"); cm.textContent = m.value_cm.toFixed(1);
      var inch = document.createElement("td"); inch.textContent = m.value_in.toFixed(1);
      var conf = document.createElement("td"); conf.className = "conf " + m.confidence_label;
      conf.textContent = m.confidence_label;
      var why = document.createElement("span"); why.className = "reason"; why.textContent = m.reason; conf.appendChild(why);
      [name, cm, inch, conf].forEach(function (td) { tr.appendChild(td); });
      tb.appendChild(tr);
    });
    $("stub-note").hidden = !sheet.stub;
    show("result", "Done");
  }

  function fail(msg) { stopCamera(); $("fatal-msg").textContent = msg; show("error", ""); }

  function reset() {
    state.photos = {}; state.tilt = {}; state.heightCm = null; stopCamera(); show("height", "Step 1 of 3");
  }
  $("retry").addEventListener("click", function () { state.photos.front && state.photos.side ? submit() : reset(); });
  $("again").addEventListener("click", reset);

  show("consent", "");
})();
