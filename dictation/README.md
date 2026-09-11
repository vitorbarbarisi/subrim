# Ditado

Página estática para treinar as frases de uma coleção, no Chrome do celular. Mostra a imagem em
largura total e, embaixo, um campo com a frase em chinês; acertando, o item é marcado como feito e
o carrossel avança.

São **cinco jogos**, que se alternam a cada frase — 1, 2, 3, 4, 5, 1… — então um bloco de 150 sai
30 de cada:

| Jogo | Imagem | Grid | Como se joga |
|---|---|---|---|
| 1 | completa | — | Digitar a frase e confirmar com Enter |
| 2 | completa | palavras em **pinyin** | Tocar as palavras na ordem |
| 3 | **só a tradução** | **caracteres** embaralhados | Tocar os caracteres na ordem |
| 4 | **só o mandarim** | 5 **traduções** | Escolher a tradução certa |
| 5 | completa | a **decomposição** de cada caractere | Tocar as decomposições na ordem |

A imagem muda de jogo para jogo porque a legenda queimada **mostra a resposta**: sem escondê-la, o
jogo 3 seria copiar o que está na tela em vez de recordar. Cada jogo vê só a metade que não é a
sua resposta.

Do 2 ao 5 o campo é preenchido pelos toques, não pelo teclado: cada acerto escreve o pedaço e
apaga o botão do grid; ao completar a frase, o carrossel avança sozinho. Errar deixa o botão
vermelho e não escreve nada — o campo é sempre um começo correto da frase, e por isso não há (nem
precisa haver) como desfazer. O jogo 4 é o único de clique único: acertou, escreve a tradução no
campo e avança.

A página em si continua independente do resto do repo: sem build, sem dependência de runtime, é um
`index.html`. Tudo que os jogos precisam — segmentação em palavras, pinyin, distratores, traduções
erradas, decomposições, embaralhamento — é calculado pelo `make_bundle.py` e viaja embutido no
arquivo, porque no celular não há rede nem servidor para consultar. Ver `wordgrid.py`,
`translations.py` e `hanzi_decomp.py`.

Continua sendo **uma imagem por frase**, a que aquele jogo usa: o bundle não fica maior.

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
**jogo 1**: o `index.json` não carrega os dados dos outros, que são montados no empacotamento.

```bash
cd dictation && python3 -m http.server 8000
```

O mesmo `index.html` atende aos dois modos: se houver dados embutidos ele os usa, senão busca
`source/index.json`.

## As três imagens por frase

Os jogos 3 e 4 precisam de imagens que escondem metade da legenda. Elas são gravadas pelo **salvar
coleção**, marcando "Gerar variantes de imagem", em subpastas da própria coleção:

```
warehouse/collections/<coleção>/
  001_amor81_line0120.png              completa   → jogos 1, 2 e 5
  so_traducao/001_amor81_line0120.png  só a tradução → jogo 3
  so_mandarim/001_amor81_line0120.png  só o mandarim → jogo 4
```

Subpasta e não sufixo no nome: o visor do R36S varre todo `*.png` da pasta, e com sufixo as
variantes entrariam no slideshow intercaladas com as imagens de verdade.

São três arquivos por frase, então o disco triplica — daí ser uma escolha na hora de salvar, e não
o padrão. O custo de tempo é bem menor que 3×: o frame é extraído do vídeo **uma vez** (a parte
cara) e só a queimada da legenda se repete.

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

O léxico dos jogos 2, 3 e 5 é carregado uma vez por execução: primeiro a word-api, e o que ela não
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

O jogo 4 varre a coluna portuguesa dos mesmos bases (~141 mil traduções, ~1s). O jogo 5 consulta a
**hanzi-api**, que não tem busca em lote — é um `GET` por caractere, e cada um incrementa o
contador `calls` daquele caractere no servidor. Por isso o resultado fica em
`dictation/.hanzi_cache.json`: um caractere é consultado uma vez na vida e reempacotar não toca
mais na API. Apagar o arquivo força a reconsulta, o que vale a pena de vez em quando — o
enriquecimento é assíncrono, e um caractere sem decomposição hoje pode ter daqui a um mês.

Se a hanzi-api estiver fora do ar e o cache vazio, o jogo 5 sai do rodízio (sem decomposição ele
seria o jogo 3 com a imagem que mostra a resposta). Nada disso quebra o empacotamento.

Reempacotar a mesma coleção dá **exatamente o mesmo arquivo**: o embaralhamento é semeado pelo nome
da imagem, não pelo relógio.

A numeração dos nomes é fixada pelo total de blocos, não pelo recorte — reexecutar com
`--max-files` não renomeia os arquivos já gerados.

## Os jogos

Quem escolhe o jogo de cada frase é o `make_bundle.py`, pela posição dela no bloco. Uma frase que
não dá para montar — um caractere só, um caractere que o léxico não conhece, uma tradução sem
concorrentes de pontuação parecida — **cai para o jogo 1** em vez de sumir; a saída do script conta
quantas foram (`jogos 32/30/30/28/30, 2 rebaixada(s)`).

**O rodízio é só sobre os jogos que a coleção suporta.** Uma coleção salva sem as variantes de
imagem não tem como jogar 3 nem 4; alternar 1..5 assim mandaria 60% das frases para o jogo 1.
Nesse caso o rodízio vira `1, 2, 5` e o script diz o motivo:

```
   jogos disponíveis: 1/2/5
   ⚠️  sem so_traducao/: o jogo 3 sai de cena
```

**Jogo 2 — montar por pinyin.** Cada palavra da frase vira um botão com o seu pinyin, e ganha mais
dois botões errados: 3 opções por palavra, tudo embaralhado junto. Os distratores variam nas
**letras**, nunca só no acento — se a certa é `jiǎn zhí`, você não vai ver `jiān zhí` do lado, e sim
coisas como `jiān chí` ou `miǎn zhí`. Palavra repetida na frase ganha um botão por ocorrência, mas
só um par de distratores.

**Jogo 3 — montar por caractere.** Os caracteres da própria frase, embaralhados, sem distrator
nenhum. A imagem mostra só a tradução.

**Jogo 4 — escolher a tradução.** A imagem mostra só o mandarim (com pinyin). As quatro traduções
erradas saem da coluna portuguesa dos `warehouse/*_base.txt`, escolhidas por terem a **mesma
sequência de pontuação** da certa — `,?` no exemplo abaixo — para que descartá-las exija ler o
chinês, não contar vírgulas:

```
    SEMPRE FUI UM CARA MUITO BACANA COM VOCÊ, VIU?
    O QUE FOI, ZORAIDE?
  ✓ PERAÍ, QUEM É QUE TE DISSE ISSO?
    TIO ABDUL JÁ VAI, HEIN?
    LEITÃOZINHO PURURUCA, MÃE?
```

O botão mostra a tradução **sem a marcação da legenda**: some o `[BRUNO]` do falante, o `<i>` do
itálico, o `♪` da música e o `>>` de troca de fala. Isso não é só limpeza: a marcação aparece em
umas opções e não em outras, então dava para escolher sem ler. As 16 linhas do warehouse com
colchete truncado (`LAURINDA] ÓTIMA…`) ficam de fora do pool inteiras — não há par para
reconstruir.

A assinatura sai do **português**, nunca do chinês: medindo os 209 bases, a pontuação das duas
colunas só coincide em 78,9% das linhas, porque a legenda foi re-segmentada na tradução. Duas
peneiras a mais existem só para não entregar a resposta — as opções têm a mesma caixa (as novelas
são maiúsculas, os filmes não) e tamanho parecido, senão bastaria escolher a diferente.

A posição da certa é sorteada, mas **nunca repete três vezes seguidas**. O sorteio puro é uniforme
e independente (medido: qui² da marginal e das diferenças abaixo do limiar, correlação lag-1 ~0),
só que o acaso produz corridas — chegou a cinco frases seguidas com a certa na mesma posição, e aí
o jogo parece viciado mesmo estando certo. A regra mora no `make_bundle`, e não no
`translations.py`, porque é sobre a sequência: lá só se enxerga uma frase por vez. Ela dispara em
~3% dos itens, então a distribuição continua uniforme.

**Jogo 5 — montar por decomposição.** Cada botão é **um componente** (`日`, `寺`), não a
decomposição inteira: montar um caractere exige achar todos os seus componentes espalhados pelo
grid. Dentro de um caractere a **ordem é livre** — a decomposição é um conjunto, e a ordem do campo
vem de LLM, então não dá para punir por ela.

- componente certo fica com **borda verde**, marcado, até o caractere fechar;
- componente errado fica vermelho e volta ao normal, sem escrever nada;
- caractere completo entra no campo e os verdes desaparecem;
- a **glossa** do componente está no hover (desktop) e no toque longo de ~400 ms (celular), porque
  no Chrome do Android não existe hover e o `title` não aparece. Componente sem glossa não abre
  balão nenhum — existem no dado (`要` vem como `西 () + 女 ()`).

Os componentes saem do campo `decomposition` da hanzi-api. Dos 1.261 caracteres com o campo
preenchido, **1.156 decompõem**; as 105 recusas são legítimas (glossa com `+` dentro, decomposição
alternativa com "ou", subtração, forma tradicional no lugar da simplificada) e caem no fallback: o
caractere inteiro num botão só. Frase em que **nenhum** caractere decompõe é rebaixada para o
jogo 1 — seriam todos botões inteiros, viraria o jogo 3 com a imagem que mostra a resposta. São
0,2% das frases.

O grid fica com ~17 botões na mediana e 25 no p90, no mesmo corpo de letra do jogo 3.

## Controles

- **Swipe** para navegar; os botões `‹` `›` fazem o mesmo. Todas as imagens ficam acessíveis, mesmo
  as já feitas.
- A página abre na **primeira imagem ainda não feita**.
- No jogo 1, **Enter** (ou a tecla "OK" do teclado) valida o que você digitou. A comparação é
  **literal**: um espaço a mais reprova. Nos outros jogos o Enter não faz nada — não há o que enviar.
- Errando, fica vermelho e treme: o campo no jogo 1, o botão tocado nos demais.
- Sair de uma frase pela metade e voltar **não perde o caminho andado** — nem o que você digitou no
  jogo 1, nem os botões já tocados nos jogos 2, 3 e 5, nem os componentes verdes de um caractere
  que ficou pela metade. O campo é um só na página, mas o conteúdo é de cada frase: chegando a uma
  frase do jogo 1 ele vem vazio e já com o cursor dentro.
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
