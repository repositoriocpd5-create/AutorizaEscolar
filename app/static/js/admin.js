/* Comportamentos do painel administrativo. */
(function () {
  "use strict";

  // Barra de filtros: turma depende de escola e ano (registrado antes do autosubmit).
  document.querySelectorAll(".js-filter-bar").forEach(function (form) {
    var escola = form.querySelector(".js-f-escola");
    var ano = form.querySelector(".js-f-ano");
    var turma = form.querySelector(".js-f-turma");
    if (!turma) return;
    function sincronizar() {
      Array.prototype.forEach.call(turma.options, function (op) {
        if (!op.value) return;
        var oculta = (escola && escola.value && op.dataset.escola !== escola.value) ||
                     (ano && ano.value && op.dataset.ano !== ano.value);
        op.hidden = oculta;
        op.disabled = oculta;
      });
      var sel = turma.options[turma.selectedIndex];
      if (sel && sel.disabled) turma.value = "";
    }
    // Trocar de passeio zera escola/ano/turma (as turmas participantes mudam).
    var passeio = form.querySelector('select[name="passeio"]');
    if (passeio) passeio.addEventListener("change", function () {
      [escola, ano, turma].forEach(function (s) { if (s && !s.disabled) s.value = ""; });
    });
    if (escola) escola.addEventListener("change", sincronizar);
    if (ano) ano.addEventListener("change", sincronizar);
    // Escolher uma turma define escola e ano coerentes.
    turma.addEventListener("change", function () {
      var op = turma.options[turma.selectedIndex];
      if (op && op.value) {
        if (escola && !escola.disabled && escola.value && escola.value !== op.dataset.escola) escola.value = op.dataset.escola;
        if (ano && ano.value && ano.value !== op.dataset.ano) ano.value = op.dataset.ano;
      }
    });
    sincronizar();
  });

  document.querySelectorAll(".js-autosubmit").forEach(function (el) {
    el.addEventListener("change", function () { el.form.submit(); });
  });

  document.querySelectorAll("form.js-confirm").forEach(function (f) {
    f.addEventListener("submit", function (ev) {
      if (!window.confirm(f.dataset.confirm)) ev.preventDefault();
    });
  });

  // Pré-visualização: arquivo escolhido ou ilustração da galeria
  document.querySelectorAll("input[type=file].js-preview").forEach(function (inp) {
    inp.addEventListener("change", function () {
      var alvo = inp.closest(".form-grid").querySelector(".img-preview img");
      if (alvo && inp.files && inp.files[0]) alvo.src = URL.createObjectURL(inp.files[0]);
    });
  });
  document.querySelectorAll(".js-imagem-evento").forEach(function (sec) {
    var alvo = sec.querySelector(".js-preview-alvo");
    var arquivo = sec.querySelector("input[type=file]");
    sec.querySelectorAll(".galeria input[type=radio]").forEach(function (r) {
      r.addEventListener("change", function () {
        // Só pré-visualiza a ilustração se não houver arquivo selecionado agora
        if (alvo && !(arquivo && arquivo.files && arquivo.files.length)) {
          alvo.src = r.parentElement.querySelector("img").src;
        }
      });
    });
  });

  // Revogação: seleção individual, da página ou de todo o filtro, com motivo único
  document.querySelectorAll("form.js-revogacao").forEach(function (form) {
    var sels = Array.prototype.slice.call(form.querySelectorAll(".js-sel"));
    var marcarPagina = form.querySelector(".js-marcar-pagina");
    var barra = form.querySelector(".bulk-bar");
    var qtd = form.querySelector(".js-qtd");
    var btnTodos = form.querySelector(".js-todos-filtro");
    var todosFiltrados = form.querySelector(".js-todos-filtrados");
    var totalFiltro = parseInt((btnTodos.textContent.match(/\d+/) || ["0"])[0], 10);
    var modal = form.querySelector("#modal-revogar");
    var lista = form.querySelector(".js-revogar-lista");
    var resumo = form.querySelector(".js-revogar-resumo");
    var motivo = form.querySelector("#motivo-lote");
    var confirma = form.querySelector(".js-revogar-confirma");
    var enviar = form.querySelector(".js-revogar-enviar");
    var enviando = false;

    if (!sels.length && marcarPagina) marcarPagina.disabled = true;

    function marcados() { return sels.filter(function (c) { return c.checked; }); }

    function atualizar() {
      var m = marcados();
      sels.forEach(function (c) { c.closest("tr").classList.toggle("is-selecionado", c.checked); });
      var todos = todosFiltrados.value === "1";
      qtd.textContent = todos ? totalFiltro : m.length;
      barra.hidden = !todos && m.length === 0;
      if (marcarPagina) {
        marcarPagina.checked = sels.length > 0 && m.length === sels.length;
        marcarPagina.indeterminate = m.length > 0 && m.length < sels.length;
      }
      // Oferece "todos do filtro" quando a página inteira está marcada e há mais resultados
      btnTodos.hidden = todos || !(m.length === sels.length && totalFiltro > sels.length);
    }

    sels.forEach(function (c) {
      c.addEventListener("change", function () { todosFiltrados.value = "0"; atualizar(); });
    });
    if (marcarPagina) marcarPagina.addEventListener("change", function () {
      todosFiltrados.value = "0";
      sels.forEach(function (c) { c.checked = marcarPagina.checked; });
      atualizar();
    });
    btnTodos.addEventListener("click", function () { todosFiltrados.value = "1"; atualizar(); });
    form.querySelector(".js-limpar-selecao").addEventListener("click", function () {
      todosFiltrados.value = "0";
      sels.forEach(function (c) { c.checked = false; });
      atualizar();
    });

    function validar() {
      enviar.disabled = enviando || !confirma.checked || motivo.value.trim().length < 5;
    }
    motivo.addEventListener("input", validar);
    confirma.addEventListener("change", validar);

    function abrir() {
      var todos = todosFiltrados.value === "1";
      var m = marcados();
      var n = todos ? totalFiltro : m.length;
      if (!n) return;
      lista.innerHTML = "";
      if (todos) {
        resumo.textContent = "Todas as " + n + " autorizações revogáveis do filtro atual serão revogadas com o motivo abaixo.";
      } else {
        resumo.textContent = n === 1 ? "A autorização abaixo será revogada:" : n + " autorizações serão revogadas com o mesmo motivo:";
        m.forEach(function (c) {
          var li = document.createElement("li");
          li.textContent = c.dataset.nome;
          lista.appendChild(li);
        });
      }
      lista.hidden = todos;
      form.querySelector("#revogar-titulo").textContent = n === 1 ? "Revogar autorização" : "Revogar " + n + " autorizações";
      enviar.lastChild.textContent = n === 1 ? "Revogar" : "Revogar " + n;
      confirma.checked = false;
      validar();
      modal.showModal();
      motivo.focus();
    }
    form.querySelector(".js-abrir-revogacao").addEventListener("click", abrir);

    // Botão "Revogar" da linha: seleciona apenas aquele aluno e abre a janela
    form.querySelectorAll(".js-revogar-um").forEach(function (a) {
      a.addEventListener("click", function (ev) {
        ev.preventDefault();
        todosFiltrados.value = "0";
        sels.forEach(function (c) { c.checked = c.value === a.dataset.aut; });
        atualizar();
        abrir();
      });
    });

    form.querySelector(".js-revogar-cancelar").addEventListener("click", function () { if (!enviando) modal.close(); });
    modal.addEventListener("cancel", function (ev) { if (enviando) ev.preventDefault(); });
    form.addEventListener("submit", function (ev) {
      if (enviando || enviar.disabled) { ev.preventDefault(); return; }
      enviando = true;  // evita duplo envio
      enviar.disabled = true;
      enviar.lastChild.textContent = "Revogando...";
    });

    atualizar();
  });

  document.querySelectorAll(".js-print").forEach(function (b) {
    b.addEventListener("click", function () { window.print(); });
  });

  // Marca/desmarca todas as turmas de uma escola no cadastro de passeio
  document.querySelectorAll(".js-toggle-escola").forEach(function (chk) {
    var turmas = document.querySelectorAll('input[name="turmas"][data-escola="' + chk.dataset.escola + '"]');
    function sync() {
      var marcadas = Array.prototype.filter.call(turmas, function (t) { return t.checked; }).length;
      chk.checked = marcadas === turmas.length && turmas.length > 0;
      chk.indeterminate = marcadas > 0 && marcadas < turmas.length;
    }
    chk.addEventListener("change", function () {
      turmas.forEach(function (t) { t.checked = chk.checked; });
    });
    turmas.forEach(function (t) { t.addEventListener("change", sync); });
    sync();
  });
})();
