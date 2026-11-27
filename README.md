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

```yaml
formato: "mp3"
qualidade: 192
albuns:
  - nome: "Álbum 1"
    musicas:
      - nome: "Primeira faixa"
        url: "https://www.youtube.com/watch?v=ID_1"
      - nome: "Segunda faixa"
        url: "https://www.youtube.com/watch?v=ID_2"
  - nome: "Álbum 2"
    musicas:
      - nome: "Primeira faixa"
        url: "https://www.youtube.com/watch?v=ID_3"
```

Cada álbum vira uma pasta na biblioteca de músicas. Nomes de faixas podem se repetir em álbuns diferentes; no mesmo álbum, apenas a primeira ocorrência é considerada. O formato anterior (`pasta` e `musicas` na raiz) deve ser convertido para `albuns`.

Links repetidos no mesmo álbum também geram um aviso: somente a primeira faixa é considerada, mesmo que os nomes sejam diferentes. URLs `youtu.be`, `watch?v=`, `shorts`, `embed` e `live` que apontem para o mesmo vídeo são reconhecidas; parâmetros de playlist, rádio e tempo não criam uma faixa diferente. A verificação ocorre na leitura da lista e antes do download, inclusive após editar links na retomada. O mesmo vídeo pode aparecer em álbuns diferentes. Essa verificação considera a lista da execução, sem consultar um histórico global de downloads.

```bash
musics -v minha-remessa.yaml
musics -d minha-remessa.yaml
musics -r minha-remessa.yaml
```

### Retomada de falhas e interrupções

O programa mantém automaticamente `downloads/retomada.json` no diretório de onde você executa os comandos. Essa fila reúne faixas pendentes de diferentes remessas (YAML, CSV, TXT ou cadastro interativo), incluindo falhas de download, conversão e publicação do áudio. Cada item preserva álbum, nome, URL, formato, qualidade, configurações e destino. A fila é atualizada a cada resultado: faixas concluídas são removidas; falhas e faixas interrompidas permanecem. Execute no mesmo diretório para encontrar a fila padrão.

```bash
musics -r                         # retoma somente a primeira faixa pendente
musics -r -dir                    # retoma todas as faixas da fila padrão
musics -r -dir outra/retomada.json # retoma uma fila indicada
musics -r -dir lista.csv          # retoma uma lista CSV (também aceita TXT e YAML)
musics -r remessa.yaml            # forma anterior continua disponível
```

Use `-y` para dispensar a confirmação ou `-de PASTA` para escolher outro destino. Se não houver pendências, o programa informa isso e encerra sem baixar. O arquivo JSON é gerenciado pelo programa; conserve-o separado dos logs de sessão. Os arquivos de retomada são criados a partir das execuções desta versão; falhas anteriores podem ser processadas novamente com a lista original para entrar na fila.

Na retomada interativa, após confirmar a execução, o programa pergunta se você deseja alterar algum link. Se responder `s`, mostra álbum, faixa e URL atual de cada item e pede uma nova URL. Pressione Enter para manter o link da faixa. Links inválidos geram um aviso e uma nova pergunta. A URL substituta é salva na fila de retomada e será usada nas próximas tentativas se a faixa falhar novamente. Isso funciona com `musics -r -dir`, com um arquivo indicado e também com `musics -r`. CSV, TXT e YAML originais não são alterados; para reutilizar a substituição, retome pela fila JSON. A opção `-y` pula a edição e usa os links já salvos.

### Adição interativa e importação de listas

Depois de instalar ou atualizar o projeto com `pipx install --force --include-deps .`, execute `music add`. O programa pede o nome do álbum, o nome da faixa e a URL; valida os dados e inicia o download imediatamente em formato MP3 (192 kb/s). `musics add` também funciona.

Para várias faixas, crie um arquivo CSV UTF-8 com o cabeçalho `album,nome,url`:

```csv
album,nome,url
Álbum 1,Primeira faixa,https://www.youtube.com/watch?v=ID_1
Álbum 1,Segunda faixa,https://www.youtube.com/watch?v=ID_2
Álbum 2,Outra faixa,https://www.youtube.com/watch?v=ID_3
```

Ou um TXT UTF-8, com uma faixa por linha no formato `álbum | nome | URL` (linhas vazias ou iniciadas por `#` são ignoradas):

```text
Álbum 1 | Primeira faixa | https://www.youtube.com/watch?v=ID_1
Álbum 2 | Outra faixa | https://www.youtube.com/watch?v=ID_3
```

```bash
music add -dir lista.csv
music add -dir lista.txt
music add -dir               # pergunta o caminho do arquivo
music add -dir lista.csv -y  # dispensa a confirmação da importação
```

Os nomes de álbum podem se repetir entre linhas; as faixas serão agrupadas na mesma pasta. Se o nome de uma música se repetir no mesmo álbum, o programa avisa e ignora as ocorrências posteriores, preservando a primeira. Também é possível usar `-de PASTA` para escolher outro destino. Uma nova execução com a mesma lista retoma faixas concluídas pelo mesmo comando; os logs e o estado ficam em `downloads/`.

Os áudios são salvos na pasta de músicas do usuário (`Músicas/<álbum>` no Windows em português; no Linux, segue `XDG_MUSIC_DIR`; no macOS, `~/Music`). Use `-de /caminho/para/musicas` ou `--destination` para escolher outra pasta base. Os logs ficam em `downloads/<nome-do-yaml>-<id>/sessoes/` no diretório de onde o comando é executado. O identificador evita misturar remessas com nomes de arquivo iguais em locais diferentes. O programa mantém somente as três sessões mais recentes de logs; as antigas são removidas automaticamente após a execução. O estado `downloads/<nome-do-yaml>-<id>/resultado.json` fica separado dos logs e é preservado para permitir `-r`. Não edite esse arquivo manualmente. A opção `-y`/`--yes` dispensa a pergunta interativa, mas somente use para arquivos cujo conteúdo você conhece.

| Operação | Flag curta | Flag longa |
| --- | --- | --- |
| Diagnosticar dependências | `-dg` | `--diagnose` |
| Validar remessa | `-v ARQUIVO` | `--validate ARQUIVO` |
| Baixar remessa | `-d ARQUIVO` | `--download ARQUIVO` |
| Retomar uma faixa pendente | `-r` | `--resume` |
| Retomar uma lista ou fila | `-r -dir [ARQUIVO]` | `--resume --directory [ARQUIVO]` |
| Retomar remessa indicada | `-r ARQUIVO` | `--resume ARQUIVO` |
| Escolher destino | `-de PASTA` | `--destination PASTA` |
| Confirmar execução | `-y` | `--yes` |
| Exibir ajuda | `-h` | `--help` |

Escolha uma operação por execução. As formas `-dg` e `-de` evitam a colisão com `-d`. Exemplo: `musics -d minha-remessa.yaml -de ./audio -y`. Os nomes dos comandos estão em inglês; mensagens e ajuda permanecem em português. As chaves do YAML continuam em português.

### Variações e erros ao digitar flags

As flags aceitam um ou dois hífens e letras maiúsculas ou minúsculas: `--dir`, `-directory`, `-download` e `--DOWNLOAD` funcionam como suas formas documentadas. Hífens tipográficos copiados de mensagens (`–` e `—`) também são reconhecidos. Isso vale para `music add` e para as operações de `musics`, inclusive retomada. Caminhos e valores preservam sua escrita original; para um nome de arquivo que começa com hífen, use `--download=-lista.yaml` ou um caminho como `./-lista.yaml`.

Se você escrever `musics --downlod lista.yaml`, o programa informa que a flag é desconhecida e sugere `--download`. Erros de escrita recebem sugestões para você escolher e executar novamente; abreviações parciais e flags curtas combinadas, como `-dy`, não são aceitas. Quando faltar um valor ou houver conflito entre operações, a mensagem explica o problema em português.

Durante o processamento, um indicador giratório mostra que há tarefas em andamento. Ele indica atividade, sem estimar porcentagem, e é desativado automaticamente quando a saída é redirecionada para arquivo. Não requer uma flag adicional.

Até cinco itens podem ser baixados ao mesmo tempo e até dois convertidos. Valores menores podem ser definidos no YAML. `original` preserva o contêiner de áudio obtido, como `.webm` ou `.m4a`. Nos demais formatos, a conversão pode perder qualidade e um bitrate maior não recupera detalhes ausentes da fonte.

Ao interromper com Ctrl+C, arquivos temporários são descartados; `musics -r ARQUIVO` baixa novamente itens ainda não concluídos. O resultado final de cada item só é publicado após terminar a conversão. Atualizações da plataforma, indisponibilidade de vídeos e restrições de acesso podem causar falhas individuais.
