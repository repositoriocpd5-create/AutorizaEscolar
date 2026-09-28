-- =====================================================================
-- Autoriza Escolar — criação/ATUALIZAÇÃO das tabelas no Supabase (PostgreSQL)
--
-- Como usar: Supabase → SQL Editor → New query → cole este arquivo → Run.
-- Pode ser executado QUANTAS VEZES QUISER: cada bloco só é aplicado se o banco
-- estiver na versão anterior a ele (tabela alembic_version). Serve tanto para um
-- banco vazio quanto para atualizar um banco criado com versões anteriores.
--
-- Segurança: RLS é ativado em TODAS as tabelas, sem políticas. A API REST do
-- Supabase (chave publicável) não acessa nenhum dado; o sistema conecta
-- diretamente ao banco.
-- =====================================================================

BEGIN;

-- Migration d3cfedaae076
DO $mig$
BEGIN
  IF to_regclass('public.alembic_version') IS NULL THEN
    CREATE TABLE alembic_version (
        version_num VARCHAR(32) NOT NULL, 
        CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
    );
    
    -- Running upgrade  -> d3cfedaae076
    
    CREATE TABLE audit_log (
        id SERIAL NOT NULL, 
        data_hora TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
        ator_tipo VARCHAR(20) NOT NULL, 
        ator_id INTEGER, 
        acao VARCHAR(40) NOT NULL, 
        alvo VARCHAR(120), 
        detalhes JSON, 
        ip VARCHAR(45), 
        user_agent VARCHAR(300), 
        CONSTRAINT pk_audit_log PRIMARY KEY (id)
    );
    
    CREATE INDEX ix_audit_log_acao ON audit_log (acao);
    
    CREATE INDEX ix_audit_log_data_hora ON audit_log (data_hora);
    
    CREATE TABLE escola (
        id SERIAL NOT NULL, 
        nome VARCHAR(160) NOT NULL, 
        codigo VARCHAR(30) NOT NULL, 
        CONSTRAINT pk_escola PRIMARY KEY (id), 
        CONSTRAINT uq_escola_codigo UNIQUE (codigo)
    );
    
    CREATE TABLE passeio (
        id SERIAL NOT NULL, 
        public_id VARCHAR(36) NOT NULL, 
        nome VARCHAR(160) NOT NULL, 
        descricao TEXT, 
        destino VARCHAR(200) NOT NULL, 
        data DATE NOT NULL, 
        hora_saida TIME WITHOUT TIME ZONE NOT NULL, 
        hora_retorno TIME WITHOUT TIME ZONE NOT NULL, 
        local_saida VARCHAR(200) NOT NULL, 
        transporte VARCHAR(200), 
        orientacoes TEXT, 
        data_limite TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
        permite_alteracao BOOLEAN NOT NULL, 
        ativo BOOLEAN NOT NULL, 
        texto_declaracao TEXT NOT NULL, 
        versao_texto INTEGER NOT NULL, 
        criado_em TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
        CONSTRAINT pk_passeio PRIMARY KEY (id), 
        CONSTRAINT uq_passeio_public_id UNIQUE (public_id)
    );
    
    CREATE TABLE protocolo_sequencia (
        ano SERIAL NOT NULL, 
        ultimo INTEGER NOT NULL, 
        CONSTRAINT pk_protocolo_sequencia PRIMARY KEY (ano)
    );
    
    CREATE TABLE responsavel (
        id SERIAL NOT NULL, 
        public_id VARCHAR(36) NOT NULL, 
        nome VARCHAR(160) NOT NULL, 
        cpf_hash VARCHAR(64) NOT NULL, 
        cpf_final VARCHAR(2) NOT NULL, 
        data_nascimento_hash VARCHAR(64), 
        email VARCHAR(160), 
        telefone VARCHAR(30), 
        ativo BOOLEAN NOT NULL, 
        criado_em TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
        CONSTRAINT pk_responsavel PRIMARY KEY (id), 
        CONSTRAINT uq_responsavel_public_id UNIQUE (public_id)
    );
    
    CREATE UNIQUE INDEX ix_responsavel_cpf_hash ON responsavel (cpf_hash);
    
    CREATE TABLE tentativa_acesso (
        id SERIAL NOT NULL, 
        chave VARCHAR(100) NOT NULL, 
        sucesso BOOLEAN NOT NULL, 
        data_hora TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
        CONSTRAINT pk_tentativa_acesso PRIMARY KEY (id)
    );
    
    CREATE INDEX ix_tentativa_acesso_chave ON tentativa_acesso (chave);
    
    CREATE INDEX ix_tentativa_acesso_data_hora ON tentativa_acesso (data_hora);
    
    CREATE TABLE admin_usuario (
        id SERIAL NOT NULL, 
        nome VARCHAR(120) NOT NULL, 
        login VARCHAR(60) NOT NULL, 
        senha_hash VARCHAR(256) NOT NULL, 
        escola_id INTEGER, 
        ativo BOOLEAN NOT NULL, 
        CONSTRAINT pk_admin_usuario PRIMARY KEY (id), 
        CONSTRAINT fk_admin_usuario_escola_id_escola FOREIGN KEY(escola_id) REFERENCES escola (id), 
        CONSTRAINT uq_admin_usuario_login UNIQUE (login)
    );
    
    CREATE TABLE documento (
        id SERIAL NOT NULL, 
        public_id VARCHAR(36) NOT NULL, 
        protocolo VARCHAR(20) NOT NULL, 
        codigo_validacao VARCHAR(14) NOT NULL, 
        passeio_id INTEGER NOT NULL, 
        responsavel_id INTEGER NOT NULL, 
        data_registro TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
        versao_texto INTEGER NOT NULL, 
        conteudo JSON NOT NULL, 
        arquivo VARCHAR(200), 
        hash_sha256 VARCHAR(64), 
        data_geracao TIMESTAMP WITHOUT TIME ZONE, 
        CONSTRAINT pk_documento PRIMARY KEY (id), 
        CONSTRAINT fk_documento_passeio_id_passeio FOREIGN KEY(passeio_id) REFERENCES passeio (id), 
        CONSTRAINT fk_documento_responsavel_id_responsavel FOREIGN KEY(responsavel_id) REFERENCES responsavel (id), 
        CONSTRAINT uq_documento_protocolo UNIQUE (protocolo), 
        CONSTRAINT uq_documento_public_id UNIQUE (public_id)
    );
    
    CREATE UNIQUE INDEX ix_documento_codigo_validacao ON documento (codigo_validacao);
    
    CREATE INDEX ix_documento_passeio_id ON documento (passeio_id);
    
    CREATE INDEX ix_documento_responsavel_id ON documento (responsavel_id);
    
    CREATE TABLE turma (
        id SERIAL NOT NULL, 
        nome VARCHAR(40) NOT NULL, 
        ano VARCHAR(40) NOT NULL, 
        escola_id INTEGER NOT NULL, 
        CONSTRAINT pk_turma PRIMARY KEY (id), 
        CONSTRAINT fk_turma_escola_id_escola FOREIGN KEY(escola_id) REFERENCES escola (id)
    );
    
    CREATE INDEX ix_turma_escola_id ON turma (escola_id);
    
    CREATE TABLE aluno (
        id SERIAL NOT NULL, 
        public_id VARCHAR(36) NOT NULL, 
        matricula VARCHAR(30) NOT NULL, 
        nome VARCHAR(160) NOT NULL, 
        data_nascimento DATE, 
        sexo VARCHAR(1), 
        escola_id INTEGER NOT NULL, 
        turma_id INTEGER NOT NULL, 
        ativo BOOLEAN NOT NULL, 
        CONSTRAINT pk_aluno PRIMARY KEY (id), 
        CONSTRAINT fk_aluno_escola_id_escola FOREIGN KEY(escola_id) REFERENCES escola (id), 
        CONSTRAINT fk_aluno_turma_id_turma FOREIGN KEY(turma_id) REFERENCES turma (id), 
        CONSTRAINT uq_aluno_matricula UNIQUE (matricula), 
        CONSTRAINT uq_aluno_public_id UNIQUE (public_id)
    );
    
    CREATE INDEX ix_aluno_escola_id ON aluno (escola_id);
    
    CREATE INDEX ix_aluno_turma_id ON aluno (turma_id);
    
    CREATE TABLE passeio_turma (
        passeio_id INTEGER NOT NULL, 
        turma_id INTEGER NOT NULL, 
        CONSTRAINT pk_passeio_turma PRIMARY KEY (passeio_id, turma_id), 
        CONSTRAINT fk_passeio_turma_passeio_id_passeio FOREIGN KEY(passeio_id) REFERENCES passeio (id), 
        CONSTRAINT fk_passeio_turma_turma_id_turma FOREIGN KEY(turma_id) REFERENCES turma (id)
    );
    
    CREATE TABLE autorizacao (
        id SERIAL NOT NULL, 
        public_id VARCHAR(36) NOT NULL, 
        passeio_id INTEGER NOT NULL, 
        aluno_id INTEGER NOT NULL, 
        responsavel_id INTEGER NOT NULL, 
        situacao VARCHAR(20) NOT NULL, 
        data_hora TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
        versao_texto INTEGER NOT NULL, 
        origem VARCHAR(30) NOT NULL, 
        ip VARCHAR(45), 
        user_agent VARCHAR(300), 
        documento_id INTEGER, 
        CONSTRAINT pk_autorizacao PRIMARY KEY (id), 
        CONSTRAINT fk_autorizacao_aluno_id_aluno FOREIGN KEY(aluno_id) REFERENCES aluno (id), 
        CONSTRAINT fk_autorizacao_documento_id_documento FOREIGN KEY(documento_id) REFERENCES documento (id), 
        CONSTRAINT fk_autorizacao_passeio_id_passeio FOREIGN KEY(passeio_id) REFERENCES passeio (id), 
        CONSTRAINT fk_autorizacao_responsavel_id_responsavel FOREIGN KEY(responsavel_id) REFERENCES responsavel (id), 
        CONSTRAINT uq_autorizacao_passeio_aluno UNIQUE (passeio_id, aluno_id), 
        CONSTRAINT uq_autorizacao_public_id UNIQUE (public_id)
    );
    
    CREATE INDEX ix_autorizacao_aluno_id ON autorizacao (aluno_id);
    
    CREATE INDEX ix_autorizacao_passeio_id ON autorizacao (passeio_id);
    
    CREATE INDEX ix_autorizacao_responsavel_id ON autorizacao (responsavel_id);
    
    CREATE TABLE passeio_aluno (
        id SERIAL NOT NULL, 
        passeio_id INTEGER NOT NULL, 
        aluno_id INTEGER NOT NULL, 
        CONSTRAINT pk_passeio_aluno PRIMARY KEY (id), 
        CONSTRAINT fk_passeio_aluno_aluno_id_aluno FOREIGN KEY(aluno_id) REFERENCES aluno (id), 
        CONSTRAINT fk_passeio_aluno_passeio_id_passeio FOREIGN KEY(passeio_id) REFERENCES passeio (id), 
        CONSTRAINT uq_passeio_aluno_par UNIQUE (passeio_id, aluno_id)
    );
    
    CREATE INDEX ix_passeio_aluno_aluno_id ON passeio_aluno (aluno_id);
    
    CREATE INDEX ix_passeio_aluno_passeio_id ON passeio_aluno (passeio_id);
    
    CREATE TABLE responsavel_aluno (
        id SERIAL NOT NULL, 
        responsavel_id INTEGER NOT NULL, 
        aluno_id INTEGER NOT NULL, 
        tipo_vinculo VARCHAR(30) NOT NULL, 
        responsavel_legal BOOLEAN NOT NULL, 
        ativo BOOLEAN NOT NULL, 
        CONSTRAINT pk_responsavel_aluno PRIMARY KEY (id), 
        CONSTRAINT fk_responsavel_aluno_aluno_id_aluno FOREIGN KEY(aluno_id) REFERENCES aluno (id), 
        CONSTRAINT fk_responsavel_aluno_responsavel_id_responsavel FOREIGN KEY(responsavel_id) REFERENCES responsavel (id), 
        CONSTRAINT uq_responsavel_aluno_par UNIQUE (responsavel_id, aluno_id)
    );
    
    CREATE INDEX ix_responsavel_aluno_aluno_id ON responsavel_aluno (aluno_id);
    
    CREATE INDEX ix_responsavel_aluno_responsavel_id ON responsavel_aluno (responsavel_id);
    
    CREATE TABLE autorizacao_historico (
        id SERIAL NOT NULL, 
        autorizacao_id INTEGER NOT NULL, 
        situacao_anterior VARCHAR(20), 
        situacao_nova VARCHAR(20) NOT NULL, 
        data_hora TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
        responsavel_id INTEGER, 
        admin_id INTEGER, 
        documento_id INTEGER, 
        motivo VARCHAR(300), 
        ip VARCHAR(45), 
        user_agent VARCHAR(300), 
        CONSTRAINT pk_autorizacao_historico PRIMARY KEY (id), 
        CONSTRAINT fk_autorizacao_historico_admin_id_admin_usuario FOREIGN KEY(admin_id) REFERENCES admin_usuario (id), 
        CONSTRAINT fk_autorizacao_historico_autorizacao_id_autorizacao FOREIGN KEY(autorizacao_id) REFERENCES autorizacao (id), 
        CONSTRAINT fk_autorizacao_historico_documento_id_documento FOREIGN KEY(documento_id) REFERENCES documento (id), 
        CONSTRAINT fk_autorizacao_historico_responsavel_id_responsavel FOREIGN KEY(responsavel_id) REFERENCES responsavel (id)
    );
    
    CREATE INDEX ix_autorizacao_historico_autorizacao_id ON autorizacao_historico (autorizacao_id);
    
    CREATE TABLE documento_item (
        id SERIAL NOT NULL, 
        documento_id INTEGER NOT NULL, 
        autorizacao_id INTEGER NOT NULL, 
        situacao VARCHAR(20) NOT NULL, 
        CONSTRAINT pk_documento_item PRIMARY KEY (id), 
        CONSTRAINT fk_documento_item_autorizacao_id_autorizacao FOREIGN KEY(autorizacao_id) REFERENCES autorizacao (id), 
        CONSTRAINT fk_documento_item_documento_id_documento FOREIGN KEY(documento_id) REFERENCES documento (id)
    );
    
    CREATE INDEX ix_documento_item_autorizacao_id ON documento_item (autorizacao_id);
    
    CREATE INDEX ix_documento_item_documento_id ON documento_item (documento_id);
    
    INSERT INTO alembic_version (version_num) VALUES ('d3cfedaae076');
  END IF;
END
$mig$;

-- Migration d758e86b8bad
DO $mig$
BEGIN
  IF to_regclass('public.alembic_version') IS NOT NULL AND EXISTS (SELECT 1 FROM alembic_version WHERE version_num = 'd3cfedaae076') THEN
    -- Running upgrade d3cfedaae076 -> d758e86b8bad
    
    CREATE TABLE configuracao (
        chave VARCHAR(60) NOT NULL, 
        valor TEXT, 
        atualizado_em TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
        CONSTRAINT pk_configuracao PRIMARY KEY (chave)
    );
    
    ALTER TABLE passeio ADD COLUMN texto_termo TEXT DEFAULT 'Declaro que sou responsável legal pelo(s) aluno(s) selecionado(s) e confirmo esta autorização.' NOT NULL;
    
    ALTER TABLE passeio ADD COLUMN prazo_alteracao_horas INTEGER;
    
    ALTER TABLE passeio ADD COLUMN imagem VARCHAR(80);
    
    UPDATE alembic_version SET version_num='d758e86b8bad' WHERE alembic_version.version_num = 'd3cfedaae076';
  END IF;
END
$mig$;

-- Migration 4d5523b3c2e3
DO $mig$
BEGIN
  IF to_regclass('public.alembic_version') IS NOT NULL AND EXISTS (SELECT 1 FROM alembic_version WHERE version_num = 'd758e86b8bad') THEN
    -- Running upgrade d758e86b8bad -> 4d5523b3c2e3
    
    ALTER TABLE passeio ADD COLUMN ilustracao VARCHAR(30) DEFAULT 'cinema' NOT NULL;
    
    UPDATE alembic_version SET version_num='4d5523b3c2e3' WHERE alembic_version.version_num = 'd758e86b8bad';
  END IF;
END
$mig$;

-- Migration 9bfba8258bec
DO $mig$
BEGIN
  IF to_regclass('public.alembic_version') IS NOT NULL AND EXISTS (SELECT 1 FROM alembic_version WHERE version_num = '4d5523b3c2e3') THEN
    -- Running upgrade 4d5523b3c2e3 -> 9bfba8258bec
    
    CREATE TABLE midia (
        nome VARCHAR(60) NOT NULL, 
        dados BYTEA NOT NULL, 
        criado_em TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
        CONSTRAINT pk_midia PRIMARY KEY (nome)
    );
    
    UPDATE alembic_version SET version_num='9bfba8258bec' WHERE alembic_version.version_num = '4d5523b3c2e3';
  END IF;
END
$mig$;

-- Migration 1b0e7f733da3
DO $mig$
BEGIN
  IF to_regclass('public.alembic_version') IS NOT NULL AND EXISTS (SELECT 1 FROM alembic_version WHERE version_num = '9bfba8258bec') THEN
    -- Running upgrade 9bfba8258bec -> 1b0e7f733da3
    
    ALTER TABLE public."alembic_version" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."escola" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."turma" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."responsavel" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."aluno" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."responsavel_aluno" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."passeio" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."passeio_turma" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."passeio_aluno" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."autorizacao" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."autorizacao_historico" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."documento" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."documento_item" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."protocolo_sequencia" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."admin_usuario" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."audit_log" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."tentativa_acesso" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."configuracao" ENABLE ROW LEVEL SECURITY;
    
    ALTER TABLE public."midia" ENABLE ROW LEVEL SECURITY;
    
    UPDATE alembic_version SET version_num='1b0e7f733da3' WHERE alembic_version.version_num = '9bfba8258bec';
  END IF;
END
$mig$;

-- Migration efba62287685
DO $mig$
BEGIN
  IF to_regclass('public.alembic_version') IS NOT NULL AND EXISTS (SELECT 1 FROM alembic_version WHERE version_num = '1b0e7f733da3') THEN
    -- Running upgrade 1b0e7f733da3 -> efba62287685
    
    ALTER TABLE admin_usuario ADD COLUMN email VARCHAR(160);
    
    ALTER TABLE admin_usuario ALTER COLUMN senha_hash DROP NOT NULL;
    
    ALTER TABLE admin_usuario ADD CONSTRAINT uq_admin_usuario_email UNIQUE (email);
    
    UPDATE alembic_version SET version_num='efba62287685' WHERE alembic_version.version_num = '1b0e7f733da3';
  END IF;
END
$mig$;

-- Migration 6802f6d3f643
DO $mig$
BEGIN
  IF to_regclass('public.alembic_version') IS NOT NULL AND EXISTS (SELECT 1 FROM alembic_version WHERE version_num = 'efba62287685') THEN
    -- Running upgrade efba62287685 -> 6802f6d3f643
    
    ALTER TABLE admin_usuario ADD COLUMN supabase_id VARCHAR(40);
    
    ALTER TABLE admin_usuario ADD COLUMN perfil VARCHAR(10) DEFAULT 'ADMIN' NOT NULL;
    
    ALTER TABLE admin_usuario ADD COLUMN permissoes VARCHAR(200) DEFAULT '' NOT NULL;
    
    ALTER TABLE admin_usuario ADD COLUMN criado_em TIMESTAMP WITHOUT TIME ZONE;
    
    UPDATE alembic_version SET version_num='6802f6d3f643' WHERE alembic_version.version_num = 'efba62287685';
  END IF;
END
$mig$;

-- Migration ac8442cb4873
DO $mig$
BEGIN
  IF to_regclass('public.alembic_version') IS NOT NULL AND EXISTS (SELECT 1 FROM alembic_version WHERE version_num = '6802f6d3f643') THEN
    -- Running upgrade 6802f6d3f643 -> ac8442cb4873
    
    ALTER TABLE escola ADD COLUMN inep VARCHAR(8);
    
    ALTER TABLE escola ADD COLUMN cnpj VARCHAR(18);
    
    ALTER TABLE escola ADD COLUMN email VARCHAR(160);
    
    ALTER TABLE escola ADD COLUMN telefone VARCHAR(30);
    
    ALTER TABLE escola ADD COLUMN ramal VARCHAR(10);
    
    ALTER TABLE escola ADD COLUMN diretor VARCHAR(160);
    
    ALTER TABLE escola ADD COLUMN vice_diretor VARCHAR(160);
    
    ALTER TABLE escola ADD COLUMN modalidade VARCHAR(120);
    
    ALTER TABLE escola ADD COLUMN turno VARCHAR(40);
    
    ALTER TABLE escola ADD COLUMN qtd_salas INTEGER;
    
    ALTER TABLE escola ADD COLUMN logradouro VARCHAR(200);
    
    ALTER TABLE escola ADD COLUMN numero VARCHAR(20);
    
    ALTER TABLE escola ADD COLUMN complemento VARCHAR(120);
    
    ALTER TABLE escola ADD COLUMN bairro VARCHAR(120);
    
    ALTER TABLE escola ADD COLUMN cidade VARCHAR(80);
    
    ALTER TABLE escola ADD COLUMN uf VARCHAR(2);
    
    ALTER TABLE escola ADD COLUMN cep VARCHAR(9);
    
    ALTER TABLE escola ADD COLUMN maps_link VARCHAR(300);
    
    ALTER TABLE escola ADD COLUMN ativo BOOLEAN DEFAULT true NOT NULL;
    
    ALTER TABLE escola ADD CONSTRAINT uq_escola_inep UNIQUE (inep);
    
    UPDATE alembic_version SET version_num='ac8442cb4873' WHERE alembic_version.version_num = '6802f6d3f643';
  END IF;
END
$mig$;

COMMIT;

-- Versão final esperada:
SELECT version_num AS versao_do_banco FROM alembic_version;
