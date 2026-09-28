# Passeio Escolar — Autorização Digital de Alunos

Sistema web para que responsáveis autorizem (ou não) a participação dos filhos em
passeios escolares, com registro auditável, PDF comprobatório com QR Code e
painel administrativo. Primeiro evento: **Passeio ao Cinema**.

Stack: Python 3.12+ · Flask · SQLAlchemy/Alembic · ReportLab (PDF e QR Code) ·
openpyxl (XLSX) · HTML/CSS/JS sem framework (mobile first).

## Publicar no Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/repositoriocpd5-create/AutorizaEscolar)

### Banco no Supabase

1. Supabase → **SQL Editor** → cole `docs/supabase/schema.sql` → **Run** (cria as 19 tabelas com RLS ativo).
   Alternativa: `DATABASE_URL=<string do Supabase> flask --app wsgi db upgrade` faz o mesmo.
2. Copie a string de conexão **Session pooler** (Project Settings → Database → Connection string)
   e informe-a como `DATABASE_URL` no Render.

A chave publicável do Supabase **não** é usada pelo sistema: com RLS ativo e sem políticas,
a API REST pública não acessa nenhum dado.

### Serviço web

O arquivo `render.yaml` cria o serviço web (gunicorn), com
`SECRET_KEY`, `CPF_PEPPER` e as senhas de demonstração **geradas pelo Render**
(veja em *Dashboard → autoriza-escolar → Environment*). Cada `push` na branch `main`
publica uma nova versão. Imagens enviadas ficam no banco, pois o disco do Render é
apagado a cada nova versão; os PDFs são regenerados de forma idêntica a partir do banco.

Observações do plano gratuito: o serviço do Render "dorme" após 15 min sem acesso
(o primeiro acesso seguinte demora ~1 min) e o projeto gratuito do Supabase é pausado
após uma semana sem uso — para uso real, use planos pagos e configure backups.

## Como executar (Windows / PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # ajuste SECRET_KEY e CPF_PEPPER
.\.venv\Scripts\flask --app wsgi db upgrade
.\.venv\Scripts\flask --app wsgi seed-demo      # somente com DEMO_MODE=true
.\.venv\Scripts\flask --app wsgi run --debug
```

Acesse <http://localhost:5000>. Linux/macOS: use `.venv/bin/` no lugar de `.\.venv\Scripts\`.

### Demonstração

| Perfil | Acesso |
|---|---|
| Responsável José da Silva (Pedro e Maria) | CPF `000.000.000-00` |
| Responsável Ana Paula Souza (3 filhos, 2 escolas) | CPF `529.982.247-25` |
| Administrador | <http://localhost:5000/admin> — usuário/senha em `DEMO_ADMIN_LOGIN` / `DEMO_ADMIN_SENHA` do `.env` |

O CPF `000.000.000-00` é inválido pelo dígito verificador; ele só é aceito com
`DEMO_MODE=true` e se estiver em `DEMO_CPFS`. O seed cria ~150 alunos fictícios
com respostas simuladas para o painel. A data do passeio fica 21 dias no futuro
(ajuste com `DEMO_PASSEIO_DATA=AAAA-MM-DD`).

Para recriar tudo: `flask --app wsgi seed-demo --reset`.

### Testes

```powershell
.\.venv\Scripts\python -m pytest -q
```

## Estrutura

```
app/
  __init__.py            fábrica da aplicação, erros, hooks de segurança
  config.py              configuração via variáveis de ambiente
  models.py              entidades (ver "Modelo de dados")
  security.py            CPF (validação/HMAC/máscara), CSRF, limite de tentativas, sessão, cabeçalhos
  audit.py               registro de auditoria
  formatacao.py          datas no fuso local e filtros Jinja
  cli.py                 comandos: seed-demo, criar-admin, limpar-tentativas
  services/
    auth_service.py      autenticação do responsável + segundo fator plugável
    passeio_service.py   consultas sempre filtradas pelo vínculo do responsável
    autorizacao_service.py  regras de negócio e gravação atômica
    documento_service.py    PDF A4 + QR Code, hash SHA-256
    relatorio_service.py    indicadores e exportação CSV/XLSX/PDF
  routes/
    public.py            páginas do responsável e validação pública
    api.py               API REST (JSON)
    admin.py             painel administrativo
  templates/
    components/ui.html   AppHeader, StatusBadge, ResponsavelCard, PasseioCard,
                         AlunoAuthorizationCard, ConfirmAuthorizationModal, SuccessCard, PDFViewer
    admin/_admin_ui.html FilterBar, DataTable, ReportExport, paginação
  static/                CSS, JS e ilustrações (SVG)
migrations/              Alembic (flask db migrate / upgrade)
seeds/demo.py            dados fictícios
tests/                   testes automatizados
```

## API REST

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/auth/responsavel` | `{cpf, [data_nascimento]}` → inicia sessão |
| POST | `/api/auth/sair` | encerra sessão |
| GET | `/api/responsavel/me` | nome e CPF mascarado |
| GET | `/api/responsavel/me/alunos` | alunos vinculados |
| GET | `/api/passeios/ativos` | passeios dos filhos |
| GET | `/api/passeios/{id}` | detalhes do passeio |
| GET | `/api/passeios/{id}/meus-alunos` | alunos + situação de cada um |
| POST | `/api/passeios/{id}/autorizacoes` | registra respostas (ver abaixo) |
| GET | `/api/autorizacoes/{id}` | situação e histórico |
| GET | `/api/autorizacoes/{id}/pdf` | PDF da última resposta |
| GET | `/api/documentos/{id}/pdf` | PDF de um documento |
| GET | `/api/validar/{codigo}` | validação pública (dados mínimos) |

Todos os `{id}` são UUIDs. Requisições `POST` exigem o cabeçalho `X-CSRF-Token`
(presente na meta tag `csrf-token` das páginas).

```json
POST /api/passeios/{id}/autorizacoes
{
  "autorizacoes": [
    {"aluno_id": "<uuid>", "situacao": "AUTORIZADO"},
    {"aluno_id": "<uuid>", "situacao": "NAO_AUTORIZADO"}
  ],
  "declaracao_aceita": true
}
```

## Regras de negócio implementadas

- O responsável só enxerga alunos com vínculo ativo de **responsável legal**
  (`ResponsavelAluno.responsavel_legal`); vínculos sem essa marca não autorizam.
- Um aluno pode ter vários responsáveis; a autorização é **uma por aluno e por
  passeio**. A resposta de outro responsável aparece como "registrada por outro
  responsável", sem expor o documento dele.
- O backend revalida sessão, vínculo, participação no passeio, prazo, declaração e
  situação atual. IDs vindos do frontend nunca são confiáveis.
- Respostas idênticas à atual são recusadas (sem duplicidade).
- Alterar depende de `permite_alteracao` e de `data_limite`; após o prazo nada muda.
- Toda mudança gera `AutorizacaoHistorico`; nada é apagado.
- Gravação atômica: todas as respostas da operação ou nenhuma.
- O PDF só é gerado **depois** do commit, a partir de uma fotografia imutável
  (`Documento.conteudo`); a regeneração produz o mesmo hash SHA-256.
- Vários filhos na mesma operação resultam em **um PDF**, mas em registros
  individuais (`Autorizacao` + `DocumentoItem`).
- A validação pública mostra "documento substituído" se houve resposta
  posterior ou cancelamento pela escola.
- A escola pode **cancelar** uma autorização (com motivo); o responsável volta a
  poder responder dentro do prazo.

## Segurança e LGPD

- CPF armazenado apenas como HMAC-SHA256 (`CPF_PEPPER`) + 2 últimos dígitos;
  exibido sempre como `***.***.***-00`; nunca vai para URL, localStorage ou exportações.
- Limite de tentativas por IP e por CPF (anti-força bruta/enumeração) e na validação pública.
- CSRF em todo POST; cookies `HttpOnly`/`SameSite=Lax` (`Secure` em produção);
  sessão expira em 30 min; CSP sem scripts inline; `no-store` em páginas com dados pessoais.
- Auditoria de login, consultas, autorizações, negativas, alterações, geração e
  download de PDF, validações e ações administrativas (sem segredos).
- Administradores podem ser restritos a uma escola (`AdminUsuario.escola_id`).
- Proteção contra injeção de fórmulas em CSV/XLSX.
- Avatares com iniciais: nenhuma foto de criança é tratada.

### Segundo fator

`AUTH_SEGUNDO_FATOR=data_nascimento` exige CPF + data de nascimento do
responsável (armazenada como HMAC em `Responsavel.data_nascimento_hash`) e passa
a responder com mensagem genérica, sem revelar se o CPF existe. Para SMS, e-mail
ou Gov.br, crie uma subclasse de `SegundoFator` em `app/services/auth_service.py`.

**O modo "somente CPF" é apenas para demonstração.**

## Produção — checklist

1. `DEMO_MODE=false` e **não** executar `seed-demo`; importar dados reais da
   gestão escolar (escolas, turmas, alunos, responsáveis, vínculos). Para gerar
   `cpf_hash`, use `app.security.hash_cpf(cpf)` com o mesmo `CPF_PEPPER`.
2. `SECRET_KEY` e `CPF_PEPPER` longos e aleatórios (guardar em cofre de segredos).
3. `AUTH_SEGUNDO_FATOR` diferente de `nenhum`.
4. PostgreSQL (`DATABASE_URL`) e `flask db upgrade`.
5. HTTPS: `SESSION_COOKIE_SECURE=true`, `FORCAR_HTTPS=true`, `PUBLIC_BASE_URL=https://...`;
   atrás de proxy reverso, `PROXY_FIX=true`.
6. Servidor WSGI: `waitress-serve --port 8000 wsgi:app` (Windows) ou `gunicorn wsgi:app`.
7. Agendar `flask --app wsgi limpar-tentativas` diariamente e backup do banco e de `DOCUMENTOS_DIR`.
8. Criar administradores com `flask --app wsgi criar-admin`.
9. Definir a política de retenção dos registros e dos PDFs.

## Painel administrativo — o que pode ser configurado

| Onde | O quê |
|---|---|
| **Configurações** (rede) | nome da instituição, título, subtítulo, brasão (upload), passeio em destaque e imagem padrão da tela inicial (galeria ou upload) |
| **Passeios** (rede) | nome, dados do evento, imagem (galeria de 9 ilustrações ou upload), prazo final, **horas para o responsável alterar/cancelar**, permitir alteração, termo de confirmação e declaração do PDF (versionados) |
| **Usuários** (rede) | cria usuários da rede ou de uma unidade escolar, redefine senha, ativa/desativa |
| **Painel** (rede e escolas) | filtros por passeio, escola, ano, turma, situação e pesquisa (sem acento); **revogação individual ou em lote** (selecionados, página ou todo o filtro) com motivo único |

Usuários de unidade escolar só enxergam e revogam alunos da própria escola (validado no servidor).
Demonstração: `escola.exemplo` / senha em `DEMO_ESCOLA_SENHA`.

Imagens enviadas são validadas com Pillow e regravadas em PNG com nome aleatório em `instance/uploads`.

## Novos passeios

Em **Admin → Passeios → Novo passeio**: nome, descrição, destino, data, horários,
local de saída, transporte, orientações, turmas participantes, prazo, se permite
alteração e se está ativo. O mesmo fluxo serve para museu, teatro, parque, viagem,
competição, evento cultural ou visita técnica. Alterar o texto da declaração cria
uma nova versão, registrada em cada autorização.
