# Ditado

Página estática para treinar a escrita das frases de uma coleção, no Chrome do celular.
Mostra a imagem em largura total e um campo onde você digita a frase em chinês; acertando, o item
é marcado como feito e o carrossel avança.

Independente do resto do repo: sem build, sem dependência de runtime. É um `index.html`.

## Qual dos dois modos usar

**No celular, use o bundle.** É um arquivo `.html` único, com as imagens embutidas:

```bash
python3 dictation/make_bundle.py warehouse/collections/0_r36s --count 150
```

Isso gera `warehouse/collections/0_r36s_ditado.html`. Copie **esse arquivo só** para o celular e
abra. Não precisa de mais nada ao lado.

**Por que o bundle é necessário.** Quando você abre um arquivo local no Chrome do Android, a URL
da página é um `content://` — um identificador *opaco* de um documento no MediaStore, não um
caminho dentro de uma pasta. Não existe diretório contra o qual um caminho relativo resolva,
então `source/imagem.png` vira `content://media/external/file/source/imagem.png`, que não é
documento nenhum: `ERR_FILE_NOT_FOUND`. Nenhum ajuste de caminho conserta isso. O bundle resolve
porque não sobra referência externa — cada imagem é um `data:` URI dentro do próprio arquivo.

**No desktop, ou servindo por HTTP**, dá para usar a pasta: copie o conteúdo de uma coleção para
`dictation/source/` (os PNGs e o `index.json`, soltos) e sirva a pasta:

```bash
cd dictation && python3 -m http.server 8000
```

O mesmo `index.html` atende aos dois modos: se houver dados embutidos ele os usa, senão busca
`source/index.json`.

## make_bundle.py

```
python3 dictation/make_bundle.py <pasta-da-coleção> [opções]

--out ARQUIVO      saída (padrão: <pasta>_ditado.html)
--start N          primeira entrada, 1-based (padrão: 1)
--count N          quantas empacotar; 0 = todas (padrão: 150)
--quality Q        qualidade do JPEG, 1-95 (padrão: 88)
--png              embute o PNG original em vez de re-encodar
```

As imagens são re-encodadas para JPEG q88, que ficou visualmente equivalente ao PNG nas legendas
e ~6x menor (271 KB → 47 KB numa imagem r36s típica). Isso importa porque base64 ainda infla o
resultado em ~33%: 150 imagens r36s dão um arquivo de ~10 MB, contra ~55 MB com `--png`.

O `--count` tem padrão 150 de propósito — uma coleção pode ter dezenas de milhares de imagens, e
empacotar tudo geraria um arquivo que o Chrome do Android não abre. O script avisa quantas
entradas ficaram de fora e alerta se o resultado passar de 60 MB.

## Controles

- **Swipe** para navegar; os botões `‹` `›` fazem o mesmo. Todas as imagens ficam acessíveis, mesmo
  as já feitas.
- A página abre na **primeira imagem ainda não feita**.
- **Enter** (ou a tecla "OK" do teclado) valida o que você digitou. A comparação é **literal**: um
  espaço a mais reprova.
- Errando, a borda fica vermelha. Acertando, o item é marcado e o carrossel anda um.
- No menu **⋮**, **Exportar index.json** baixa o índice com os `done` atualizados.

## O progresso não volta para o index.json sozinho

Uma página estática não pode gravar arquivo no Android — a File System Access API é só desktop.
O progresso fica no `localStorage` do navegador do celular e sobrevive a recarregar e fechar. Use
**Exportar** quando quiser levar o estado de volta para o Mac. Limpar os dados do site apaga o
progresso.

A chave do `localStorage` é uma impressão digital dos nomes dos arquivos do índice, então o
progresso é **compartilhado** entre o bundle e a mesma coleção aberta pela pasta — e duas coleções
diferentes não se misturam.
