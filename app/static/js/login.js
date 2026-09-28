/* Tela de acesso: máscara e validação do CPF + envio à API. */
(function () {
  "use strict";
  var form = document.getElementById("form-login");
  var input = document.getElementById("cpf");
  var erro = document.getElementById("login-erro");
  var botao = document.getElementById("btn-entrar");
  var texto = botao.querySelector(".js-texto");

  function digitos(v) { return (v || "").replace(/\D/g, "").slice(0, 11); }

  function mascarar(d) {
    var r = d.slice(0, 3);
    if (d.length > 3) r += "." + d.slice(3, 6);
    if (d.length > 6) r += "." + d.slice(6, 9);
    if (d.length > 9) r += "-" + d.slice(9, 11);
    return r;
  }

  function cpfValido(c) {
    if (c.length !== 11 || /^(\d)\1{10}$/.test(c)) return false;
    for (var t = 9; t < 11; t++) {
      var soma = 0;
      for (var i = 0; i < t; i++) soma += parseInt(c[i], 10) * (t + 1 - i);
      if (((soma * 10) % 11) % 10 !== parseInt(c[t], 10)) return false;
    }
    return true;
  }

  input.addEventListener("input", function () {
    input.value = mascarar(digitos(input.value));
    input.removeAttribute("aria-invalid");
    erro.hidden = true;
  });

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var cpf = digitos(input.value);
    // Validação local é só conveniência; o backend valida novamente.
    // CPFs fictícios da demonstração são aceitos apenas pelo servidor em DEMO_MODE.
    if (cpf.length !== 11 || (!cpfValido(cpf) && cpf !== "00000000000")) {
      input.setAttribute("aria-invalid", "true");
      App.mostrarErro(erro, "CPF inválido. Verifique os números informados.");
      input.focus();
      return;
    }
    var dados = { cpf: cpf };
    form.querySelectorAll("input:not(#cpf)").forEach(function (el) { if (el.name) dados[el.name] = el.value; });

    botao.disabled = true;
    texto.textContent = "Validando CPF...";
    botao.insertAdjacentHTML("afterbegin", '<span class="spinner" aria-hidden="true"></span>');

    App.postJSON("/api/auth/responsavel", dados).then(function (r) {
      if (r.ok && r.corpo.redirecionar) {
        window.location.assign(r.corpo.redirecionar);
        return;
      }
      var msg = r.corpo.erro || "Não foi possível acessar. Tente novamente.";
      if (r.corpo.dicas && r.corpo.dicas.length) msg += " " + r.corpo.dicas.join(" ");
      App.mostrarErro(erro, msg);
      restaurar();
    }).catch(function () {
      App.mostrarErro(erro, "Falha de conexão. Verifique sua internet e tente novamente.");
      restaurar();
    });
  });

  function restaurar() {
    botao.disabled = false;
    texto.textContent = "Entrar";
    var s = botao.querySelector(".spinner");
    if (s) s.remove();
  }
})();
