# Site Barravento

Base local da Barravento com visual mais editorial e geracao automatica de paginas a partir de arquivos `.docx`.

## Fluxo rapido

1. Abra `abrir-site-completo.bat` para subir o ambiente web completo.
2. Entre pela pagina `membros/` com um acesso aprovado; se a sessao ja estiver aberta, voce vai direto para `painel/`.
3. No `painel/`, envie o `.docx` junto com uma imagem obrigatoria e uma ou mais categorias.
4. O artigo sera publicado e aparecera na capa e nas paginas de categoria.
5. Se preferir, o fluxo por pasta continua funcionando em `conteudo/entrada-docx`.

## O que acontece

- O envio pela web exige `.docx`, imagem e pelo menos uma categoria.
- O arquivo enviado vai para `conteudo/processados`.
- A imagem enviada vai para `site/uploads`.
- Uma pagina nova nasce em `site/artigos/<slug>/index.html`.
- Cada categoria ganha sua propria pagina em `site/categorias/<slug>/index.html`.
- A home em `site/index.html` mostra os 3 textos mais recentes por categoria e atualiza o menu superior.
- Existem paginas proprias para `quem-somos`, `contato` e `busca`.
- A pagina de login fica em `site/membros/index.html`.
- O painel editorial fica em `site/painel/index.html`.
- O caminho antigo `site/publicar.html` continua funcionando como atalho para o painel.

## Regras simples do importador

- O nome do arquivo vira o slug da URL.
- O titulo sai do primeiro titulo ou cabecalho do documento; se nao houver, usa o primeiro paragrafo.
- Se a primeira linha do corpo comecar com `Por `, ela vira a assinatura do texto.
- As categorias sao escolhidas no painel de publicacao e um texto pode pertencer a mais de uma.
- Tags e hashtags podem ser preenchidas no envio e passam a aparecer na pagina do artigo.
- Na edicao, um novo `.docx` substitui o documento anterior e uma nova imagem substitui a imagem anterior.
- Se nenhuma informacao for alterada na edicao, o sistema nao executa a atualizacao.
- O restante entra como corpo da materia.
