(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var VIEWS = {
    front: {
      title: "Front photo",
      tips: ["Face the camera, standing straight, feet a little apart.", "Arms slightly away from your body (about a hand's width).", "Wear fitted clothes, not loose ones.", "Prop the phone upright and level. Step back only until the banner on the camera turns green (your whole body is in view). Standing further back than that makes the photo less accurate."],
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
                tiltNow: null, pendingBlob: null, pendingTilt: null, orientationOn: false, retake: null, issues: [] };

  var order = { token: new URLSearchParams(location.search).get("order"), info: null, kept: false };

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

  // Phones with an ultra-wide back camera (iPhone 11 and newer) can show a whole body from about half the distance.
  var wide = { id: null, probed: false, active: false };

  function openCamera() {
    stopCamera();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return useFallback();
    var useWide = !!(wide.id && state.facing === "environment" && $("wide-box").checked);
    var video = useWide ? { deviceId: { exact: wide.id }, height: { ideal: 1920 } } : { facingMode: state.facing, height: { ideal: 1920 } };
    navigator.mediaDevices.getUserMedia({ video: video, audio: false })
      .then(function (s) {
        wide.active = useWide;
        state.stream = s; $("video").srcObject = s; $("fallback").hidden = true; $("video").hidden = false;
        // Widest view the camera allows (where the browser supports zoom), so less distance is needed.
        try {
          var track = s.getVideoTracks()[0], cap = track.getCapabilities && track.getCapabilities();
          if (cap && cap.zoom && cap.zoom.min < 1) track.applyConstraints({ advanced: [{ zoom: cap.zoom.min }] }).catch(function () {});
        } catch (e) {}
        $("wide-wrap").hidden = !(wide.id && state.facing === "environment");
        try { $("lens").textContent = "Camera in use: " + (s.getVideoTracks()[0].label || "default"); } catch (e) {}
        $("live-controls").hidden = false; updateShoot();
        startFraming();
        if (!wide.probed) probeWide();
      }, function () {
        if (useWide) { wide.id = null; $("wide-wrap").hidden = true; return openCamera(); }  // wide camera refused: use the normal one
        useFallback();
      });
  }

  // Camera names are only visible after permission is granted, so look for the wide one after the first stream opens.
  function probeWide() {
    wide.probed = true;
    if (!navigator.mediaDevices.enumerateDevices) return;
    navigator.mediaDevices.enumerateDevices().then(function (list) {
      var cams = list.filter(function (d) { return d.kind === "videoinput" && /ultra/i.test(d.label) && !/front|user/i.test(d.label); });
      wide.id = cams.length ? cams[0].deviceId : null;
      if (!wide.id) return;
      $("wide-wrap").hidden = state.facing !== "environment";
      if ($("wide-box").checked && !wide.active && state.facing === "environment" && !counting() && !state.pendingBlob) openCamera();
    }).catch(function () {});
  }
  $("wide-box").addEventListener("change", function () { if (!counting()) openCamera(); });

  function useFallback() {
    $("video").hidden = true; $("live-controls").hidden = true; $("fallback").hidden = false;
  }

  function stopCamera() {
    stopFraming();
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

  // ---- live framing check: tells the person when their whole body is in view, so they don't stand further than needed ----
  var framing = { timer: null, busy: false, off: false };

  function postFrame(blob) {
    var fd = new FormData(); fd.append("frame", blob, "frame.jpg");
    return fetch("/v1/framing", { method: "POST", body: fd }).then(function (r) {
      if (r.status === 503) framing.off = true;  // not available on this server: stay quiet
      if (!r.ok) throw new Error("framing " + r.status);
      return r.json();
    });
  }
  function startFraming() {
    stopFraming();
    if (framing.off) return;
    framing.timer = setInterval(checkFraming, 2000); setTimeout(checkFraming, 500);
  }
  function stopFraming() {
    if (framing.timer) { clearInterval(framing.timer); framing.timer = null; }
    $("framing").hidden = true;
  }
  function checkFraming() {
    var v = $("video");
    if (framing.busy || framing.off || counting() || !state.stream || !v.videoWidth) return;
    framing.busy = true;
    var size = TF.fitSize(v.videoWidth, v.videoHeight, 512), c = document.createElement("canvas");
    c.width = size.w; c.height = size.h; c.getContext("2d").drawImage(v, 0, 0, size.w, size.h);
    c.toBlob(function (blob) {
      if (!blob) { framing.busy = false; return; }
      postFrame(blob).then(function (res) {
        var m = TF.framingMessage(res.status), el = $("framing");
        if (!m || !state.stream) return;
        el.hidden = false; el.className = "framing " + m.level; el.textContent = m.text;
      }).catch(function () {}).then(function () { framing.busy = false; });
    }, "image/jpeg", 0.7);
  }

  function review(blob, tilt) {
    stopFraming();
    var rf = $("review-framing"); rf.hidden = true;
    if (!framing.off) postFrame(blob).then(function (res) {  // check the photo itself too, so a cut-off one is caught before sending
      var m = TF.framingMessage(res.status); if (!m || state.pendingBlob !== blob) return;
      rf.hidden = false; rf.className = "framing " + m.level; rf.textContent = m.level === "warn" ? "This photo: " + m.text + " Retake it." : m.text;
    }).catch(function () {});
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
    if (state.retake) {  // only the rejected photos are retaken
      state.retake = state.retake.filter(function (v) { return v !== state.view; });
      if (state.retake.length) return startRetake(state.retake[0]);
      state.retake = null;
      return submit();
    }
    if (state.view === "front") startCapture("side"); else submit();
  });

  function startRetake(view) {
    startCapture(view);
    $("cap-error").textContent = TF.rejectionText(state.issues, view);
  }

  // ---- submit ----
  function submit() {
    show("sending", "");
    var fd = new FormData();
    fd.append("front", state.photos.front, "front.jpg");
    fd.append("side", state.photos.side, "side.jpg");
    fd.append("height_cm", String(state.heightCm));
    fd.append("consent", "true");
    fd.append("locale", $("lang").value);
    if (order.token) { fd.append("order_token", order.token); fd.append("keep_photos", $("keep-box").checked ? "true" : "false"); }
    ["front", "side"].forEach(function (v) { if (state.tilt[v] !== null && state.tilt[v] !== undefined) fd.append(v + "_tilt", String(state.tilt[v])); });
    var ctl = new AbortController(), timer = setTimeout(function () { ctl.abort(); }, 90000);
    fetch("/v1/measurements", { method: "POST", body: fd, signal: ctl.signal })
      .then(function (r) {
        order.kept = r.headers.get("X-Photos-Kept") === "true";
        return r.json().catch(function () { return {}; }).then(function (body) {
          if (!r.ok && body.detail && body.detail.error === "photo_rejected") {
            var rej = new Error("photo_rejected"); rej.issues = body.detail.issues; throw rej;
          }
          if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "The server could not process your photos (error " + r.status + ").");
          return body;
        });
      })
      .then(renderResult)
      .catch(function (err) {
        if (err.issues) {  // quality gate refused a photo: show the fix and go back to that photo
          state.issues = err.issues; state.retake = TF.rejectionViews(err.issues);
          return startRetake(state.retake[0]);
        }
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
    $("order-extras").hidden = !order.token;
    if (order.token) {
      $("offer-text").hidden = $("fabric-file").parentNode.hidden = !(order.info && order.info.style);
      $("privacy-line").textContent = order.kept ? "Your tailor is keeping your photos (faces blurred) because you chose to." : "Your photos were deleted after processing. Only your measurements were kept.";
      $("delete-btn").hidden = !order.kept;
    }
    show("result", "Done");
  }

  function fail(msg) { stopCamera(); $("fatal-msg").textContent = msg; show("error", ""); }

  function reset() {
    state.photos = {}; state.tilt = {}; state.heightCm = null; stopCamera(); show("height", "Step 1 of 3");
  }
  $("retry").addEventListener("click", function () { state.photos.front && state.photos.side ? submit() : reset(); });
  $("again").addEventListener("click", reset);

  // ---- order link from the tailor ----
  $("fabric-file").addEventListener("change", function (e) {
    var f = e.target.files[0]; if (!f || !state.photos.front || !order.info || !order.info.style) return;
    $("preview-error").textContent = ""; $("preview-wait").hidden = false; $("preview-img").hidden = true; $("preview-note").hidden = true;
    var fd = new FormData();
    fd.append("front", state.photos.front, "front.jpg"); fd.append("fabric", f, "fabric.jpg");
    fd.append("style_id", order.info.style.id); fd.append("consent", "true"); fd.append("order_token", order.token);
    fetch("/v1/previews", { method: "POST", body: fd }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (b) { if (!r.ok) throw new Error(typeof b.detail === "string" ? b.detail : "The preview could not be made. Try again."); return b; });
    }).then(function (b) {
      $("preview-img").src = "data:" + b.media_type + ";base64," + b.image_base64; $("preview-img").hidden = false;
      $("preview-note").hidden = false;
      $("preview-note").textContent = b.mode === "neutral_model" ? "We could not keep your exact shape in the preview, so a neutral model is shown. " + b.label + "." : b.label + ". Sent to your tailor.";
    }).catch(function (err) { $("preview-error").textContent = err instanceof TypeError ? "No connection. Try again." : err.message; })
      .then(function () { $("preview-wait").hidden = true; $("fabric-file").value = ""; });
  });
  $("delete-btn").addEventListener("click", function () {
    fetch("/v1/capture/" + encodeURIComponent(order.token) + "/delete-request", { method: "POST" }).then(function (r) {
      if (!r.ok) throw new Error(); $("delete-msg").textContent = "Done. Your photos and preview have been deleted. Your tailor keeps your measurements."; $("delete-btn").hidden = true; $("privacy-line").textContent = "Your photos are not kept.";
    }).catch(function () { $("delete-msg").textContent = "We could not delete them just now. Please try again."; });
  });

  if (order.token) {
    fetch("/v1/capture/" + encodeURIComponent(order.token)).then(function (r) { if (!r.ok) throw new Error(); return r.json(); }).then(function (info) {
      order.info = info;
      var g = $("greeting"); g.hidden = false;
      g.textContent = "Hi " + info.customer_first_name + ", your tailor asked for these photos" + (info.style ? " for your " + info.style.name + "." : ".");
      $("keep-wrap").hidden = false;
    }).catch(function () {
      order.token = null;
      fail("This link is not valid any more. Please ask your tailor for a new one.");
      $("retry").hidden = true;
    });
  }

  show("consent", "");
})();
