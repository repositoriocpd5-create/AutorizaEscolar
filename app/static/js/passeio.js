/* Seleção das respostas, modal de confirmação e registro via API. */
(function () {
  "use strict";
  var form = document.getElementById("form-respostas");
  if (!form) return;
  var botao = document.getElementById("btn-continuar");
  var contador = document.getElementById("contador");
  var modal = document.getElementById("modal-confirmar");
  var formModal = document.getElementById("form-confirmar");
  var declaracao = document.getElementById("declaracao");
  var btnConfirmar = document.getElementById("btn-confirmar");
  var btnCancelar = document.getElementById("btn-cancelar");
  var erro = document.getElementById("modal-erro");
  var loading = document.getElementById("modal-loading");
  var loadingTexto = loading.querySelector(".js-loading-text");
  var enviando = false;

  function selecionadas() {
    var lista = [];
    form.querySelectorAll(".aluno-card").forEach(function (card) {
      var marcado = card.querySelector('input[type="radio"]:checked');
      var fieldset = card.querySelector(".opcoes");
      if (marcado && marcado.value && fieldset && !fieldset.hidden) {
        lista.push({ aluno_id: card.dataset.aluno, nome: card.dataset.nome, situacao: marcado.value });
      }
    });
    return lista;
  }

  function atualizar() {
    // Fallback visual para navegadores sem :has()
    form.querySelectorAll(".opcao").forEach(function (op) {
      op.classList.toggle("is-checked", op.querySelector("input").checked);
    });
    if (!botao) return;
    // A barra só aparece enquanto houver aluno aguardando seleção
    document.getElementById("action-bar").hidden = !form.querySelector(".opcoes:not([hidden])");
    var sel = selecionadas();
    var aut = sel.filter(function (s) { return s.situacao === "AUTORIZADO"; }).length;
    var neg = sel.length - aut;
    botao.disabled = sel.length === 0;
    if (!sel.length) {
      contador.textContent = "Selecione a resposta para cada filho.";
    } else {
      var partes = [];
      var canc = sel.filter(function (s) { return s.situacao === "CANCELADO"; }).length;
      neg -= canc;
      if (aut) partes.push(aut + (aut > 1 ? " autorizações" : " autorização"));
      if (neg) partes.push(neg + (neg > 1 ? " negativas" : " negativa"));
      if (canc) partes.push(canc + (canc > 1 ? " cancelamentos" : " cancelamento"));
      contador.textContent = partes.join(" e ") + (sel.length > 1 ? " selecionadas" : " selecionada");
    }
  }

  form.addEventListener("change", atualizar);

  // "Alterar resposta": revela as opções de um aluno já respondido
  form.querySelectorAll(".js-alterar").forEach(function (b) {
    b.addEventListener("click", function () {
      var fs = document.getElementById(b.getAttribute("aria-controls"));
      var abrir = fs.hidden;
      fs.hidden = !abrir;
      b.setAttribute("aria-expanded", String(abrir));
      if (!abrir) fs.querySelector('input[value=""]').checked = true;
      atualizar();
    });
  });

  function preencherLista(id, grupoId, itens, icone) {
    var ul = document.getElementById(id);
    ul.innerHTML = "";
    itens.forEach(function (s) {
      var li = document.createElement("li");
      li.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-' + icone + '"></use></svg>';
      li.appendChild(document.createTextNode(s.nome));
      ul.appendChild(li);
    });
    document.getElementById(grupoId).hidden = itens.length === 0;
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var sel = selecionadas();
    if (!sel.length) return;
    preencherLista("lista-autorizados", "grupo-autorizados", sel.filter(function (s) { return s.situacao === "AUTORIZADO"; }), "check");
    preencherLista("lista-negados", "grupo-negados", sel.filter(function (s) { return s.situacao === "NAO_AUTORIZADO"; }), "x");
    preencherLista("lista-cancelados", "grupo-cancelados", sel.filter(function (s) { return s.situacao === "CANCELADO"; }), "ban");
    var soAut = sel.every(function (s) { return s.situacao === "AUTORIZADO"; });
    document.getElementById("modal-titulo").textContent = soAut ? "Confirmar autorização" : "Confirmar respostas";
    document.querySelector(".js-confirmar-texto").textContent = soAut ? "Confirmar autorização" : "Confirmar";
    declaracao.checked = false;
    btnConfirmar.disabled = true;
    erro.hidden = true;
    loading.hidden = true;
    if (typeof modal.showModal === "function") modal.showModal(); else modal.setAttribute("open", "");
    declaracao.focus();
  });

  declaracao.addEventListener("change", function () { btnConfirmar.disabled = !declaracao.checked || enviando; });
  btnCancelar.addEventListener("click", function () { if (!enviando) modal.close(); });
  modal.addEventListener("cancel", function (ev) { if (enviando) ev.preventDefault(); });

  formModal.addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (enviando || !declaracao.checked) return;   // evita duplo clique
    enviando = true;
    btnConfirmar.disabled = true;
    btnCancelar.disabled = true;
    erro.hidden = true;
    loading.hidden = false;
    loadingTexto.textContent = "Registrando autorização...";
    var timer = setTimeout(function () { loadingTexto.textContent = "Gerando documento..."; }, 900);

    var payload = {
      passeio_id: form.dataset.passeio,
      autorizacoes: selecionadas().map(function (s) { return { aluno_id: s.aluno_id, situacao: s.situacao }; }),
      declaracao_aceita: true
    };
    App.postJSON(form.dataset.api, payload).then(function (r) {
      clearTimeout(timer);
      if (r.ok && r.corpo.redirecionar) {
        loadingTexto.textContent = "Concluído!";
        window.location.assign(r.corpo.redirecionar);
        return;
      }
      falha(r.corpo.erro);
    }).catch(function () {
      clearTimeout(timer);
      falha();
    });
  });

  function falha(msg) {
    enviando = false;
    loading.hidden = true;
    btnCancelar.disabled = false;
    btnConfirmar.disabled = !declaracao.checked;
    App.mostrarErro(erro, msg || "Não foi possível registrar a autorização. Nenhuma alteração foi realizada. Tente novamente.");
  }

  atualizar();
})();
