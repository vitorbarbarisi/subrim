# Subrim no YouTube (extensão Chrome)

Mostra a legenda chinesa do vídeo no estilo subrim (pinyin roxo, hanzi branco,
tradução amarela por palavra, frase traduzida no topo) sobre o player do YouTube.

## Uso

1. Suba o servidor local: `python subrim_server.py` (porta 7997).
2. `chrome://extensions` → modo do desenvolvedor → **Carregar sem compactação** → esta pasta.
3. Abra um vídeo com legenda chinesa. Não precisa ligar o CC: a extensão captura
   a legenda que o próprio player baixa e, se ele estiver em outra língua, troca
   a faixa do player para a chinesa (o YouTube exige um token na URL da legenda,
   que só o player tem). Sem legenda manual, usa a automática do YouTube,
   juntando os fragmentos em frases.
4. A tradução chega em streaming: as frases a partir do ponto atual do vídeo
   aparecem primeiro (cada lote da DeepSeek fica no cache do servidor).

### Vídeos sem legenda chinesa (Whisper)

O popup mostra **Transcrever com Whisper** (ou marque *Transcrever
automaticamente*). O servidor baixa o áudio com yt-dlp (usando o `cookies.txt`
do projeto), transcreve com o Whisper (`SUBRIM_WHISPER_MODEL`, default
`medium`) e guarda em `cache/yt/<id>_whisper.json` — abrir o vídeo de novo
reaproveita a transcrição. O progresso aparece no lugar da legenda e no popup.

## Opções (ícone da extensão)

- **Legendas subrim**: desligado, volta a legenda nativa do YouTube.
- **Tradução da frase no topo** (`BURN_TOP_TRANSLATION` do queimado).
- **Várias linhas** (`BURN_MULTILINE`): a frase quebra entre palavras e cresce
  para cima; desligado, fica numa linha só e a fonte encolhe para caber.
  Nos dois casos, se não couber, a fonte encolhe em passos de 5% até 40%.
- **Caixa opaca** (`BURN_BOX_OPAQUE`): desligado, a caixa fica 50% transparente.
- **Tamanho da fonte**: 60% a 160% do tamanho do queimado (hanzi = 6% da altura).
- **Clicar na palavra marca como dominada**: clicar numa palavra que ainda tem
  pinyin/tradução grava `confidence_level = 3` na word-api (via
  `PATCH /word-api/{word}` do hanzi-api; se a palavra não existe lá, ela é
  criada) e a ajuda some na hora. O aviso no canto tem **Desfazer**, que volta
  ao nível anterior. Vale para todo o subrim (queima, Coleções), não só aqui.
- **Este vídeo**: estado da legenda/tradução e o botão do Whisper.

O popup também mostra se o servidor local está no ar.

## Arquivos

- `inject_main.js` — mundo MAIN: intercepta `fetch`/XHR de `/api/timedtext` (zh*) e faz o fallback.
- `content.js` — navegação SPA, conversão json3 → cues, sincronia com o vídeo.
- `background.js` — chamadas ao `localhost:7997` (content script não pode, por CORS/PNA),
  incluindo o NDJSON de `/pairs/stream` repassado por uma porta (`chrome.runtime.connect`).
- `render.js` — parser dos pares, casamento por termo mais longo e overlay.
- `popup.html` / `popup.js` — opções (`chrome.storage.sync`) e status do servidor.
- `icons/` — gerados do `subrim_icon.png` com `sips -z N N`.
- `styles.css` — tamanhos relativos à altura do player (hanzi = 6%, entre 24 e 120px).

## Testes

```bash
cd chrome_extension && node --test
```
