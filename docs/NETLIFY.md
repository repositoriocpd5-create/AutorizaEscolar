# Publicação no Netlify (Edge Gateway + CDN)

O sistema utiliza arquitetura híbrida de alto desempenho:
1. **Netlify (Edge Gateway & CDN Global):** Serve todos os arquivos estáticos (CSS, JS, imagens pesadas de eventos, brasões e ícones) diretamente da borda (CDN) com cache de longa duração, e atua como gateway reverso seguro via função serverless/edge (`netlify/functions/proxy.mjs`).
2. **Backend Flask (Render / VPS):** Executa a lógica de negócios em Python, processamento de PDFs com ReportLab, consultas com SQLAlchemy/PostgreSQL e sessões criptografadas.

---

## 1. Passo a Passo do Deploy

### Passo 1: Publicar o Backend Flask (Render)
1. Crie o serviço web no Render a partir do repositório (usando o `render.yaml`).
2. Configure as variáveis de ambiente necessárias no Render:
   - `DATABASE_URL` (conexão session pooler do Supabase)
   - `SECRET_KEY` (chave aleatória de 64+ caracteres)
   - `CPF_PEPPER` (pepper secreto para HMAC do CPF)
   - `SUPABASE_URL` e `SUPABASE_PUBLISHABLE_KEY` (se usar Supabase Auth)
   - `SUPABASE_SECRET_KEY` (para criação e gestão de usuários)
   - `ADMIN_EMAILS` (e-mails com acesso inicial de administrador de rede)
   - `PROXY_FIX=true` (obrigatório para confiar no header `X-Forwarded-For` repassado pelo Netlify)
   - `FORCAR_HTTPS=true`
   - `SESSION_COOKIE_SECURE=true`
   - `DEMO_MODE=false` (para produção com dados reais)
3. Guarde a URL HTTPS gerada pelo Render (ex: `https://autoriza-escolar.onrender.com`).

---

### Passo 2: Criar o Projeto no Netlify
1. No painel do Netlify, clique em **Add new project → Import an existing project**.
2. Selecione seu provedor Git (GitHub / GitLab / Bitbucket) e o repositório deste projeto.
3. As configurações de compilação são lidas automaticamente do arquivo `netlify.toml`:
   - **Build command:** `node netlify/build.mjs`
   - **Publish directory:** `netlify/public`
   - **Functions directory:** `netlify/functions`
4. Em **Project configuration → Environment variables**, crie a variável de ambiente:
   ```text
   FLASK_BACKEND_URL=https://autoriza-escolar.onrender.com
   ```
   *(Substitua pela URL HTTPS real do seu backend no Render, sem barra no final).*
5. Clique em **Deploy site**.

---

### Passo 3: Ajustar a URL Pública no Render
1. Após a conclusão do deploy no Netlify, copie a URL do seu site Netlify (ex: `https://seu-dominio.netlify.app` ou seu domínio próprio personalizado).
2. Volte ao painel do **Render → Environment**:
   - Defina ou atualize `PUBLIC_BASE_URL` com o endereço do Netlify:
     ```text
     PUBLIC_BASE_URL=https://seu-dominio.netlify.app
     ```
3. Faça um novo deploy ou reinicie o serviço no Render.
   *(Isso garante que os links gerados nos QR Codes dos PDFs apontem diretamente para o domínio público do Netlify).*

---

## 2. Recursos e Otimizações Implementadas

- **Aceleração de Assets Estáticos:** O script `netlify/build.mjs` copia `app/static` para `netlify/public/static`, garantindo que estilos, scripts e imagens carreguem com latência mínima através do CDN do Netlify.
- **Encaminhamento de IP Real:** A função `proxy.mjs` repassa o IP de conexão do cliente via `X-Forwarded-For`, preservando os limites de taxa (anti-força bruta) e a integridade da trilha de auditoria (`AuditLog`).
- **Compatibilidade com Node 18+:** Suporte a streaming de requisições POST/PUT com corpo (`duplex: 'half'`).
- **Múltiplos Cookies Preservados:** Trata adequadamente múltiplos cabeçalhos `Set-Cookie` através de `getSetCookie()`, evitando perda de sessão ou descompasso do CSRF.
- **Reescrita Transparente de Redirecionamentos:** Se o Flask gerar um redirecionamento HTTP contendo o domínio do Render, o proxy reescreve o cabeçalho `Location` para manter o usuário no domínio do Netlify.

---

## 3. Checklist de Verificação Pós-Deploy

- [ ] Acessar `https://SEU-DOMINIO.netlify.app/` e conferir se a tela de login do responsável carrega instantaneamente.
- [ ] Testar autenticação com CPF de demonstração (se `DEMO_MODE=true`) ou CPF real.
- [ ] Acessar `https://SEU-DOMINIO.netlify.app/admin/login` e efetuar login administrativo.
- [ ] Emitir uma autorização de teste e baixar o PDF.
- [ ] Ler o QR Code do documento gerado e certificar-se de que a validação abre no endereço `https://SEU-DOMINIO.netlify.app/validar/<codigo>`.
- [ ] Verificar a rota `/saude` diretamente no backend do Render para monitoramento de uptime.

> [!WARNING]
> **Segurança:** Nunca cadastre `DATABASE_URL`, `SECRET_KEY`, `CPF_PEPPER` ou credenciais de banco no Netlify. Essas variáveis pertencem com exclusividade ao backend no Render.
