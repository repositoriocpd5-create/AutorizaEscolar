/* Utilitários compartilhados. Nenhum dado pessoal é gravado no navegador. */
(function () {
  "use strict";
  var meta = document.querySelector('meta[name="csrf-token"]');

  window.App = {
    csrf: meta ? meta.content : "",

    /** POST JSON com token CSRF e tratamento uniforme de erros. */
    postJSON: function (url, dados) {
      return fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": App.csrf, "Accept": "application/json" },
        body: JSON.stringify(dados)
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (corpo) {
          return { ok: r.ok, status: r.status, corpo: corpo };
        });
      });
    },

    mostrarErro: function (el, texto) {
      el.textContent = texto;
      el.hidden = false;
    }
  };
})();
