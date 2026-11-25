# Remessa de músicas

Aplicativo de terminal para organizar remessas de áudio de conteúdo que você pode baixar. Uma URL acessível não garante autorização de uso ou sucesso do download. Respeite os direitos do titular e os termos da plataforma.

## Instalação (Ubuntu/Linux)

Requer Python 3.11+, `ffmpeg`/`ffprobe`, `pipx` e, para suporte completo ao YouTube, um runtime JavaScript compatível com `yt-dlp-ejs` (Deno é recomendado pelo projeto yt-dlp). Consulte a [documentação de EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS) para instalar/configurar o runtime.

```bash
sudo apt update
sudo apt install ffmpeg pipx
pipx ensurepath
```

Feche e abra o terminal após `pipx ensurepath`. Na raiz do projeto (onde fica `pyproject.toml`), instale:

```bash
pipx install --include-deps .
yt-dlp --version
musics -dg
```

### Instalação do yt-dlp

O comando `pipx install --include-deps .` instala o projeto e sua dependência `yt-dlp[default]`. A opção `--include-deps` disponibiliza também o executável `yt-dlp` no terminal, necessário porque o programa o chama como processo externo. Não é preciso instalar outra cópia quando essa opção é utilizada.

Se você já instalou o projeto com `pipx install .` e o diagnóstico informa que `yt-dlp` está ausente, execute novamente na raiz do projeto:

```bash
pipx install --force --include-deps .
yt-dlp --version
musics -dg
```

Para atualizar apenas o yt-dlp dentro do ambiente do projeto:

```bash
pipx runpip remessa-musicas install --upgrade "yt-dlp[default]"
yt-dlp --version
```

Para atualizar o projeto a partir dos arquivos locais, execute `pipx install --force --include-deps .` novamente após obter a versão desejada do código.

Como alternativa, se preferir manter o executável do yt-dlp instalado separadamente, use os comandos abaixo **em vez** da instalação com `--include-deps`:

```bash
pipx install .
pipx install "yt-dlp[default]"
yt-dlp --version
```

Nessa alternativa, atualize o executável com `pipx upgrade yt-dlp`. Evite misturar os dois métodos para não criar conflitos entre executáveis com o mesmo nome.

O extra `[default]` inclui as dependências Python recomendadas pelo yt-dlp, incluindo os componentes EJS; `ffmpeg`/`ffprobe` e o runtime JavaScript precisam ser instalados separadamente. Se o runtime for Node em vez de Deno, configure-o conforme a [documentação oficial de EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

Referências: [instalação oficial do yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/Installation) e [exposição de comandos das dependências pelo pipx](https://pipx.pypa.io/stable/how-to/expose-apps.html).

## Uso

Edite uma cópia de `exemplos/remessa.yaml` e use:

```bash
musics -v minha-remessa.yaml
musics -d minha-remessa.yaml
musics -r minha-remessa.yaml
```

Os arquivos são salvos em `downloads/<pasta>/` no diretório de onde o comando é executado. Use `-de /caminho/para/musicas` ou `--destination` para escolher a pasta base. Dentro da remessa fica `resultado.json`, com o status de cada item; não edite esse arquivo manualmente. A opção `-y`/`--yes` dispensa a pergunta interativa, mas somente use para arquivos cujo conteúdo você conhece.

| Operação | Flag curta | Flag longa |
| --- | --- | --- |
| Diagnosticar dependências | `-dg` | `--diagnose` |
| Validar remessa | `-v ARQUIVO` | `--validate ARQUIVO` |
| Baixar remessa | `-d ARQUIVO` | `--download ARQUIVO` |
| Retomar remessa | `-r ARQUIVO` | `--resume ARQUIVO` |
| Escolher destino | `-de PASTA` | `--destination PASTA` |
| Confirmar execução | `-y` | `--yes` |
| Exibir ajuda | `-h` | `--help` |

Escolha uma operação por execução. As formas `-dg` e `-de` evitam a colisão com `-d`. Exemplo: `musics -d minha-remessa.yaml -de ./audio -y`. Os nomes dos comandos estão em inglês; mensagens e ajuda permanecem em português. As chaves do YAML continuam em português.

Durante o processamento, um indicador giratório mostra que há tarefas em andamento. Ele indica atividade, sem estimar porcentagem, e é desativado automaticamente quando a saída é redirecionada para arquivo. Não requer uma flag adicional.

Até cinco itens podem ser baixados ao mesmo tempo e até dois convertidos. Valores menores podem ser definidos no YAML. `original` preserva o contêiner de áudio obtido, como `.webm` ou `.m4a`. Nos demais formatos, a conversão pode perder qualidade e um bitrate maior não recupera detalhes ausentes da fonte.

Ao interromper com Ctrl+C, os downloads incompletos ficam em uma área de trabalho dentro da remessa; `musics -r ARQUIVO` reprocessa itens ainda não concluídos. O resultado final de cada item só é publicado após terminar a conversão. Atualizações da plataforma, indisponibilidade de vídeos e restrições de acesso podem causar falhas individuais.
