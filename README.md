# Remessa de músicas

Aplicativo de terminal para organizar remessas de áudio de conteúdo que você pode baixar. Uma URL acessível não garante autorização de uso ou sucesso do download. Respeite os direitos do titular e os termos da plataforma.

## Instalação (Ubuntu/Linux)

Requer Python 3.11+, `ffmpeg`/`ffprobe`, `pipx` e, para suporte completo ao YouTube, um runtime JavaScript compatível com `yt-dlp-ejs` (Deno é recomendado pelo projeto yt-dlp). Consulte a [documentação de EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS) para instalar/configurar o runtime.

```bash
sudo apt install ffmpeg pipx
pipx install .
musics -dg
```

O pacote instala `yt-dlp[default]` com as dependências Python. Atualize-o regularmente com `pipx upgrade remessa-musicas`. Se o runtime for Node em vez de Deno, configure-o conforme a documentação oficial do yt-dlp.

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
