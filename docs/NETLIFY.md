# Publicação no Netlify

O sistema usa Flask, PDFs e sessão no servidor. Por isso o Flask deve continuar
hospedado no Render (ou outro serviço Python); o Netlify entrega o domínio público
e encaminha todas as requisições por `netlify/functions/proxy.mjs`.

## 1. Publique o backend Flask

1. Crie o serviço pelo `render.yaml` deste repositório e informe `DATABASE_URL`,
   `SECRET_KEY`, `CPF_PEPPER`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`,
   `SUPABASE_SECRET_KEY` (se usar gestão de usuários) e `ADMIN_EMAILS`.
2. No Render, defina também `PROXY_FIX=true`, `FORCAR_HTTPS=true`,
   `SESSION_COOKIE_SECURE=true` e `DEMO_MODE=false`.
3. Guarde a URL HTTPS do Render, por exemplo `https://autoriza-escolar.onrender.com`.

## 2. Crie o projeto no Netlify

1. Em **Add new project → Import an existing project**, escolha este repositório
   e a branch desejada.
2. O arquivo `netlify.toml` já configura publicação e função. Não informe comando
   de build nem diretório manualmente.
3. Em **Project configuration → Environment variables**, crie:

   ```text
   FLASK_BACKEND_URL=https://autoriza-escolar.onrender.com
   ```

4. Publique. Depois de receber a URL `https://SEU-SITE.netlify.app`, volte ao
   Render e defina `PUBLIC_BASE_URL` com essa URL. Faça um novo deploy no Render.

## Verificação

- Abra a URL do Netlify e faça um teste de acesso por CPF.
- Acesse `/admin/login` e confirme o login do Supabase.
- Gere um PDF e valide se o QR Code aponta para o domínio do Netlify.

Nunca cadastre `DATABASE_URL`, `SECRET_KEY`, `CPF_PEPPER` ou chaves Supabase no
Netlify: eles pertencem somente ao backend Flask no Render.
