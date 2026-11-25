# Contexto do projeto: gerenciador de downloads de audio

## Objetivo

Construir um aplicativo de terminal em Python que leia uma remessa YAML, processe URLs de midia autorizada pelo usuario, extraia/converta o audio e organize os arquivos em uma pasta definida na remessa.

O programa deve ser um orquestrador robusto de ferramentas locais. Nao automatizar sites conversores, paginas com anuncios, redirecionamentos ou desafios de navegador.

## Escopo inicial

- Plataforma primaria: Ubuntu/Linux.
- Interface: terminal interativo.
- Entrada: arquivo YAML padronizado.
- Provedor inicial: `yt-dlp`, executado como processo separado.
- Conversao: binarios `ffmpeg` e `ffprobe`, executados como processos separados.
- Interface de terminal: preferencialmente Rich.
- CLI: argparse ou Typer, escolhendo uma unica opcao durante a implementacao.
- Comandos planejados:
  - `musicas diagnostico`
  - `musicas validar <remessa.yaml>`
  - `musicas baixar <remessa.yaml>`
  - `musicas retomar <remessa.yaml>`

## Formato preliminar da remessa

```yaml
pasta: "Rock Nacional"
formato: "mp3"
qualidade: 320

execucao:
  downloads_simultaneos: 5
  conversoes_simultaneas: 2
  tentativas: 3
  intervalo_tentativas: 3

musicas:
  - nome: "Musica 01"
    url: "https://www.youtube.com/watch?v=..."
```

Os limites aceitos pela primeira versao devem ser, no maximo, cinco downloads simultaneos e duas conversoes simultaneas. Valores ausentes usam esses limites como padrao; valores acima deles devem ser rejeitados ou reduzidos com aviso explicito.

## Pipeline e concorrencia

Usar duas filas independentes:

1. Validar remessa e itens.
2. Enfileirar itens validos para download.
3. Executar ate 5 downloads simultaneos.
4. Ao terminar cada download, enfileirar o arquivo para conversao.
5. Executar ate 2 conversoes simultaneas.
6. Mover o resultado concluido para a pasta final e registrar o resultado.

Controlar os dois limites separadamente, por exemplo com `asyncio.Semaphore`. Nao multiplicar acidentalmente a concorrencia usando varios fragmentos simultaneos por item; na primeira versao, manter a concorrencia interna de fragmentos do `yt-dlp` em 1.

Uma falha individual nao deve cancelar toda a remessa. Implementar novas tentativas com espera progressiva, registro do erro e possibilidade de retomada.

## Comportamento de download

Receber uma URL nao significa que o download sempre funcionara. O programa deve tentar processa-la e apresentar um resultado explicito. Possiveis impedimentos incluem:

- URL invalida ou video removido/privado;
- restricao de idade, regiao ou autenticacao;
- transmissao ao vivo ainda nao finalizada;
- indisponibilidade temporaria ou limitacao de requisicoes;
- mudancas no site que exijam uma atualizacao do `yt-dlp`;
- ausencia/incompatibilidade de `ffmpeg`, `ffprobe`, runtime JavaScript ou demais dependencias;
- formato ou fluxo de audio indisponivel;
- falta de espaco ou permissao de escrita.

O fluxo esperado para uma URL valida e acessivel e: obter o melhor fluxo de audio disponivel, salvar em area temporaria, converter para o formato solicitado e somente entao publicar o arquivo final. Nao prometer qualidade inexistente: converter uma fonte de menor qualidade para MP3 320 kbps nao melhora o audio original.

## Robustez

- Usar APIs/parametros estaveis do `yt-dlp` ou subprocessos com lista de argumentos; nunca concatenar comandos de shell.
- Nao depender do texto exato da saida humana do `yt-dlp` quando houver saida estruturada ou codigo de retorno.
- Manter downloads parciais e temporarios fora da pasta final.
- Publicar o arquivo final por movimentacao atomica quando possivel.
- Sanitizar nomes e impedir caminhos absolutos, `..` e escape da pasta de destino.
- Evitar sobrescrita silenciosa e detectar duplicatas.
- Verificar previamente versoes e disponibilidade das dependencias.
- Registrar sucesso, falha, tentativa, duracao, arquivo final e versoes das ferramentas.
- Permitir atualizacao independente do `yt-dlp` e do `ffmpeg`.
- Nunca executar arquivos baixados.
- Nao implementar contorno de DRM, controles de acesso, CAPTCHA ou bloqueios de seguranca.

## Uso autorizado

O fato de uma URL ser tecnicamente processavel nao comprova autorizacao. O usuario deve usar o programa somente em conteudo proprio, dominio publico, conteudo com licenca apropriada ou quando possuir permissao aplicavel.

Antes da primeira execucao, mostrar uma confirmacao informativa. Essa confirmacao nao substitui autorizacao e nao deve ser tratada como mecanismo juridico.

## Distribuicao

O programa podera ser compartilhado sem incluir musicas ou listas de links. A primeira distribuicao deve priorizar um pacote Python instalavel via `pipx`, com `pyproject.toml`, README, licenca e diagnostico de dependencias.

Inicialmente, nao empacotar tudo em um executavel unico. Manter `yt-dlp` e `ffmpeg` atualizaveis separadamente reduz fragilidade. Se binarios de terceiros forem incluidos no futuro, revisar e distribuir as licencas correspondentes.

## Fora do escopo inicial

- Automacao de sites conversores.
- Interface grafica.
- Windows e macOS como plataformas oficialmente suportadas.
- Download de playlists inteiras.
- Contorno de autenticacao, DRM ou restricoes da plataforma.
- Inclusao de audio protegido, cookies ou credenciais no repositorio.

## Criterios da primeira versao

- Validar uma remessa antes de iniciar.
- Pedir confirmacao interativa.
- Respeitar os limites 5/2.
- Continuar apos falhas individuais.
- Produzir nomes seguros e resultados deterministas.
- Gerar relatorio final de concluidos, ignorados e falhos.
- Retomar uma remessa interrompida sem repetir arquivos concluidos.
- Explicar claramente falhas de URL, dependencia, rede, conversao e armazenamento.
