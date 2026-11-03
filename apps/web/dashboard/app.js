(function () {
  "use strict";
  var app = document.getElementById("app"), nav = document.getElementById("nav");
  var timer = null, styles = [];

  // ---- tiny DOM helper: everything from the server goes in as text, never as HTML ----
  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (k === "class") el.className = v; else if (k === "text") el.textContent = v;
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, ""); else if (v !== false && v !== null && v !== undefined) el.setAttribute(k, v);
    });
    function add(c) {
      if (c === null || c === undefined || c === false) return;
      if (Array.isArray(c)) return c.forEach(add);  // allow lists of children, e.g. from .map()
      el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    for (var i = 2; i < arguments.length; i++) add(arguments[i]);
    return el;
  }
  function mount() { app.textContent = ""; for (var i = 0; i < arguments.length; i++) app.appendChild(arguments[i]); window.scrollTo(0, 0); }

  function api(method, path, body) {
    var opts = { method: method, credentials: "same-origin", headers: {} };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (r.status === 401 && path.indexOf("/auth/login") < 0) { showLogin(); throw new Error("login"); }
        if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong (" + r.status + ").");
        return data;
      });
    });
  }
  function stopTimer() { if (timer) { clearInterval(timer); timer = null; } }
  function fmtDate(s) { return s ? new Date(s).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : ""; }
  function pretty(n) { return n.replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }

  // ---- login ----
  function showLogin(msg) {
    stopTimer(); nav.hidden = true;
    var err = h("p", { class: "error", role: "alert", text: msg || "" });
    var user = h("input", { id: "user", autocomplete: "username", required: true }), pass = h("input", { id: "pass", type: "password", autocomplete: "current-password", required: true });
    var form = h("form", { class: "card", onsubmit: function (e) {
      e.preventDefault(); err.textContent = "";
      api("POST", "/v1/auth/login", { username: user.value, password: pass.value })
        .then(function () { return start(); }).catch(function (x) { err.textContent = x.message; });
    } }, h("h1", { text: "Tailor login" }), h("label", { for: "user", text: "Username" }), user, h("label", { for: "pass", text: "Password" }), pass, err, h("button", { type: "submit", text: "Log in" }));
    mount(form); user.focus();
  }

  // ---- order list ----
  function showList() {
    stopTimer(); nav.hidden = false;
    var body = h("tbody"), empty = h("p", { class: "muted", text: "No orders yet. Add your first customer." });
    function load() {
      api("GET", "/v1/orders").then(function (orders) {
        body.textContent = ""; empty.hidden = orders.length > 0;
        orders.forEach(function (o) {
          var badges = h("span", null, h("span", { class: "badge " + o.status, text: o.status === "new" ? "Waiting for photos" : "Measured" }));
          if (o.carried_from) badges.appendChild(h("span", { class: "badge repeat", text: " Repeat order" }));
          if (o.low_confidence) badges.appendChild(h("span", { class: "badge warn", text: " " + o.low_confidence + " to check" }));
          body.appendChild(h("tr", { class: "click", tabindex: 0, onclick: function () { showOrder(o.id); } },
            h("td", null, h("strong", { text: o.customer.name }), h("div", { class: "muted", text: o.customer.phone || "" })),
            h("td", { class: "hide-sm", text: o.style ? o.style.name : "-" }), h("td", null, badges),
            h("td", { class: "hide-sm", text: o.yardage || "-" }), h("td", { class: "hide-sm muted", text: fmtDate(o.measured_at || o.created_at) })));
        });
      }).catch(function () {});
    }
    mount(h("div", { class: "row", style: "align-items:center" }, h("h1", { text: "Orders" }), h("div", { style: "text-align:right" }, h("button", { id: "new-btn", text: "+ New customer", onclick: showNew }))),
      h("div", { class: "card" }, h("table", null, h("thead", null, h("tr", null, h("th", { text: "Customer" }), h("th", { class: "hide-sm", text: "Style" }), h("th", { text: "Status" }), h("th", { class: "hide-sm", text: "Fabric" }), h("th", { class: "hide-sm", text: "Updated" }))), body), empty));
    load(); timer = setInterval(load, 10000);  // a customer finishing shows up on its own
  }

  // ---- new customer ----
  function styleSelect(selected, withNone) {
    var s = h("select", { id: "style" });
    if (withNone) s.appendChild(h("option", { value: "", text: "Not chosen yet" }));
    styles.forEach(function (st) { s.appendChild(h("option", { value: st.id, text: st.name })); });
    s.value = selected || ""; return s;
  }
  function showNew() {
    stopTimer();
    var err = h("p", { class: "error", role: "alert" });
    var name = h("input", { id: "cname", required: true, maxlength: 120 }), phone = h("input", { id: "cphone", type: "tel", maxlength: 40 }), st = styleSelect("senator", true);
    var width = h("select", { id: "cwidth" }, [36, 45, 60].map(function (w) { return h("option", { value: w, text: w + " inches" }); })); width.value = "45";
    mount(h("form", { class: "card", onsubmit: function (e) {
      e.preventDefault(); err.textContent = "";
      api("POST", "/v1/orders", { customer_name: name.value, phone: phone.value, style_id: st.value || null, fabric_width_in: Number(width.value) })
        .then(function (o) { showOrder(o.id); }).catch(function (x) { err.textContent = x.message; });
    } }, h("h1", { text: "New customer" }), h("label", { for: "cname", text: "Name" }), name, h("label", { for: "cphone", text: "Phone (optional)" }), phone,
      h("div", { class: "row" }, h("div", null, h("label", { for: "style", text: "Style" }), st), h("div", null, h("label", { for: "cwidth", text: "Fabric width" }), width)),
      err, h("div", { class: "actions" }, h("button", { type: "submit", text: "Create and get link" }), h("button", { type: "button", class: "ghost", text: "Cancel", onclick: showList })))); name.focus();
  }

  // ---- order detail ----
  function showOrder(id) {
    stopTimer(); nav.hidden = false;
    api("GET", "/v1/orders/" + id).then(function (o) { renderOrder(o); }).catch(function (e) { if (e.message !== "login") { mount(h("p", { class: "error", text: e.message }), h("button", { class: "ghost", text: "Back", onclick: showList })); } });
  }

  function renderOrder(o) {
    var out = [];
    out.push(h("div", { class: "row", style: "align-items:center" },
      h("div", null, h("h1", { text: o.customer.name }), h("div", { class: "muted", text: (o.customer.phone || "No phone") + " · " + (o.measured_at ? "measured " + fmtDate(o.measured_at) : "created " + fmtDate(o.created_at)) })),
      h("div", { style: "text-align:right" }, o.can_repeat ? h("button", { id: "repeat-btn", text: "New order for " + o.customer.name.split(" ")[0], onclick: function () {
        api("POST", "/v1/orders/" + o.id + "/repeat", {}).then(renderOrder).catch(function (e) { alert(e.message); });
      } }) : null, " ", h("button", { class: "ghost", text: "← All orders", onclick: showList }))));
    if (o.carried_from) out.push(h("div", { class: "tapefirst", id: "carried-note" }, h("strong", { text: "Repeat order: numbers from " + fmtDate(o.carried_from.measured_at) + "." }),
      h("div", { class: "muted", text: "Nothing was re-measured. If " + o.customer.name.split(" ")[0] + "'s body may have changed, send the link below and ask for new photos; this page will then show what changed." })));

    var link = location.origin + o.capture_url;
    var linkInput = h("input", { id: "caplink", readonly: true, value: link });
    var copied = h("span", { class: "muted", id: "copied" });
    out.push(h("div", { class: "card" }, h("h2", { text: o.status === "new" ? "Send this link to " + o.customer.name.split(" ")[0] : o.carried_from ? "Ask for new photos (optional)" : "Customer link" }),
      h("div", { class: "linkbox" }, linkInput, h("button", { id: "copy-btn", text: "Copy", onclick: function () { linkInput.select(); (navigator.clipboard ? navigator.clipboard.writeText(link) : Promise.reject()).then(function () { copied.textContent = "Copied"; }, function () { copied.textContent = "Press copy on the selected text"; }); } }), copied),
      whatsappRow(o, link),
      o.status === "new" ? h("p", { class: "muted", text: "They open it on their phone, take two photos and enter their height. This page updates when they finish." }) : null));

    if (o.status === "new") { out.push(h("p", { class: "muted", id: "waiting", text: "Waiting for photos…" })); timer = setInterval(function () { api("GET", "/v1/orders/" + o.id).then(function (n) { if (n.status !== "new") { stopTimer(); renderOrder(n); } }).catch(function () {}); }, 5000); }
    else { out.push(measurementsCard(o)); if (o.changes && o.changes.items.length) out.push(changesCard(o)); }

    out.push(styleCard(o));
    if (o.finished && o.finished.length) out.push(finishedCard(o));
    if (o.has_preview) out.push(h("div", { class: "card" }, h("h2", { text: "Style preview" }), h("img", { class: "preview", id: "preview-img", alt: "Style preview", src: "/v1/orders/" + o.id + "/preview.jpg?t=" + Date.now() }), h("p", { class: "muted", text: "Preview, not the final garment." })));
    out.push(notesCard(o), privacyCard(o));
    mount.apply(null, out);
  }

  // WhatsApp: "Open WhatsApp" needs nothing but the number (the tailor taps Send); "Send automatically" needs the Cloud API.
  function whatsappRow(o, link) {
    var wa = o.whatsapp, msg = h("span", { class: "muted", id: "wa-msg" }), row = h("div", { class: "actions", id: "wa-row" });
    if (wa.phone_digits) {
      var text = "Hi " + o.customer.name.split(" ")[0] + ", please take two quick photos so I can get your measurements" + (o.style ? " for your " + o.style.name : "") + ". Open this link on your phone: " + link;
      row.appendChild(h("a", { class: "btn", id: "wa-open", target: "_blank", rel: "noopener", href: "https://wa.me/" + wa.phone_digits + "?text=" + encodeURIComponent(text), text: "Open WhatsApp with this message" }));
      if (wa.auto) row.appendChild(h("button", { id: "wa-send", class: "ghost", text: "Send automatically", onclick: function () {
        msg.textContent = "Sending…";
        api("POST", "/v1/orders/" + o.id + "/send-whatsapp").then(function (r) { msg.textContent = r.sent === "template" ? "Sent as a template message." : "Sent."; }).catch(function (e) { msg.textContent = e.message; });
      } }));
      row.appendChild(msg);
    }
    var phone = h("input", { id: "phone-input", type: "tel", value: o.customer.phone || "", placeholder: "0803 000 0000", maxlength: 40, "aria-label": "Customer phone" });
    var perr = h("span", { class: "error", id: "phone-error" });
    return h("div", null, row,
      wa.phone_digits ? null : h("p", { class: "muted", id: "wa-missing", text: "Add a phone number to send this on WhatsApp. Start with the country code (+234…) or with 0 for a Nigerian number." }),
      h("div", { class: "linkbox", style: "margin-top:8px" }, phone, h("button", { id: "phone-save", class: "ghost", text: "Save number", onclick: function () {
        api("PATCH", "/v1/orders/" + o.id, { phone: phone.value }).then(renderOrder).catch(function (e) { perr.textContent = e.message; });
      } })), perr);
  }

  function measurementsCard(o) {
    var dirty = {}, save = h("button", { id: "save-edits", text: "Save changes", disabled: true }), tapeNow = o.tape_first || [];
    var body = h("tbody");
    o.measurements.forEach(function (m) {
      var input = h("input", { type: "number", step: "0.1", min: "5", max: "300", value: m.value_cm, "aria-label": pretty(m.name) + " in cm", "data-name": m.name });
      input.addEventListener("input", function () {
        var v = parseFloat(input.value);
        if (isFinite(v) && Math.abs(v - m.value_cm) > 1e-9) dirty[m.name] = v; else delete dirty[m.name];
        save.disabled = !Object.keys(dirty).length;
      });
      var cells = [h("td", null, h("strong", { text: pretty(m.name) })), h("td", { class: "muted hide-sm", text: m.edited ? m.original_cm.toFixed(1) : "" }),
        h("td", { class: m.edited ? "edited" : "" }, input), h("td", { class: "hide-sm", text: m.value_in.toFixed(1) }),
        h("td", null, h("span", { class: "conf-" + m.confidence_label, text: m.confidence_label }), h("div", { class: "why", text: m.reason })),
        h("td", null, m.edited ? h("button", { class: "ghost", style: "padding:4px 8px;font-size:.8rem", text: "Undo edit", onclick: function () { var e = {}; e[m.name] = null; saveEdits(o.id, e); } }) : null)];
      if (!m.edited && !o.carried_from) cells[5] = h("td", null, h("button", { class: "ghost", style: "padding:4px 8px;font-size:.8rem", "data-agree": m.name, text: "Tape agrees", onclick: function () { var e = {}; e[m.name] = m.original_cm; saveEdits(o.id, e); } }));
      body.appendChild(h("tr", { "data-row": m.name, class: tapeNow.indexOf(m.name) >= 0 ? "tape-now" : "" }, cells));
    });
    save.addEventListener("click", function () { saveEdits(o.id, dirty); });
    return h("div", { class: "card" }, h("h2", { text: "Measurements" }),
      o.stub ? h("p", { class: "notice error", text: "Demo values: the measurement engine was not connected, so these numbers are not real." }) : null,
      tapeNow.length ? h("div", { class: "tapefirst", id: "tape-first" }, h("strong", { text: "Tape these first: " + tapeNow.map(pretty).join(", ") }),
        h("div", { class: "muted", text: "These are the numbers we are least sure of. The rest are likely close enough to start cutting." })) : null,
      o.carried_from ? h("p", { class: "muted", text: "Edit any value if you re-measured. Edits on a repeat order are not used to track accuracy, because we did not estimate these numbers for this order." }) : h("p", { class: "muted", text: "Type what your tape says, or press \"Tape agrees\" if our number is right. Your tape values are saved to track how accurate we are for you (see Accuracy), and they never change the original estimate." }),
      h("table", null, h("thead", null, h("tr", null, h("th", { text: "Measurement" }), h("th", { class: "hide-sm", text: "Original cm" }), h("th", { text: "cm" }), h("th", { class: "hide-sm", text: "in" }), h("th", { text: "Confidence" }), h("th"))), body),
      h("p", { class: "error", id: "edit-error", role: "alert" }), h("div", { class: "actions" }, save));
  }
  function changesCard(o) {
    var c = o.changes, rows = c.items.map(function (i) {
      return h("tr", { "data-change": i.name }, h("td", null, h("strong", { text: pretty(i.name) })), h("td", { text: i.previous_cm.toFixed(1) + " cm" }), h("td", { text: i.current_cm.toFixed(1) + " cm" }),
        h("td", { class: i.delta_cm > 0 ? "up" : "down", text: (i.delta_cm > 0 ? "+" : "") + i.delta_cm.toFixed(1) + " cm" }), h("td", { class: "muted", text: i.both_checked ? "both taped" : "estimates" }));
    });
    return h("div", { class: "card", id: "changes-card" }, h("h2", { text: "What changed since " + fmtDate(c.previous_date) }),
      h("table", null, h("thead", null, h("tr", null, ["Measurement", "Before", "Now", "Change", "Based on"].map(function (t) { return h("th", { text: t }); }))), h("tbody", null, rows)),
      h("p", { class: "muted", text: "Only changes bigger than the usual error are listed (about 1.5 cm if both were taped, otherwise 3 cm or more). Check these with a tape before cutting." }));
  }

  function saveEdits(id, edits) {
    api("PUT", "/v1/orders/" + id + "/measurements", { edits: edits }).then(renderOrder).catch(function (e) { var el = document.getElementById("edit-error"); if (el) el.textContent = e.message; });
  }

  function styleCard(o) {
    var st = styleSelect(o.style && o.style.id, true), width = h("select", { id: "fwidth" }, [36, 45, 60].map(function (w) { return h("option", { value: w, text: w + " inches" }); })); width.value = String(o.fabric_width_in);
    var A = o.allowances, fields = [["seam_in", "Seam (in)"], ["hem_in", "Hem (in)"], ["shrink_pct", "Shrinkage %"], ["extra_pct", "Extra %"], ["pattern_match_pct", "Print matching %"]];
    var inputs = {}; var allowRow = h("div", { class: "row" });
    fields.forEach(function (f) { inputs[f[0]] = h("input", { type: "number", step: "0.25", min: "0", id: "al-" + f[0], value: A[f[0]] }); allowRow.appendChild(h("div", null, h("label", { for: "al-" + f[0], text: f[1] }), inputs[f[0]])); });
    var easeLabels = { chest: "Chest ease (in)", hip: "Trouser hip ease (in)", thigh: "Trouser thigh ease (in)" }, easeInputs = {}, easeRow = null;
    if (o.ease) {
      easeRow = h("div", { class: "row", id: "ease-row" });
      Object.keys(o.ease.defaults).forEach(function (part) {
        easeInputs[part] = h("input", { type: "number", step: "0.5", min: "0", id: "ease-" + part, value: o.ease.values[part] });
        easeRow.appendChild(h("div", null, h("label", { for: "ease-" + part, text: easeLabels[part] }), easeInputs[part], h("div", { class: "muted", text: "style default " + o.ease.defaults[part] })));
      });
    }
    var err = h("p", { class: "error", id: "style-error", role: "alert" });
    var y = o.yardage, result = null;
    if (y && y.error) result = h("p", { class: "error", text: y.error });
    else if (y) result = h("div", null, h("div", { class: "big", id: "yardage", text: y.display }), h("div", { class: "muted", text: "of " + y.fabric_width_in + "-inch fabric · all widths: " + Object.keys(y.yards_by_width).map(function (w) { return w + "\": " + y.yards_by_width[w] + " yd"; }).join(", ") }),
      y.notes.length ? h("ul", null, y.notes.map(function (n) { return h("li", { class: "muted", text: n }); })) : null, h("p", { class: "muted", text: y.basis }));
    else result = h("p", { class: "muted", text: "Choose a style to see the yardage." });
    return h("div", { class: "card" }, h("h2", { text: "Style and fabric" }),
      h("div", { class: "row" }, h("div", null, h("label", { for: "style", text: "Style" }), st), h("div", null, h("label", { for: "fwidth", text: "Fabric width" }), width)),
      easeRow ? h("div", null, h("h3", { text: "Ease: how loose the garment is" }), easeRow) : null,
      h("details", null, h("summary", { text: "Fabric allowances (you can change these)" }), allowRow),
      h("div", { class: "actions" }, h("button", { id: "update-style", text: "Update", onclick: function () {
        var al = {}; fields.forEach(function (f) { al[f[0]] = Number(inputs[f[0]].value); });
        // Only pin an ease value when it differs from the style's default, so a later style change picks up the new default.
        Object.keys(easeInputs).forEach(function (part) { var v = Number(easeInputs[part].value); al[part + "_ease_in"] = v === o.ease.defaults[part] ? null : v; });
        api("PATCH", "/v1/orders/" + o.id, { style_id: st.value, fabric_width_in: Number(width.value), allowances: al }).then(renderOrder).catch(function (e) { err.textContent = e.message; });
      } })), err, result,
      o.measurements.length ? h("div", { class: "actions" }, h("a", { class: "btn", id: "pdf-link", target: "_blank", rel: "noopener", href: "/v1/orders/" + o.id + "/cutting-sheet.pdf", text: "Print cutting sheet (PDF)" })) : null);
  }

  function finishedCard(o) {
    var rows = o.finished.map(function (r) {
      return h("tr", { "data-part": r.part }, h("td", null, h("strong", { text: r.part })), h("td", { text: r.inches.toFixed(1) + " in" }), h("td", { class: "hide-sm", text: r.cm.toFixed(1) + " cm" }),
        h("td", { class: "muted", text: r.how }), h("td", null, h("span", { class: "conf-" + r.confidence_label, text: r.confidence_label })));
    });
    return h("div", { class: "card", id: "finished-card" }, h("h2", { text: "Finished garment: " + o.style.name }),
      h("table", null, h("thead", null, h("tr", null, h("th", { text: "Part" }), h("th", { text: "Finished" }), h("th", { class: "hide-sm", text: "" }), h("th", { text: "How" }), h("th", { text: "Confidence" }))), h("tbody", null, rows)),
      h("p", { class: "muted", text: "Body measurement plus the ease for this style. A low-confidence row depends on a body number we are unsure about: tape it first." }));
  }

  function notesCard(o) {
    var t = h("textarea", { id: "notes", rows: 3, maxlength: 2000 }); t.value = o.notes; var msg = h("span", { class: "muted" });
    return h("div", { class: "card" }, h("h2", { text: "Your notes" }), t, h("div", { class: "actions" }, h("button", { class: "ghost", text: "Save notes", onclick: function () { api("PATCH", "/v1/orders/" + o.id, { notes: t.value }).then(function () { msg.textContent = "Saved"; }); } }), msg));
  }

  function privacyCard(o) {
    var status = o.photos_kept ? "Face-blurred photos are kept because the customer chose to keep them."
      : o.photos_deleted_at ? "Photos deleted " + fmtDate(o.photos_deleted_at) + (o.deletion_requested_at ? " at the customer's request." : ".")
      : "No photos are stored. They were deleted right after processing.";
    var actions = h("div", { class: "actions" });
    if (o.photos_kept || o.has_preview) actions.appendChild(h("button", { class: "ghost", id: "del-photos", text: "Delete photos and preview", onclick: function () { if (confirm("Delete the stored photos and preview? The measurements stay.")) api("DELETE", "/v1/orders/" + o.id + "/photos").then(function () { showOrder(o.id); }); } }));
    actions.appendChild(h("button", { class: "danger", id: "del-order", text: "Delete this order", onclick: function () { if (confirm("Delete " + o.customer.name + " and everything stored about this order?")) api("DELETE", "/v1/orders/" + o.id).then(showList); } }));
    return h("div", { class: "card" }, h("h2", { text: "Privacy" }), h("p", { class: "muted", id: "privacy-status", text: status }), actions);
  }

  // ---- accuracy: how far our estimates were from this tailor's tape ----
  function showAccuracy() {
    stopTimer(); nav.hidden = false;
    api("GET", "/v1/accuracy").then(function (a) {
      var rows = a.measurements.map(function (m) {
        var max = Math.max.apply(null, m.series_cm.concat([1]));
        var spark = h("div", { class: "spark", "aria-label": "Gap per order, oldest first" }, m.series_cm.slice(-12).map(function (e) { return h("i", { style: "height:" + Math.max(2, Math.round(36 * e / max)) + "px", title: e + " cm" }); }));
        var trend = m.first_mae_cm !== null ? (m.first_mae_cm + " → " + m.recent_mae_cm + " cm") : "needs 4 orders";
        return h("tr", { "data-acc": m.name }, h("td", null, h("strong", { text: pretty(m.name) })), h("td", { text: String(m.n) }),
          h("td", { text: m.mae_cm + " cm" }), h("td", { text: (m.bias_cm > 0 ? "+" : "") + m.bias_cm + " cm" }), h("td", { class: m.recent_mae_cm !== null && m.recent_mae_cm < m.first_mae_cm ? "good" : "", text: trend }),
          h("td", { text: m.offset_cm ? (m.offset_cm > 0 ? "+" : "") + m.offset_cm + " cm applied" : "not yet" }), h("td", null, spark));
      });
      mount(h("div", { class: "row", style: "align-items:center" }, h("h1", { text: "Accuracy" }), h("div", { style: "text-align:right" }, h("button", { class: "ghost", text: "← All orders", onclick: showList }))),
        h("div", { class: "card" }, h("p", { class: "muted", id: "acc-intro", text: a.orders ? "Based on " + a.orders + " order" + (a.orders === 1 ? "" : "s") + " where you entered a tape value. Gap = how far our estimate was from your tape. Bias is positive when we read too big."
            : "No tape values yet. Open a measured order, type what your tape says (or press \"Tape agrees\"), and this page fills in." }),
          a.measurements.length ? h("table", null, h("thead", null, h("tr", null, ["Measurement", "Checked", "Average gap", "Bias", "First → latest orders", "Learned offset", "Gap per order"].map(function (t) { return h("th", { text: t }); }))), h("tbody", null, rows)) : null,
          h("p", { class: "muted", text: "A learned offset is only applied to new sheets once a measurement has " + a.min_orders + " orders with a steady one-sided bias. Older sheets are never changed. Until then this page only reports." })));
    }).catch(function () {});
  }

  document.getElementById("acc-btn").addEventListener("click", showAccuracy);
  document.getElementById("home-btn").addEventListener("click", showList);
  document.getElementById("logout-btn").addEventListener("click", function () { api("POST", "/v1/auth/logout").then(function () { showLogin(); }); });

  function start() {
    return fetch("/v1/styles").then(function (r) { return r.json(); }).then(function (s) { styles = s; return api("GET", "/v1/auth/me"); }).then(function (me) {
      if (!me.configured) return mount(h("div", { class: "card" }, h("h1", { text: "Dashboard not set up" }), h("p", { text: "Set TAILOR_USERNAME and TAILOR_PASSWORD on the server, then restart it." })));
      if (me.logged_in) showList(); else showLogin();
    });
  }
  start();
})();
