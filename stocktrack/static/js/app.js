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
