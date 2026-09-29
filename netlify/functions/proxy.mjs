/**
 * Porta de entrada Netlify para o Flask hospedado em um serviço Python.
 * Configure FLASK_BACKEND_URL no painel do Netlify com a URL HTTPS do Render.
 */
const HOP_BY_HOP = new Set([
  "connection", "content-length", "host", "keep-alive", "proxy-authenticate",
  "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
]);

export default async function handler(request) {
  const backend = process.env.FLASK_BACKEND_URL?.replace(/\/$/, "");
  if (!backend) {
    return new Response("Configuração pendente: defina FLASK_BACKEND_URL no Netlify.", {
      status: 503, headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }

  const origem = new URL(request.url);
  const destino = new URL(`${origem.pathname}${origem.search}`, `${backend}/`);
  const headers = new Headers(request.headers);
  for (const nome of HOP_BY_HOP) headers.delete(nome);
  headers.set("x-forwarded-host", origem.host);
  headers.set("x-forwarded-proto", "https");

  try {
    const resposta = await fetch(destino, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      redirect: "manual",
    });
    const respostaHeaders = new Headers(resposta.headers);
    respostaHeaders.delete("content-encoding");
    respostaHeaders.delete("content-length");
    respostaHeaders.set("x-proxy-backend", "flask");
    return new Response(resposta.body, { status: resposta.status, headers: respostaHeaders });
  } catch {
    return new Response("Não foi possível conectar ao serviço da aplicação.", {
      status: 502, headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }
}

export const config = { path: "/*", preferStatic: false };
