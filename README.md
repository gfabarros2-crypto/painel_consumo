# Painel de Consumo de Água e Energia da EMPETUR

Módulo independente para incorporar ao portal, com arquivos estáticos e funções Python compatíveis com a Vercel. A pasta aberta nesta tarefa não continha o repositório do site; por isso o painel foi entregue como página, API e área de abastecimento próprias. O portal público consultado usa uma página de consumo em `https://www.empetur.pe.gov.br/consumo-de-agua` com links para dois PDFs de 2022. Esses links continuam disponíveis no painel.

## Publicar pelo GitHub e pela Vercel

1. Crie um repositório próprio para este painel e envie **o conteúdo desta pasta como raiz do repositório**. A Vercel deve importar esse repositório com `Root Directory` na raiz e sem `Build Command` personalizado. `public/` contém a página e `api/` contém as funções.
2. Na Vercel, crie um **Blob privado** no projeto e vincule-o aos ambientes desejados. Isso disponibiliza `BLOB_READ_WRITE_TOKEN` às funções. Sem ele, o painel lê a base inicial empacotada, mas bloqueia novos uploads/publicações para evitar perda de dados.
3. Configure `EMPETUR_ADMIN_USER` e `EMPETUR_ADMIN_PASSWORD` como variáveis de ambiente de produção. Use HTTPS (fornecido pela Vercel). Acesse `/admin.html` para abastecer e a raiz `/` para consultar.
4. Publique o projeto. Após o primeiro upload, os PDFs recebidos, a base mensal e as revisões são gravados no Blob privado; novos deploys do GitHub não apagam esses dados. A primeira leitura usa `data/records.json` apenas quando o Blob ainda está vazio.

Não grave credenciais nem token Blob no GitHub. O código não publica automaticamente os PDFs recebidos; um comprovante aparece apenas com link e aprovação explícita.

## O que há na base entregue

- **Água:** nove competências de janeiro a setembro de 2022, extraídas do [PDF oficial da EMPETUR](https://www.empetur.pe.gov.br/images/consumo-mensal-de-agua-e-energia/2022/planilha_mensal_agua_empetur_-_AGUA.pdf). Uma cópia está em `public/planilhas/agua-empetur-2022.pdf`. O PDF discrimina consumo e fatura total; não discrimina água/esgoto por valor.
- **Energia:** nove faturas de janeiro a setembro de 2022, extraídas do PDF da EMPETUR enviado nesta conversa e guardado em `public/planilhas/energia-empetur-2022.pdf`. A coluna de **kWh está vazia no próprio documento**. A aba mostra os valores faturados e um gráfico de faturamento, com consumo, média, variação, custo por kWh e classificação indisponíveis. O [link original no portal](https://www.empetur.pe.gov.br/images/consumo-mensal-de-agua-e-energia/2022/planilha_mensal_energia_empetur_-_LUZ.pdf) permanece referenciado.
- **Comprovantes:** nenhum foi incluído. O demonstrativo agregado não foi tratado como comprovante de fatura.
- **Lei:** a cópia de uma página fornecida nesta conversa está em [`public/legislacao/lei-16847-2020.pdf`](public/legislacao/lei-16847-2020.pdf) e é aberta pela seção de metodologia.

## Rodar localmente

Requer Python 3.11+ e `pip`. No PowerShell, dentro desta pasta:

```powershell
python -m pip install -r requirements.txt
$env:EMPETUR_ADMIN_USER = "seu-usuario"
$env:EMPETUR_ADMIN_PASSWORD = "sua-senha-forte"
python server.py
```

Abra `http://127.0.0.1:8765/` para o painel e `http://127.0.0.1:8765/admin.html` para o abastecimento. A área administrativa é desativada quando usuário ou senha não estão configurados. O endereço e a porta podem ser definidos com `EMPETUR_HOST` e `EMPETUR_PORT`.

## Atualizar todo mês

1. Acesse `/admin.html` e escolha **Água** ou **Energia**.
2. Envie o PDF recebido (até 4 MB). O sistema extrai linhas mensais com texto selecionável e mostra uma prévia. Se o arquivo for digitalizado, use **Adicionar mês manualmente**.
3. Compare cada linha com o PDF. Corrija competência, consumo e valor total; preencha água e esgoto apenas quando discriminados. Se um campo estiver realmente vazio na fonte, confirme essa ausência na linha ou use **Confirmar campos vazios após conferência** depois de revisar o documento. O link da publicação oficial pode ser aplicado a todos os meses do arquivo.
4. Se houver um comprovante **aprovado para divulgação**, informe sua URL HTTPS e marque a aprovação. Sem os dois dados, o link não aparece no painel público.
5. Clique em **Publicar meses revisados**. Uma competência já existente é substituída; o estado anterior é salvo em `data/revisions/`. O PDF enviado fica em `data/imports/` para auditoria.

No servidor local, o JSON normalizado fica em `data/records.json`. Na Vercel, fica no Blob privado em `empetur-consumo/records.json`. Para implantações locais com armazenamento em volume separado, configure `EMPETUR_DATA_DIR`. O arquivo `data/modelo-registro.json` mostra o esquema para cargas automatizadas. Não edite a interface para adicionar meses.

Campos obrigatórios por mês: `resource` (`water` ou `energy`), `period` (`AAAA-MM`) e ao menos um entre `consumption` e `total_brl`. Zero é um valor válido; ausência é `null` ou registro inexistente. Se um dos dois valores principais estiver ausente, marque `consumption_missing_confirmed` ou `total_missing_confirmed` após conferir o documento. Campos opcionais: `water_brl`, `sewage_brl`, `source_url`, `receipt_url` e `receipt_approved`. Links externos devem usar HTTPS; demonstrativos incluídos no módulo podem usar `planilhas/nome.pdf`.

## Integração no portal

- **Entrada pública:** `public/index.html`, servido por `server.py`. Publique o módulo em um host próprio ou sob `/consumo/` por proxy reverso que remova esse prefixo antes de encaminhar a solicitação. Os recursos da página e as chamadas à API usam caminhos relativos.
- **Página atual:** mantenha no portal o acesso às planilhas originais e acrescente um link para o novo painel, ou faça a rota atual apontar para ele. Como o código do Joomla/portal não foi fornecido, não alteramos sua navegação nem sua página existente.
- **Página inicial:** a lei prevê um símbolo de consumo na página inicial. Insira no HTML do portal:

```html
<script src="https://SEU-HOST/consumo/indicador.js" defer></script>
<empetur-consumo-indicador></empetur-consumo-indicador>
```

O componente busca `/api/overview` no mesmo host do script, mostra Água e Energia com texto e cor e liga ao painel. A API pública permite leitura pelo domínio `https://www.empetur.pe.gov.br`. A identidade do **símbolo padrão** deve ser validada pela EMPETUR antes de instalar o indicador na página inicial, pois o pacote oficial de ícones não estava acessível.

Em produção, mantenha `data/` em armazenamento persistente, use HTTPS, configure credenciais fortes para a área administrativa e coloque o servidor atrás do proxy do ambiente. O PDF enviado fica privado; publicar valores não torna o documento recebido automaticamente acessível ao público.

## Cálculo e pendências

A média considera exatamente os seis meses-calendário anteriores do mesmo recurso com **consumo informado**. A variação é `(consumo atual / média - 1) × 100`. Com histórico incompleto, consumo ausente ou média zero, o percentual e a classe são indisponíveis. Um valor de fatura isolado não é convertido em kWh. O indicador usa texto além da cor.

O [art. 2º da Lei Estadual nº 16.847/2020](public/legislacao/lei-16847-2020.pdf) define: consciente abaixo da média; adequado da média até 10% acima; alerta de 11% a 50% acima; abusivo a partir de 50% acima. O texto deixa **(10%, 11%)** sem faixa e **50%** em duas faixas. `domain.classify()` devolve **Classificação pendente** nesses casos até que a EMPETUR defina o critério institucional. Os valores mensais continuam consultáveis.

## Verificações

```powershell
python -m unittest discover -s tests -v
node --check public/app.js
node --check public/admin.js
```

Os testes cobrem virada de ano, histórico incompleto, zero registrado, ausência de kWh, limites legais, comprovante ausente e extração dos PDFs de água e energia. A API de prévia, revisão/publicação e consulta pública também foi exercitada com uma cópia isolada da base. O layout e as abas foram verificados em desktop e largura móvel.
