<<<<<<< HEAD
# Remessa de músicas

Aplicativo de terminal para organizar remessas de áudio de conteúdo que você pode baixar. Uma URL acessível não garante autorização de uso ou sucesso do download. Respeite os direitos do titular e os termos da plataforma.

## Instalação (Ubuntu/Linux)

Requer Python 3.11+, `ffmpeg`/`ffprobe`, `pipx` e, para suporte completo ao YouTube, um runtime JavaScript compatível com `yt-dlp-ejs` (Deno é recomendado pelo projeto yt-dlp). Consulte a [documentação de EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS) para instalar/configurar o runtime.

```bash
sudo apt install ffmpeg pipx
pipx install .
musicas diagnostico
```

O pacote instala `yt-dlp[default]` com as dependências Python. Atualize-o regularmente com `pipx upgrade remessa-musicas`. Se o runtime for Node em vez de Deno, configure-o conforme a documentação oficial do yt-dlp.

## Uso

Edite uma cópia de `exemplos/remessa.yaml` e use:

```bash
musicas validar minha-remessa.yaml
musicas baixar minha-remessa.yaml
musicas retomar minha-remessa.yaml
```

Os arquivos são salvos em `downloads/<pasta>/` no diretório de onde o comando é executado. Use `--destino /caminho/para/musicas` para escolher a pasta base. Dentro da remessa fica `resultado.json`, com o status de cada item; não edite esse arquivo manualmente. A opção `--sim` dispensa a pergunta interativa, mas somente use para arquivos cujo conteúdo você conhece.

Até cinco itens podem ser baixados ao mesmo tempo e até dois convertidos. Valores menores podem ser definidos no YAML. `original` preserva o contêiner de áudio obtido, como `.webm` ou `.m4a`. Nos demais formatos, a conversão pode perder qualidade e um bitrate maior não recupera detalhes ausentes da fonte.

Ao interromper com Ctrl+C, os downloads incompletos ficam em uma área de trabalho dentro da remessa; `retomar` reprocessa itens ainda não concluídos. O resultado final de cada item só é publicado após terminar a conversão. Atualizações da plataforma, indisponibilidade de vídeos e restrições de acesso podem causar falhas individuais.
=======
# MusicDownloads
>>>>>>> 31942c584e0805b1adb7e4ac3234a76c1c5ea51e
