# Histórico de alterações

## 0.3 — 2026-11-02

- Importação de arquivos 7z com libarchive, incluindo arquivos solid e conteúdo Unicode, pelo mesmo fluxo de instalação, dependências e ativação usado por ZIP.
- Seletor aceita ZIP/7z e botão passa a se chamar Importar mod.
- Validação compartilhada de caminhos, links, duplicatas e limite de 8 GiB. Verifica também o tamanho efetivamente extraído e recusa arquivos protegidos por senha.
- Novos testes de importação/ativação/desativação 7z e do seletor Qt. CI instala libarchive e 7zip para executar as fixtures.

## 0.2 — 2026-11-02

- Instalação/ativação real de plugins ESP/ESM/ESL no Proton para Skyrim e Skyrim SE, com edição de listas de plugins e preservação de comentários/entradas alheias.
- Leitura de masters TES4, dependências de SKSE e cadastro de outros requisitos pelo nome do mod. Mods importados ficam desativados; requisitos ausentes/inativos bloqueiam ativação e têm seus nomes exibidos.
- Aba Plugins, seleção de prefixo, ordem manual validada e proteção contra desativar dependências em uso.
- Remoção da biblioteca, limpeza de referências dos perfis e manutenção do histórico.
- Restauração de perfis em ordem de dependências, backups, rollback de erros e journal para recuperação de operações interrompidas.
- Trava de instância única, testes de núcleo e interface e workflow de CI.
- Instalação explícita das bibliotecas gráficas do Qt no Ubuntu do CI, corrigindo a falha de importação por ausência de `libEGL.so.1`.
- README e AGENTS descrevem capacidades, limites e o fluxo solicitado de atualizar documentação e publicar mudanças no GitHub.

## 0.1 — 2026-11-02

- Detecção de bibliotecas Steam, biblioteca local SQLite, importação ZIP, perfis e histórico.
- Ativação/desativação inicial de arquivos de dados, hashes e bloqueio de conflitos.
- Tema Steam clássico/Half-Life e mudança do projeto para Documentos/projetos.
- Importação de pacotes com plugins, ainda sem ativação na versão 0.1.
