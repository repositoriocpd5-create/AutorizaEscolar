-- >>>>>>>>>> REMOVE OS DADOS DE EXEMPLO (DEMONSTRAÇÃO) — basta clicar em "RUN" <<<<<<<<<<
-- Autoriza Escolar — limpeza dos dados fictícios criados pelo "seed-demo".
--
-- Remove: escolas de exemplo (códigos EM-001 e EM-002) com suas turmas, alunos,
-- responsáveis de exemplo, vínculos, autorizações, históricos, documentos PDF e usuários
-- do painel vinculados a essas escolas; e passeios que ficarem sem turmas
-- (ex.: "Visita ao Museu de Ciências").
-- Mantém: as escolas reais, os alunos/responsáveis importados e o "Passeio ao Cinema",
-- que passa a valer para TODAS as turmas da escola indicada em v_inep_passeio
-- (padrão: E. M. Amauri Ferreira). Deixe v_inep_passeio vazio ('') para não mexer no passeio.
--
-- Tudo em um único comando: ou remove tudo, ou nada. Pode ser executado mais de uma vez.
DO $limpeza$
DECLARE
  v_inep_passeio text := '33045119';   -- >>> escola cujas turmas passam a participar do "Passeio ao Cinema"
  v_escolas int[];
  v_alunos  int[];
  v_resps   int[];
  v_auts    int[];
  v_docs    int[];
  v_cinema  int;
  v_escola_passeio int;
  n_alunos int; n_resps int; n_passeios int; n_participantes int;
BEGIN
  SELECT coalesce(array_agg(id), '{}') INTO v_escolas FROM escola WHERE codigo IN ('EM-001', 'EM-002');
  SELECT coalesce(array_agg(id), '{}') INTO v_alunos  FROM aluno  WHERE escola_id = ANY (v_escolas);
  -- Responsáveis de exemplo: sem id_externo (não importados) e ligados SOMENTE a alunos de exemplo
  SELECT coalesce(array_agg(r.id), '{}') INTO v_resps FROM responsavel r
   WHERE r.id_externo IS NULL
     AND EXISTS (SELECT 1 FROM responsavel_aluno ra WHERE ra.responsavel_id = r.id AND ra.aluno_id = ANY (v_alunos))
     AND NOT EXISTS (SELECT 1 FROM responsavel_aluno ra WHERE ra.responsavel_id = r.id AND NOT (ra.aluno_id = ANY (v_alunos)));
  SELECT coalesce(array_agg(id), '{}') INTO v_auts FROM autorizacao
   WHERE aluno_id = ANY (v_alunos) OR responsavel_id = ANY (v_resps);
  SELECT coalesce(array_agg(id), '{}') INTO v_docs FROM documento
   WHERE responsavel_id = ANY (v_resps)
      OR id IN (SELECT documento_id FROM documento_item WHERE autorizacao_id = ANY (v_auts));
  n_alunos := cardinality(v_alunos);
  n_resps  := cardinality(v_resps);

  -- Autorizações, históricos e documentos dos dados de exemplo
  DELETE FROM documento_item WHERE autorizacao_id = ANY (v_auts) OR documento_id = ANY (v_docs);
  DELETE FROM autorizacao_historico WHERE autorizacao_id = ANY (v_auts) OR documento_id = ANY (v_docs)
                                       OR responsavel_id = ANY (v_resps);
  UPDATE autorizacao SET documento_id = NULL WHERE documento_id = ANY (v_docs);
  DELETE FROM autorizacao WHERE id = ANY (v_auts);
  DELETE FROM documento WHERE id = ANY (v_docs);

  -- Vínculos, participações, alunos e responsáveis de exemplo
  DELETE FROM responsavel_aluno WHERE aluno_id = ANY (v_alunos) OR responsavel_id = ANY (v_resps);
  DELETE FROM passeio_aluno WHERE aluno_id = ANY (v_alunos);
  DELETE FROM aluno WHERE id = ANY (v_alunos);
  DELETE FROM responsavel WHERE id = ANY (v_resps);

  -- Usuários do painel presos às escolas de exemplo (ex.: escola.exemplo)
  DELETE FROM autorizacao_historico WHERE admin_id IN (SELECT id FROM admin_usuario WHERE escola_id = ANY (v_escolas));
  DELETE FROM admin_usuario WHERE escola_id = ANY (v_escolas);
  -- Usuário "Administrador (demo)" com senha local, se o seed o tiver criado
  DELETE FROM autorizacao_historico WHERE admin_id IN (SELECT id FROM admin_usuario WHERE nome = 'Administrador (demo)');
  DELETE FROM admin_usuario WHERE nome = 'Administrador (demo)';

  -- Turmas e escolas de exemplo
  DELETE FROM passeio_turma WHERE turma_id IN (SELECT id FROM turma WHERE escola_id = ANY (v_escolas));
  DELETE FROM turma WHERE escola_id = ANY (v_escolas);
  DELETE FROM escola WHERE id = ANY (v_escolas);

  -- "Passeio ao Cinema" passa a valer para as turmas da escola indicada
  SELECT id INTO v_cinema FROM passeio WHERE nome = 'Passeio ao Cinema' ORDER BY id LIMIT 1;
  IF v_inep_passeio <> '' AND v_cinema IS NOT NULL THEN
    SELECT id INTO v_escola_passeio FROM escola WHERE inep = v_inep_passeio;
    IF v_escola_passeio IS NULL THEN
      RAISE EXCEPTION 'Escola com INEP % não encontrada (linha v_inep_passeio). Nada foi removido.', v_inep_passeio;
    END IF;
    INSERT INTO passeio_turma (passeio_id, turma_id)
      SELECT v_cinema, t.id FROM turma t WHERE t.escola_id = v_escola_passeio
      ON CONFLICT DO NOTHING;
    INSERT INTO passeio_aluno (passeio_id, aluno_id)
      SELECT v_cinema, a.id FROM aluno a WHERE a.escola_id = v_escola_passeio AND a.ativo
      ON CONFLICT (passeio_id, aluno_id) DO NOTHING;
  END IF;

  -- Passeios que ficaram sem turmas e sem respostas (ex.: "Visita ao Museu de Ciências")
  SELECT count(*) INTO n_passeios FROM passeio p
   WHERE NOT EXISTS (SELECT 1 FROM passeio_turma pt WHERE pt.passeio_id = p.id)
     AND NOT EXISTS (SELECT 1 FROM autorizacao a WHERE a.passeio_id = p.id)
     AND NOT EXISTS (SELECT 1 FROM documento d WHERE d.passeio_id = p.id);
  UPDATE configuracao SET valor = NULL
   WHERE chave = 'passeio_destaque' AND valor IN (
     SELECT p.public_id FROM passeio p
      WHERE NOT EXISTS (SELECT 1 FROM passeio_turma pt WHERE pt.passeio_id = p.id)
        AND NOT EXISTS (SELECT 1 FROM autorizacao a WHERE a.passeio_id = p.id)
        AND NOT EXISTS (SELECT 1 FROM documento d WHERE d.passeio_id = p.id));
  DELETE FROM passeio_aluno WHERE passeio_id IN (
     SELECT p.id FROM passeio p WHERE NOT EXISTS (SELECT 1 FROM passeio_turma pt WHERE pt.passeio_id = p.id)
        AND NOT EXISTS (SELECT 1 FROM autorizacao a WHERE a.passeio_id = p.id)
        AND NOT EXISTS (SELECT 1 FROM documento d WHERE d.passeio_id = p.id));
  DELETE FROM passeio p WHERE NOT EXISTS (SELECT 1 FROM passeio_turma pt WHERE pt.passeio_id = p.id)
     AND NOT EXISTS (SELECT 1 FROM autorizacao a WHERE a.passeio_id = p.id)
     AND NOT EXISTS (SELECT 1 FROM documento d WHERE d.passeio_id = p.id);

  SELECT count(*) INTO n_participantes FROM passeio_aluno WHERE passeio_id = v_cinema;
  RAISE NOTICE 'Removidos: % alunos e % responsáveis de exemplo, % passeio(s) sem turmas. "Passeio ao Cinema": % alunos participantes.',
    n_alunos, n_resps, n_passeios, n_participantes;
END
$limpeza$;

-- Conferência (depois da limpeza)
SELECT (SELECT count(*) FROM escola)                                   AS escolas,
       (SELECT count(*) FROM aluno)                                    AS alunos,
       (SELECT count(*) FROM aluno WHERE ativo)                        AS alunos_ativos,
       (SELECT count(*) FROM responsavel)                              AS responsaveis,
       (SELECT count(*) FROM passeio)                                  AS passeios,
       (SELECT count(*) FROM passeio_aluno)                            AS participantes_em_passeios;
