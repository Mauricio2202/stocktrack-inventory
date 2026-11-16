// StockTrack · comportamiento mínimo del lado del cliente (compatible con CSP sin scripts en línea).
(function () {
  "use strict";

  // Menú lateral en pantallas pequeñas
  document.querySelectorAll("[data-toggle='sidebar']").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var sidebar = document.getElementById("sidebar");
      if (sidebar) sidebar.classList.toggle("open");
    });
  });

  // Confirmación antes de enviar formularios destructivos
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
    });
  });

  // RNF-04: cierre por inactividad. El servidor es quien decide; aquí solo se mantiene viva la
  // sesión mientras hay actividad y se redirige al login cuando ya expiró.
  var idleSeconds = parseInt(document.body.getAttribute("data-idle-seconds") || "0", 10);
  if (idleSeconds > 0) {
    var lastActivity = Date.now(), lastPing = Date.now();
    var token = (document.querySelector("meta[name='csrf-token']") || {}).content || "";
    ["click", "keydown", "mousemove", "touchstart", "scroll"].forEach(function (name) {
      document.addEventListener(name, function () { lastActivity = Date.now(); }, { passive: true });
    });
    setInterval(function () {
      var now = Date.now();
      if (now - lastActivity > idleSeconds * 1000) {
        window.location.href = document.body.getAttribute("data-login-url");
      } else if (lastActivity > lastPing && now - lastPing > 60000) {
        lastPing = now;
        fetch(document.body.getAttribute("data-ping-url"), {
          method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": token }
        }).then(function (r) {
          if (r.status === 401) window.location.href = document.body.getAttribute("data-login-url");
        }).catch(function () {});
      }
    }, 15000);
  }

  // Autocompletado de SKU en el formulario de movimientos
  var input = document.getElementById("sku-input");
  var list = document.getElementById("sku-suggestions");
  if (input && list) {
    var timer = null;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 2) return;
      timer = setTimeout(function () {
        fetch(input.getAttribute("data-suggest-url") + "?q=" + encodeURIComponent(q), {
          credentials: "same-origin",
          headers: { Accept: "application/json" }
        })
          .then(function (r) { return r.ok ? r.json() : []; })
          .then(function (items) {
            list.innerHTML = "";
            items.forEach(function (item) {
              var option = document.createElement("option");
              option.value = item.sku;
              option.textContent = item.name + " (stock " + item.stock + ")";
              list.appendChild(option);
            });
          })
          .catch(function () { /* sin sugerencias si falla la red */ });
      }, 200);
    });
  }
})();
