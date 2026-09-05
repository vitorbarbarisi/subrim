# Ditado

Página estática para treinar as frases de uma coleção, no Chrome do celular. Mostra a imagem em
largura total e, embaixo, um campo com a frase em chinês; acertando, o item é marcado como feito e
o carrossel avança.

São **três jogos**, que se alternam a cada frase — 1, 2, 3, 1, 2, 3… — então um bloco de 150 sai
50 de cada:

| Jogo | O que aparece | Como se joga |
|---|---|---|
| 1 | Só o campo de texto | Digitar a frase e confirmar com Enter |
| 2 | Grid de botões com **pinyin** | Tocar as palavras na ordem da frase |
| 3 | Grid de botões com os **caracteres** embaralhados | Tocar os caracteres na ordem |

Nos jogos 2 e 3 o campo é preenchido pelos toques, não pelo teclado: cada acerto escreve o pedaço
e apaga o botão do grid; ao completar a frase, o carrossel avança sozinho. Errar deixa o botão
vermelho e não escreve nada — o campo é sempre um começo correto da frase, e por isso não há (nem
precisa haver) como desfazer.

A página em si continua independente do resto do repo: sem build, sem dependência de runtime, é um
`index.html`. O que os jogos 2 e 3 precisam — segmentação em palavras, pinyin, distratores,
embaralhamento — é calculado pelo `make_bundle.py` e viaja embutido no arquivo, porque no celular
não há rede nem servidor para consultar. Ver `wordgrid.py`.

## Qual dos dois modos usar

**No celular, use os bundles.** São arquivos `.html` autocontidos, com as imagens embutidas:

```bash
python3 dictation/make_bundle.py warehouse/collections/0_r36s
```

Isso cobre **todas** as entradas do `index.json`, em blocos de 150, gravando aqui em `dictation/`:

```
dictation/0_r36s_ditado_01.html   (index 1..150)
dictation/0_r36s_ditado_02.html   (index 151..300)
...
```

Copie para o celular **só os arquivos que você vai usar** — cada um funciona sozinho, sem nada ao
lado. Cada bundle tem seu próprio progresso, e o **Exportar** dele traz só as entradas daquele
bloco.

Atenção ao volume: 150 imagens r36s dão ~8 MB por arquivo, então uma coleção de 8.692 imagens
gera 58 arquivos e ~460 MB. Os bundles são gitignored (`dictation/*_ditado_*.html`).

**Por que o bundle é necessário.** Quando você abre um arquivo local no Chrome do Android, a URL
da página é um `content://` — um identificador *opaco* de um documento no MediaStore, não um
caminho dentro de uma pasta. Não existe diretório contra o qual um caminho relativo resolva,
então `source/imagem.png` vira `content://media/external/file/source/imagem.png`, que não é
documento nenhum: `ERR_FILE_NOT_FOUND`. Nenhum ajuste de caminho conserta isso. O bundle resolve
porque não sobra referência externa — cada imagem é um `data:` URI dentro do próprio arquivo.

**No desktop, ou servindo por HTTP**, dá para usar a pasta: copie o conteúdo de uma coleção para
`dictation/source/` (os PNGs e o `index.json`, soltos) e sirva a pasta. Nesse modo só existe o
**jogo 1**: o `index.json` não carrega os dados dos outros dois, que são montados no empacotamento.

```bash
cd dictation && python3 -m http.server 8000
```

O mesmo `index.html` atende aos dois modos: se houver dados embutidos ele os usa, senão busca
`source/index.json`.

## make_bundle.py

```
python3 dictation/make_bundle.py <pasta-da-coleção> [opções]

--out-dir DIR      onde gravar (padrão: dictation/)
--per-file N       imagens por arquivo (padrão: 150)
--max-files N      gera no máximo N arquivos; 0 = todos (padrão: 0)
--quality Q        qualidade do JPEG, 1-95 (padrão: 88)
--png              embute o PNG original em vez de re-encodar
--no-games         gera tudo como jogo 1 (digitar), sem os grids de botões
```

As imagens são re-encodadas para JPEG q88, que ficou visualmente equivalente ao PNG nas legendas
e ~6x menor (271 KB → 47 KB numa imagem r36s típica). Isso importa porque base64 ainda infla o
resultado em ~33%: com `--png` cada arquivo passaria de 40 MB.

O `--per-file` existe porque um arquivo único com uma coleção inteira o Chrome do Android não
abre. O script alerta se algum arquivo passar de 60 MB. O `--max-files` serve para gerar só os
primeiros blocos, sem esperar a coleção toda.

O léxico dos jogos 2 e 3 é carregado uma vez por execução: primeiro a word-api, e o que ela não
tiver (ou tudo, se ela estiver fora do ar) sai de uma varredura dos `warehouse/*_base.txt`. Com as
duas fontes dá ~36 mil palavras em ~2,5s; só com o warehouse, ~32 mil em ~1s — e a diferença
aparece nos distratores, não na cobertura (4,4% das frases caem para o jogo 1 nos dois casos). Sem
nenhuma das duas, o script avisa e gera tudo como jogo 1. O texto acrescentado a cada frase é
desprezível perto da imagem em base64: os arquivos não mudam de tamanho.

Vale rodar com a word-api no ar: além de ter mais palavras, ela é a fonte canônica. Mas ela também
guarda entradas onde o campo pinyin traz a tradução (`暗示` → `suggest`), o pinyin sem os espaços
(`孩子們` → `háizi men`) ou uma nota em português dentro do campo da palavra. O `wordgrid.py`
valida a estrutura de cada sílaba antes de aceitar uma entrada, e nesses casos a versão do
warehouse é quem prevalece.

Reempacotar a mesma coleção dá **exatamente o mesmo arquivo**: o embaralhamento é semeado pelo nome
da imagem, não pelo relógio.

A numeração dos nomes é fixada pelo total de blocos, não pelo recorte — reexecutar com
`--max-files` não renomeia os arquivos já gerados.

## Os jogos

Quem escolhe o jogo de cada frase é o `make_bundle.py`, pela posição dela no bloco. Uma frase que
não dá para montar — um caractere só, ou um caractere que o léxico não conhece — **cai para o jogo
1** em vez de sumir; a saída do script conta quantas foram (`jogos 50/48/50, 2 rebaixada(s)`).

**Jogo 2 — montar por pinyin.** Cada palavra da frase vira um botão com o seu pinyin, e ganha mais
dois botões errados: 3 opções por palavra, tudo embaralhado junto. Os distratores variam nas
**letras**, nunca só no acento — se a certa é `jiǎn zhí`, você não vai ver `jiān zhí` do lado, e sim
coisas como `jiān chí` ou `miǎn zhí`. Palavra repetida na frase ganha um botão por ocorrência, mas
só um par de distratores.

**Jogo 3 — montar por caractere.** Os caracteres da própria frase, embaralhados, sem distrator
nenhum.

## Controles

- **Swipe** para navegar; os botões `‹` `›` fazem o mesmo. Todas as imagens ficam acessíveis, mesmo
  as já feitas.
- A página abre na **primeira imagem ainda não feita**.
- No jogo 1, **Enter** (ou a tecla "OK" do teclado) valida o que você digitou. A comparação é
  **literal**: um espaço a mais reprova. Nos jogos 2 e 3 o Enter não faz nada — não há o que enviar.
- Errando, fica vermelho e treme: o campo no jogo 1, o botão tocado nos jogos 2 e 3.
- Sair de uma frase pela metade e voltar **não perde o caminho andado** — nem o que você digitou no
  jogo 1, nem os botões já tocados nos jogos 2 e 3. O campo é um só na página, mas o conteúdo é de
  cada frase: chegando a uma frase do jogo 1 ele vem vazio e já com o cursor dentro.
- No menu **⋮**, **Exportar index.json** baixa o índice com os `done` atualizados. O arquivo sai no
  formato de sempre (`index`, `source`, `sentence`, `done`) — os dados dos jogos não vão junto,
  porque são remontados a cada empacotamento.

## O progresso não volta para o index.json sozinho

Uma página estática não pode gravar arquivo no Android — a File System Access API é só desktop.
O progresso fica no `localStorage` do navegador do celular e sobrevive a recarregar e fechar. Use
**Exportar** quando quiser levar o estado de volta para o Mac. Limpar os dados do site apaga o
progresso.

A chave do `localStorage` é uma impressão digital dos nomes dos arquivos do índice, então o
progresso é **compartilhado** entre o bundle e a mesma coleção aberta pela pasta — e duas coleções
diferentes não se misturam.
