"""Gera docs/supabase/corrigir_responsaveis.sql (LOCAL, fora do Git).

Remove responsáveis COM CPF duplicados por uma importação feita com um CPF_PEPPER
diferente do servidor. O arquivo leva só os HMACs corretos (calculados com o
CPF_PEPPER do .env.producao), nunca CPFs em claro.

Uso:  .venv\\Scripts\\python scripts\\gerar_correcao_responsaveis.py csv\\arquivo.json
"""
import hashlib
import hmac
import sys
from pathlib import Path

from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.services.importacao_alunos import ler_arquivo  # noqa: E402


def main(arquivo: str, env: str = ".env.producao") -> None:
    pepper = dotenv_values(RAIZ / env).get("CPF_PEPPER")
    if not pepper:
        raise SystemExit(f"CPF_PEPPER não encontrado em {env}")
    leitura = ler_arquivo(arquivo)
    cpfs = {c for l in leitura.linhas for c in (l.cpf_mae, l.cpf_pai) if c}
    hashes = sorted(hmac.new(pepper.encode(), c.encode(), hashlib.sha256).hexdigest() for c in cpfs)
    lista = ",\n    ".join(f"'{h}'" for h in hashes)
    sql = f"""-- >>>>>>>>>> CORRIGE RESPONSÁVEIS DUPLICADOS — basta clicar em "RUN" <<<<<<<<<<
-- Remove responsáveis COM CPF criados por uma importação feita com um CPF_PEPPER diferente
-- do servidor (eles têm o mesmo nome e os mesmos filhos, mas não conseguem entrar).
-- Mantém os {len(hashes)} responsáveis corretos, identificados pelo hash do CPF (sem CPF em claro).
-- Não versione este arquivo. Tudo em um único comando; pode ser executado de novo.
DO $corrige$
DECLARE
  v_ok text[] := ARRAY[
    {lista}
  ];
  v_extras int[];
  n_certos int;
BEGIN
  SELECT count(*) INTO n_certos FROM responsavel WHERE cpf_hash = ANY (v_ok);
  IF n_certos < cardinality(v_ok) THEN
    RAISE EXCEPTION 'Só % de % responsáveis corretos foram encontrados: rode antes o alunos.sql pronto (com o CPF_PEPPER do .env.producao). Nada foi alterado.', n_certos, cardinality(v_ok);
  END IF;
  -- Extras: com CPF, não importados sem CPF, hash fora da lista e ligados SOMENTE a alunos importados
  SELECT coalesce(array_agg(r.id), '{{}}') INTO v_extras FROM responsavel r
   WHERE r.cpf_hash IS NOT NULL AND r.id_externo IS NULL AND NOT (r.cpf_hash = ANY (v_ok))
     AND EXISTS (SELECT 1 FROM responsavel_aluno ra JOIN aluno a ON a.id = ra.aluno_id
                  WHERE ra.responsavel_id = r.id AND a.id_externo IS NOT NULL)
     AND NOT EXISTS (SELECT 1 FROM responsavel_aluno ra JOIN aluno a ON a.id = ra.aluno_id
                      WHERE ra.responsavel_id = r.id AND a.id_externo IS NULL);
  DELETE FROM documento_item WHERE documento_id IN (SELECT id FROM documento WHERE responsavel_id = ANY (v_extras));
  DELETE FROM autorizacao_historico WHERE responsavel_id = ANY (v_extras);
  UPDATE autorizacao SET documento_id = NULL
   WHERE documento_id IN (SELECT id FROM documento WHERE responsavel_id = ANY (v_extras));
  DELETE FROM documento WHERE responsavel_id = ANY (v_extras);
  DELETE FROM autorizacao WHERE responsavel_id = ANY (v_extras);
  DELETE FROM responsavel_aluno WHERE responsavel_id = ANY (v_extras);
  DELETE FROM responsavel WHERE id = ANY (v_extras);
  RAISE NOTICE 'Responsáveis duplicados removidos: %', cardinality(v_extras);
END
$corrige$;

SELECT (SELECT count(*) FROM responsavel)                         AS responsaveis,
       (SELECT count(*) FROM responsavel WHERE cpf_hash IS NOT NULL) AS com_cpf,
       (SELECT count(*) FROM responsavel WHERE cpf_hash IS NULL)     AS sem_cpf,
       (SELECT count(*) FROM responsavel_aluno)                      AS vinculos;
"""
    saida = RAIZ / "docs" / "supabase" / "corrigir_responsaveis.sql"
    saida.write_text(sql, encoding="utf-8")
    print(f"{len(hashes)} responsáveis corretos -> {saida}")


if __name__ == "__main__":
    main(sys.argv[1])
