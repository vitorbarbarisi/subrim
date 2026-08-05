# Ditado

Página estática para treinar a escrita das frases de uma coleção, no Chrome do celular.
Mostra a imagem em largura total e um campo onde você digita a frase em chinês; acertando, o item
é marcado como feito e o carrossel avança.

Independente do resto do repo: sem Python, sem build, sem dependência. É um `index.html` e uma
pasta `source/`.

## Uso

1. Salve uma coleção pela aba **Coleções** do Subrim Manager. Ela sai em
   `warehouse/collections/<chave>_<formato>/` com os PNGs e um `index.json`.
2. Copie **o conteúdo** dessa pasta para `dictation/source/` (os PNGs e o `index.json`, soltos —
   sem subpasta).
3. Copie a pasta `dictation/` inteira para o celular e abra o `index.html`.

Na primeira abertura a página pede o `index.json` (veja abaixo). Depois disso ela lembra.

## Controles

- **Swipe** para navegar; os botões `‹` `›` fazem o mesmo. Todas as imagens ficam acessíveis, mesmo
  as já feitas.
- A página abre na **primeira imagem ainda não feita**.
- **Enter** (ou a tecla "OK" do teclado) valida o que você digitou. A comparação é **literal**: um
  espaço a mais reprova.
- Errando, a borda fica vermelha. Acertando, o item é marcado e o carrossel anda um.
- **Exportar** baixa um `index.json` com os `done` atualizados.

## Duas coisas que valem saber

**O `source/index.json` no disco nunca muda.** Uma página estática não pode gravar arquivo no
Android — a File System Access API é só desktop. O progresso fica no `localStorage` do navegador
do celular, e sobrevive a recarregar e fechar. Use **Exportar** quando quiser levar o estado de
volta para o Mac. Limpar os dados do site apaga o progresso.

**Por que ela pede o `index.json` na primeira vez.** Aberta como arquivo local (`file://`), o
Chrome bloqueia `fetch` por CORS, então a página não consegue ler o json por conta própria — as
imagens carregam normalmente, só a leitura do json é barrada. Você escolhe o arquivo uma vez e ele
fica em cache.

Se o Chrome do Android der problema com `file://` (dependendo do gerenciador de arquivos ele
entrega um `content://`, e aí os caminhos relativos das imagens quebram), sirva a pasta do Mac pela
wifi — nesse caso não precisa copiar nada nem escolher o arquivo:

```bash
cd dictation && python3 -m http.server 8000
```

e no celular abra `http://<ip-do-mac>:8000`.

## Progresso de mais de uma coleção

Todas as páginas `file://` compartilham o mesmo `localStorage`, então o progresso é guardado sob
uma chave derivada da própria lista de arquivos. Duas coleções em duas pastas não se misturam.
