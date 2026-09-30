/**
 * Porta de entrada Netlify Edge / Serverless Function para o backend Flask.
 * 
 * Funcionalidades:
 * - Encaminha requisições dinâmicas para FLASK_BACKEND_URL (ex: hospedado no Render).
 * - Repassa o IP real do cliente via X-Forwarded-For para auditoria e rate-limiting.
 * - Suporta chamadas POST/PUT com stream body (duplex: 'half') no Node 18+.
 * - Preserva múltiplos cabeçalhos Set-Cookie (sessão, CSRF) via getSetCookie().
 * - Reescreve cabeçalhos Location em redirects para manter o usuário no domínio do Netlify.
 * - Habilita preferStatic para que arquivos estáticos em /static sejam servidos direto pelo CDN.
 */
const HOP_BY_HOP = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

export default async function handler(request) {
  const backend = process.env.FLASK_BACKEND_URL?.replace(/\/$/, "");
  if (!backend) {
    return new Response(
      "Configuração pendente: defina a variável de ambiente FLASK_BACKEND_URL no painel do Netlify.",
      {
        status: 503,
        headers: { "content-type": "text/plain; charset=utf-8" },
      }
    );
  }

  const origem = new URL(request.url);
  const destino = new URL(`${origem.pathname}${origem.search}`, `${backend}/`);

  const headers = new Headers(request.headers);
  for (const nome of HOP_BY_HOP) {
    headers.delete(nome);
  }

  // Identificação do host e protocolo originais
  headers.set("x-forwarded-host", origem.host);
  headers.set("x-forwarded-proto", "https");

  // Captura o IP real fornecido pelo Netlify para repassar ao ProxyFix do Flask
  const clientIp =
    request.headers.get("x-nf-client-connection-ip") ||
    request.headers.get("client-ip");
  if (clientIp) {
    headers.set("x-forwarded-for", clientIp);
  }

  const temBody = !["GET", "HEAD"].includes(request.method);
  const fetchOptions = {
    method: request.method,
    headers,
    body: temBody ? request.body : undefined,
    redirect: "manual",
  };

  // Node.js 18+ exige duplex: 'half' ao enviar ReadableStream no body
  if (temBody && request.body) {
    fetchOptions.duplex = "half";
  }

  try {
    const resposta = await fetch(destino, fetchOptions);
    const respostaHeaders = new Headers(resposta.headers);

    respostaHeaders.delete("content-encoding");
    respostaHeaders.delete("content-length");
    respostaHeaders.set("x-proxy-backend", "flask");

    // Preserva múltiplos cookies Set-Cookie sem concatená-los com vírgulas
    if (typeof resposta.headers.getSetCookie === "function") {
      const cookies = resposta.headers.getSetCookie();
      if (cookies && cookies.length > 0) {
        respostaHeaders.delete("set-cookie");
        for (const cookie of cookies) {
          respostaHeaders.append("set-cookie", cookie);
        }
      }
    }

    // Se o backend responder com redirect para o próprio backend, reescreve para a URL do Netlify
    const location = respostaHeaders.get("location");
    if (location) {
      try {
        const locUrl = new URL(location, destino);
        const backendUrl = new URL(backend);
        if (locUrl.host === backendUrl.host) {
          locUrl.protocol = origem.protocol;
          locUrl.host = origem.host;
          locUrl.port = origem.port;
          respostaHeaders.set("location", locUrl.toString());
        }
      } catch {
        // Redirecionamento relativo é mantido como está
      }
    }

    return new Response(resposta.body, {
      status: resposta.status,
      headers: respostaHeaders,
    });
  } catch (erro) {
    console.error("Erro no proxy Netlify -> Flask:", erro);
    return new Response(
      "Não foi possível conectar ao serviço da aplicação. Verifique se o backend está ativo.",
      {
        status: 502,
        headers: { "content-type": "text/plain; charset=utf-8" },
      }
    );
  }
}

export const config = { path: "/*", preferStatic: true };
