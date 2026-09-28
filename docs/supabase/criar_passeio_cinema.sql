-- >>>>>>>>>> CRIA O "PASSEIO AO CINEMA" — confira as linhas 5 a 9 e clique em "RUN" <<<<<<<<<<
-- Cria (ou completa) o passeio e inclui TODAS as turmas e os alunos ativos da escola indicada.
-- Depois é possível editar tudo em Admin → Passeios. Pode ser executado de novo sem duplicar.
DO $passeio$
DECLARE
  v_inep     text := '33045119';                 -- >>> escola (E. M. Amauri Ferreira)
  v_data     date := current_date + 21;          -- >>> data do passeio (ex.: DATE '2026-10-19')
  v_limite   timestamp := (current_date + 18) + time '23:59';  -- >>> prazo final para responder
  v_nome     text := 'Passeio ao Cinema';
  v_destino  text := 'Cinema Shopping Cidade';
  v_escola   int;
  v_passeio  int;
  n_turmas   int;
  n_alunos   int;
BEGIN
  SELECT id INTO v_escola FROM escola WHERE inep = v_inep;
  IF v_escola IS NULL THEN
    RAISE EXCEPTION 'Escola com INEP % não encontrada. Nada foi alterado.', v_inep;
  END IF;
  IF v_limite::date > v_data THEN
    RAISE EXCEPTION 'O prazo para responder deve ser anterior ou igual à data do passeio.';
  END IF;

  SELECT id INTO v_passeio FROM passeio WHERE nome = v_nome ORDER BY id LIMIT 1;
  IF v_passeio IS NULL THEN
    INSERT INTO passeio (public_id, nome, descricao, destino, data, hora_saida, hora_retorno, local_saida,
                         transporte, orientacoes, data_limite, permite_alteracao, ativo, texto_declaracao,
                         texto_termo, versao_texto, prazo_alteracao_horas, ilustracao, criado_em)
    VALUES (gen_random_uuid()::text, v_nome,
            'Sessão de cinema com filme de classificação livre, como atividade cultural do bimestre.',
            v_destino, v_data, time '13:00', time '18:00', 'Unidade Escolar',
            'Transporte escolar disponibilizado pela rede',
            'Enviar lanche leve e garrafa de água. Usar uniforme escolar. Chegar à unidade escolar até 12h40.',
            v_limite, true, true,
            'Declaro, na condição de responsável legal, que autorizo o(s) aluno(s) identificado(s) neste documento a participar do passeio escolar descrito acima, estando ciente das informações, horários e condições apresentadas pela unidade escolar.',
            'Declaro que sou responsável legal pelo(s) aluno(s) selecionado(s) e confirmo esta autorização.',
            1, 48, 'cinema', now() AT TIME ZONE 'utc')
    RETURNING id INTO v_passeio;
  END IF;

  INSERT INTO passeio_turma (passeio_id, turma_id)
    SELECT v_passeio, t.id FROM turma t WHERE t.escola_id = v_escola
    ON CONFLICT DO NOTHING;
  INSERT INTO passeio_aluno (passeio_id, aluno_id)
    SELECT v_passeio, a.id FROM aluno a WHERE a.escola_id = v_escola AND a.ativo
    ON CONFLICT (passeio_id, aluno_id) DO NOTHING;

  SELECT count(*) INTO n_turmas FROM passeio_turma WHERE passeio_id = v_passeio;
  SELECT count(*) INTO n_alunos FROM passeio_aluno WHERE passeio_id = v_passeio;
  RAISE NOTICE '"%": % turmas e % alunos participantes.', v_nome, n_turmas, n_alunos;
END
$passeio$;

SELECT p.nome, p.data, p.data_limite,
       (SELECT count(*) FROM passeio_turma pt WHERE pt.passeio_id = p.id) AS turmas,
       (SELECT count(*) FROM passeio_aluno pa WHERE pa.passeio_id = p.id) AS alunos
FROM passeio p ORDER BY p.id;
