# Subrim no YouTube (extensão Chrome, fase 1)

Mostra a legenda chinesa do vídeo no estilo subrim (pinyin roxo, hanzi branco,
tradução amarela por palavra, frase traduzida no topo) sobre o player do YouTube.

## Uso

1. Suba o servidor local: `python subrim_server.py` (porta 7997).
2. `chrome://extensions` → modo do desenvolvedor → **Carregar sem compactação** → esta pasta.
3. Abra um vídeo com legenda chinesa e **ligue o CC** (a extensão captura a
   legenda que o próprio player baixa; sem CC ela tenta ler as faixas do
   `playerResponse`, o que pode falhar se o YouTube exigir token na URL).

## Arquivos

- `inject_main.js` — mundo MAIN: intercepta `fetch`/XHR de `/api/timedtext` (zh*) e faz o fallback.
- `content.js` — navegação SPA, conversão json3 → cues, sincronia com o vídeo.
- `background.js` — chamadas ao `localhost:7997` (content script não pode, por CORS/PNA).
- `render.js` — parser dos pares, casamento por termo mais longo e overlay.
- `styles.css` — tamanhos relativos à altura do player (hanzi = 6%, entre 24 e 120px).

## Testes

```bash
cd chrome_extension && node --test
```
