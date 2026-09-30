/**
 * Script de build para o Netlify.
 * Copia os arquivos estáticos de `app/static` para `netlify/public/static`,
 * permitindo que sejam servidos com altíssimo desempenho diretamente pelo CDN global do Netlify.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const raiz = path.resolve(__dirname, "..");
const dirOrigem = path.join(raiz, "app", "static");
const dirDestinoPublic = path.join(__dirname, "public");
const dirDestinoStatic = path.join(dirDestinoPublic, "static");

console.log("Iniciando build para Netlify...");

// Limpa ou cria o diretório netlify/public
if (fs.existsSync(dirDestinoPublic)) {
  fs.rmSync(dirDestinoPublic, { recursive: true, force: true });
}
fs.mkdirSync(dirDestinoStatic, { recursive: true });

// Copia recursivamente app/static para netlify/public/static
function copiarDiretorio(origem, destino) {
  fs.mkdirSync(destino, { recursive: true });
  const itens = fs.readdirSync(origem, { withFileTypes: true });

  for (const item of itens) {
    const caminhoOrigem = path.join(origem, item.name);
    const caminhoDestino = path.join(destino, item.name);

    if (item.isDirectory()) {
      copiarDiretorio(caminhoOrigem, caminhoDestino);
    } else if (item.isFile()) {
      fs.copyFileSync(caminhoOrigem, caminhoDestino);
    }
  }
}

if (fs.existsSync(dirOrigem)) {
  copiarDiretorio(dirOrigem, dirDestinoStatic);
  console.log(`✓ Arquivos estáticos copiados com sucesso de app/static para netlify/public/static.`);
} else {
  console.warn(`! Diretório de origem não encontrado: ${dirOrigem}`);
}

console.log("Build concluído com sucesso.");
