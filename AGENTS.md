# Forge Mods: instruções para colaboradores e agentes

## Objetivo e decisões do usuário

- Aplicativo desktop próprio para Linux; interface em português, inspirada na Steam clássica/Half-Life.
- Descobrir jogos Steam e preservar biblioteca, histórico e perfis fora da pasta dos jogos.
- Instalar, ativar, desativar e gerenciar mods. Importar um mod sem oferecer ativação para formatos já suportados não atende ao objetivo.
- Mods importados começam desativados. Se faltar uma dependência conhecida, exibir seu nome e impedir ativação até que ela esteja instalada e ativa quando aplicável. Baixar ou importar a dependência não equivale a ativá-la.
- Downloads e integração de conta Nexus foram adiados pelo usuário. Não iniciar essa integração sem nova instrução.

## Fluxo obrigatório de manutenção

Por solicitação explícita do usuário, após cada conjunto coerente de alterações:

1. Atualizar `README.md` e `CHANGELOG.md` com comportamento, uso, limites e validação reais. Atualizar este `AGENTS.md` quando mudar arquitetura, fluxo, restrições ou decisões; não criar alterações vazias.
2. Executar os testes relevantes e corrigir falhas antes de concluir.
3. Revisar `git diff`, incluir apenas arquivos do projeto, criar um commit descritivo e enviar ao remoto `origin`, configurado como `git@github.com:Mattdolne/forge_mods.git`.
4. Confirmar que o commit remoto corresponde ao local. Nunca usar force push ou reescrever histórico sem instrução específica.
5. Se uma permissão ou autenticação impedir o push, preservar o trabalho e informar exatamente o que ficou pendente; nunca alegar publicação sem verificação.

Essa orientação é autorização para commits e pushes das mudanças solicitadas neste projeto; não é autorização para tarefas novas ou divulgação de dados pessoais.

## Arquitetura

- `app.py`: janela Qt/PySide6, estados, ações e mensagens.
- `core.py`: descoberta Steam, SQLite, dependências, perfis, ativação/desativação e remoção.
- `skyrim.py`: leitura limitada do cabeçalho TES4/MAST e edição de listas de plugins no prefixo Proton.
- `transactions.py`: snapshots de arquivos, journal de rollback e marcador de commit coordenado com SQLite. Recuperar operações interrompidas antes de usar a biblioteca.
- `tests/test_core.py`: instalações e prefixos sintéticos em diretórios temporários.
- `tests/test_ui.py`: interações reais Qt em modo offscreen, com fixtures sintéticas.

Preservar nomes, codificação, comentários e entradas de outros mods nos arquivos de configuração. Bloquear caminhos inseguros, symlinks e sobrescritas conflitantes. Não ignorar dependências para fazer um teste passar.

## Dependências

- Ler masters declarados em ESP/ESM/ESL e considerar dependências implícitas do jogo.
- SkyUI e DLLs em SKSE/Plugins exigem SKSE; presença do loader, DLL de runtime e script SKSE é uma verificação de instalação, não prova de versão compatível nem de execução.
- Requisitos descritos apenas no Nexus não são inferidos integralmente de um ZIP. Até haver API, expor cadastro manual por nome exato da biblioteca. Não inventar requisitos nem alegar cobertura completa.
- Ordenação local verifica masters/dependências; não equivale à otimização ou às regras da masterlist do LOOT.

## Validação e dados

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v
```

Usar `FORGE_DATA_DIR` temporário para testes e prévias. Nunca ativar mods nos jogos reais do usuário apenas para validar código. Não versionar ZIPs de terceiros, arquivos do jogo, banco pessoal, credenciais, backups ou capturas com caminhos e biblioteca pessoais. A captura `preview.png` deve usar dados de demonstração.
