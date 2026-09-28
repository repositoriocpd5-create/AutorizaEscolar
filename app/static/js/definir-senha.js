/* Define a senha a partir do link de convite/redefinição do Supabase.
   O token vem no fragmento (#access_token=...), que o navegador não envia ao servidor. */
(function () {
  "use strict";
  var box = document.querySelector(".js-definir-senha");
  if (!box) return;
  var url = box.dataset.url, key = box.dataset.key;
  var hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  var token = hash.get("access_token");
  var erro = box.querySelector(".js-erro");
  var form = box.querySelector(".js-form");

  // Remove o token da barra de endereço/histórico
  if (window.location.hash) history.replaceState(null, "", window.location.pathname);

  if (hash.get("error_description")) {
    erro.textContent = "Link inválido ou expirado. Solicite um novo ao administrador.";
    erro.hidden = false;
    return;
  }
  if (!token || !url || !key) {
    box.querySelector(".js-sem-token").hidden = false;
    return;
  }
  form.hidden = false;
  var tipo = hash.get("type");
  box.querySelector(".js-email").textContent = tipo === "invite"
    ? "Bem-vindo(a)! Crie sua senha para acessar o painel."
    : "Crie uma nova senha para sua conta.";

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var nova = document.getElementById("nova").value;
    var conf = document.getElementById("confirma").value;
    erro.hidden = true;
    if (nova.length < 10) { erro.textContent = "A senha deve ter pelo menos 10 caracteres."; erro.hidden = false; return; }
    if (nova !== conf) { erro.textContent = "As senhas não conferem."; erro.hidden = false; return; }
    var btn = form.querySelector("button");
    btn.disabled = true;
    fetch(url.replace(/\/$/, "") + "/auth/v1/user", {
      method: "PUT",
      headers: { "apikey": key, "Authorization": "Bearer " + token, "Content-Type": "application/json" },
      body: JSON.stringify({ password: nova })
    }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      form.hidden = true;
      box.querySelector(".js-ok").hidden = false;
    }).catch(function () {
      btn.disabled = false;
      erro.textContent = "Não foi possível salvar a senha. O link pode ter expirado; solicite um novo.";
      erro.hidden = false;
    });
  });
})();
