# Relatório de validação — fluxo automático, rostos e botões

Data: 13 de agosto de 2026  
Projeto: CortaFlow AI 0.1.0  
Vídeo real: `sP3N8HRHFkw`, 11min07s, 1920×1080, 59,94 fps, AV1/Opus

## Conclusão

O fluxo pedido está implementado e foi corrigido para executar nesta ordem:

```text
link/arquivo autorizado
→ mídia local
→ transcrição por palavra
→ cenas, pausas e atividade de voz
→ detecção/rastreamento facial
→ falante ativo quando há mais de uma pessoa no quadro
→ ranking dos trechos com texto + áudio + cena + rosto
→ cortes únicos entre 5 e 179 segundos
→ legendas automáticas
→ prévias para revisão/alteração
→ aprovação
→ escolha da pasta e render final
```

Não foi criado build nem instalador e nenhum programa/modelo foi baixado nesta validação.

## Por que os rostos não apareciam automaticamente

Foram encontrados três defeitos independentes:

1. O modelo oficial `face_landmarker.task` já existia em `AppData\Local\CortaFlow\CortaFlowAI\Audit`, mas o campo da tela Analisar ficava vazio. O botão manual exigia que o usuário localizasse o mesmo arquivo novamente.
2. O pipeline de um clique detectava rostos somente depois de pontuar os cortes. Assim, o componente facial da nota não recebia as observações reais.
3. O pipeline não executava a análise de falante ativo e zerava suas decisões ao concluir. Com mais de uma pessoa, o reenquadramento tendia ao maior rosto, não necessariamente a quem falava.

Além disso, o teste visual revelou um quarto problema: em plano aberto, os rostos pequenos eram visíveis para uma pessoa, mas o Face Landmarker não os encontrava no quadro inteiro. Foi adicionada uma segunda passagem por seis regiões sobrepostas do mesmo quadro somente quando o plano é horizontal e o rosto está ausente ou pequeno. Essa passagem usa o mesmo modelo local; não instala nem baixa outra IA.

Correções aplicadas:

- localização automática do modelo facial já instalado, mantendo a seleção manual;
- detecção facial movida para antes do ranking;
- observações de rosto entregues ao pontuador de cortes;
- gatilho de falante ativo quando uma amostra possui dois ou mais IDs temporários;
- reaproveitamento da energia/VAD já extraída, evitando analisar o áudio duas vezes;
- decisões de falante preservadas no projeto, editor e prévias;
- detecção regional de rostos pequenos em planos abertos;
- nenhuma identificação biométrica: apenas caixas, movimento da boca e IDs temporários.

## Testes no vídeo real

### Trecho de 60 segundos com closes e trocas de câmera

| Evidência | Resultado |
|---|---:|
| Observações faciais | 136 |
| IDs temporários ao longo do trecho | 3 |
| Enquadramentos gerados | 136 |
| Rostos simultâneos por amostra | 1 |

Nesse trecho, a câmera mostrou uma pessoa por vez; por isso o modo multipessoa não deveria ser acionado.

### Trecho de 30 segundos com plano aberto

Antes da correção regional, o detector retornava no máximo um rosto por amostra e o gatilho multipessoa ficava falso. Depois da correção:

| Evidência | Resultado |
|---|---:|
| Observações faciais | 81 |
| Amostras temporais | 75 |
| Amostras com mais de um rosto | 5 |
| Máximo de rostos no mesmo quadro | 3 |
| Gatilho automático multipessoa | verdadeiro |
| Decisões de falante | 75 |
| Decisões com foco definido | 73 |
| Decisões incertas/grupo | 26 |
| Trocas de foco detectadas | 10 |
| Enquadramentos de falante | 75 |

A análise facial do trecho levou 28,83 s e a correlação de falante 0,14 s no ambiente testado. O arquivo completo 1080p/59,94 fps ultrapassou cinco minutos em uma execução de diagnóstico integral; isso é limitação de desempenho, não falha de detecção. O fluxo continua cancelável e roda fora da thread da interface.

## Critérios para estimar bons cortes

O sistema não pode garantir viralização. Antes da publicação ele calcula potencial editorial; métricas reais só existem após o público assistir.

As regras locais agora consideram início com hook, ideia completa, valor/informação, emoção, densidade e continuidade da fala, energia, pausas, limites de cena, presença de rosto, duração desejada e diversidade temática. Isso está alinhado aos sinais públicos das plataformas:

- o YouTube informa que Shorts são classificados por escolha de assistir, duração média, percentual médio assistido, likes e pesquisas pós-visualização, além de interesse no tema, concorrência e sazonalidade ([YouTube — Search & Discovery](https://support.google.com/youtube/answer/11914225?co=YOUTUBE._YTVideoType%3Dshorts&hl=en));
- retenção, “stayed to watch”, visualizações engajadas, duração média e percentual assistido são métricas centrais ([YouTube — Content analytics](https://support.google.com/youtube/answer/12220281)); picos podem indicar repetição/compartilhamento ou falta de clareza, enquanto quedas indicam abandono/pulo ([YouTube — audience retention](https://support.google.com/youtube/answer/9314415));
- o TikTok recomenda apresentar o hook nos primeiros seis segundos e a proposta nos primeiros três, usar texto/legendas e recursos como suspense, surpresa e emoção ([TikTok — Creative best practices](https://ads.tiktok.com/help/article/creative-best-practices?lang=en)); também recomenda vídeo vertical 9:16, som e mensagem clara ([TikTok Creative Center](https://ads.tiktok.com/business/creativecenter/quicktok/online/creative-tips-for-home-and-lifestyle/pc/en)).

O CortaFlow não consulta tendências ao vivo nem dados pós-publicação. “Trend” só poderá ser calibrado de verdade se, no futuro e com aprovação, o usuário fornecer métricas dos vídeos publicados.

## Quantidade, repetição, legendas e prévias

- Duração configurável: 5 a 179 segundos.
- Quantidade atual: 1 a 50 sugestões por análise.
- Diversidade: rejeita sobreposição temporal a partir de 60% e similaridade temática a partir de 82%.
- Limites: cada sugestão fica dentro das palavras/transcrição e procura terminar em frase, pausa ou cena natural.
- Legendas: criadas automaticamente com timestamps por palavra e editáveis antes do arquivo final.
- Revisão: todas as sugestões aparecem primeiro na lista e cada resultado solicitado recebe sua versão vertical no cache.
- Saída final: só é salva depois da aprovação e da escolha explícita da pasta.

“Infinitos cortes” não é possível em um vídeo finito sem repetir conteúdo. O estado atual entrega até 50 cortes distintos por análise. Aumentar esse teto é tecnicamente possível, mas reduz diversidade e pode produzir centenas de variações muito parecidas; por isso não foi alterado silenciosamente.

## Botões e fluxo de interface

Foi executada uma verificação automática em todas as seis páginas principais. Os 53 botões encontrados possuem ação conectada; o botão Mudo usa corretamente o sinal de alternância, e os demais usam clique. O editor final agora é filho de **Cortes sugeridos**, não uma sétima página concorrente.

| Página | Botões conectados | Funções principais verificadas |
|---|---:|---|
| Importar | 5 | analisar URL, pasta, baixar, cancelar, arquivo local |
| Analisar | 7 | cortes, cancelar, modelo, rostos, seleção, falante, correção |
| Cortes sugeridos | 20 | lista, player, aceitar/rejeitar, lote, editor incorporado, legenda, enquadramento, marca-d'água e salvamento |
| Editor | 13 | reprodução, quadros, saltos, mudo, tela cheia, marcas e exportação |
| Legendas | 6 | transcrever, cancelar, JSON, SRT, ASS e aplicar ao vídeo |
| Histórico | 2 | atualizar e abrir |

Os testes funcionais existentes também cobrem download autorizado, importação assíncrona, análise, rostos, falante, edição de intervalos, legendas, marca-d'água, prévia obrigatória, aprovação, escolha da pasta final, fila e render FFmpeg.

## Erro `out_time_us=N/A` e mensagens do terminal

O traceback informado foi causado pelo progresso do FFmpeg: AV1/Opus pode emitir `out_time_us=N/A` antes do primeiro timestamp. A interface convertia esse texto diretamente com `int()`. Agora `N/A`, vazio ou valor inválido é tratado como 0% até chegar um timestamp válido. O teste específico e os testes reais de renderização passaram.

As mensagens `Could not update timestamps for skipped samples` são avisos do decodificador Opus; no registro anexado elas não são o traceback que derrubou a atualização de progresso.

O comando `cd .\src\cortaflow\main.py` falha porque `cd` entra somente em diretórios. A forma recomendada, a partir da raiz, é:

```powershell
.\.venv\Scripts\python.exe -m cortaflow.main
```

Também funciona entrar em `src\cortaflow` e executar `python .\main.py`, desde que o ambiente virtual esteja ativo.

## Correção da tela vazia e das prévias

Na reprodução informada, o botão automático estava executando: os logs mostraram análise de cenas e três arquivos foram criados no cache às 15:30. A interface, porém, mantinha a tabela vazia durante todo o processamento e mostrava o andamento somente na barra inferior. Além disso, **Abrir prévia** dependia de um arquivo renderizado e tentava abrir outro programa, dando a impressão de botão sem ação.

O comportamento foi corrigido:

- clicar em **Gerar cortes sugeridos** abre imediatamente **Cortes sugeridos**;
- a página mostra um indicador indeterminado e o nome da etapa atual;
- as sugestões chegam à tabela assim que o ranking termina, antes das renderizações;
- cada prévia pronta é publicada individualmente na tabela, sem esperar as três;
- a coluna mostra **Original** enquanto oferece a visualização rápida do intervalo de origem e **Com legenda** quando a versão vertical está pronta;
- **Assistir selecionado** reproduz o intervalo dentro da própria página e muda para **Pausar prévia** durante a reprodução;
- **Anterior** e **Próximo** permitem conferir os cortes em sequência, um por vez;
- a coluna informa **Legenda + rosto conferido** somente depois que o arquivo renderizado passa pela segunda detecção facial, evitando confundir um plano de recorte com o resultado realmente gravado;
- **Cancelar automático** é habilitado somente durante uma tarefa, apresenta estado visual diferente quando desabilitado e confirma que o cancelamento foi solicitado;
- os botões automáticos receberam teste funcional de início, mudança de página, estado habilitado/desabilitado e cancelamento.

Uma prévia real gerada para o vídeo `otFNfH_qO2Y` foi carregada no player incorporado com estado `LoadedMedia`, duração de 6.966 ms e resolução 540×960, com vídeo H.264 e áudio AAC.

### Correção de rosto na troca de câmera

As prévias reais foram inspecionadas. Todas continham legenda gravada, mas uma delas mantinha por alguns quadros o movimento proveniente da câmera anterior e outra deixava parte do rosto na borda durante movimento. Havia duas causas relacionadas: a mudança de cena não era preservada no render e os keyframes faciais, que já chegavam suavizados, recebiam uma segunda suavização e atrasavam em relação à pessoa.

Os keyframes agora preservam `scene_reset` e `face_safe`. Na mesma tomada, o enquadramento acompanha o rosto uma única vez e aplica margem segura lateral; ao detectar corte de câmera, o FFmpeg mantém a posição anterior até o limite e salta para o novo rosto, sem atravessar lentamente a imagem.

Validação no ponto real problemático:

- mudança de cena detectada em 8,800 s;
- keyframe de reinício aplicado em 8,800 s;
- quadro inspecionado no tempo original 11,760 s;
- um rosto detectado inteiro na saída;
- centro horizontal do rosto em 59,1% do quadro vertical;
- caixa facial dentro da margem segura;
- legenda visível na mesma prévia.

Uma segunda validação real foi feita no vídeo `otFNfH_qO2Y` após reduzir a amostragem para 250 ms: 339 observações faciais, 338 instantes avaliados, sete IDs temporários, até dois rostos no mesmo quadro e cinco trocas de foco. Depois da correção automática, **338/338 amostras ficaram dentro da área segura (100%)**.

### Correção do falso recorte central e validação pós-render

O MP4 que ainda cortava o rosto foi medido diretamente. O recorte permaneceu fixo em X=656 durante o corte e 52 de 95 amostras renderizadas ficaram cortadas ou descentralizadas. A causa era objetiva: o modelo local estava em `CortaFlowAI\Audit\face_landmarker.task`, mas o localizador também montava uma rota antiga em `CortaFlow\Audit`. Sem encontrar o arquivo, o pipeline recebia zero keyframes e usava o centro fixo, embora a ausência do detector pudesse parecer “sem rosto”.

O localizador agora inclui a pasta real de dados da aplicação e preserva a rota antiga apenas por compatibilidade. Quando nenhum detector executa, o resultado passa a ser `Revisar`, nunca `Sem rosto`. Além da validação geométrica anterior ao render, cada MP4 pronto é aberto novamente pelo detector local; rosto ausente, tocando a borda ou fora da região central reprova a prévia e bloqueia a aceitação automática.

No novo teste de ponta a ponta com o mesmo vídeo foram obtidos 339 pontos faciais, 338 decisões/keyframes e um MP4 vertical de 59,960 s. A auditoria do arquivo pronto aprovou **148/148 amostras (100%)**, inclusive no instante em que a versão antiga cortava o lado direito do rosto.

### Revisão individual e salvamento

- **Revisar, ajustar e salvar** abre o corte selecionado na revisão final;
- a prévia vertical existente é reutilizada para conferir rosto e legenda;
- o texto das legendas do intervalo é editável e qualquer correção exige nova prévia;
- **Ajustar enquadramento no Editor** abre exatamente o intervalo do corte;
- apenas PNG, WebP, JPG/JPEG ou BMP legível é aceito como marca-d'água;
- a imagem pode ser arrastada e redimensionada sobre a prévia vertical;
- **Aprovar e salvar este corte** solicita a pasta e salva exatamente o início/fim do corte;
- o estado muda para aceito somente depois que o arquivo final termina de ser gravado;
- nomes existentes não são sobrescritos: o programa cria um nome livre com sufixo.

### Marca-d'água na prévia

As tarefas reais 10 e 11 registraram a imagem `Pós jogo BR - m.png` como ativa, com posição inferior direita, largura de 18% e opacidade de 75%. Os dois renders terminaram normalmente e a comparação de quadros confirmou que a marca está gravada no MP4. O problema restante era visual: o overlay de arrastar usava toda a largura do widget, incluindo as barras pretas laterais, enquanto o vídeo 9:16 ocupava somente a faixa central.

O overlay agora calcula o retângulo visível do vídeo conforme a proporção de saída e limita desenho, movimento e redimensionamento a essa área. Ao escolher a imagem, a tela informa que é necessário atualizar a prévia para gravá-la; após o render, o estado confirma **Marca-d'água gravada no MP4**.

A captura posterior revelou ainda um problema específico de composição do Qt no Windows: o `QStackedLayout` estava em modo `StackAll`, mas o player permanecia como widget atual no índice 0. Mesmo com a marca calculada e marcada como visível, o `QVideoWidget` podia repintar por cima dela. Quando ativa, a marca agora é explicitamente definida como camada atual superior no índice 1. A validação de interface confirmou `currentWidget == watermark_overlay`, imagem visível e retângulo contido no vídeo 9:16.

O fluxo individual também foi separado do lote. Quando **Editar e salvar** está aberto, tanto **Salvar este corte** quanto o botão superior **Salvar cortes** solicitam a pasta e renderizam diretamente o intervalo exibido, mesmo que a linha não tenha sido aceita antes. A prévia atualizada permanece opcional. Ao alterar a marca-d'água, a sincronização não pode mais reativar **Usar linha do tempo editada**: o corte individual mantém início/fim exatos e `use_timeline=False`. A aceitação prévia continua restrita ao salvamento em lote.

No teste real 1080×1920 com posição superior direita, a marca ocupou X=898–1012 e Y=81–224, totalmente dentro do quadro vertical.

### Reorganização baseada em editores atuais

A documentação oficial consultada aponta o mesmo padrão de produto adotado nesta revisão:

- o [CapCut Long Video to Shorts](https://www.capcut.com/tools/ai-long-video-to-short-video) gera clipes, permite visualizar cada resultado, abrir edição adicional e só depois exportar;
- o [CapCut Desktop](https://www.capcut.com/resource/how-to-use-capcut-on-pc) trata Auto Reframe e legendas como operações de edição do clipe, mantendo exportação como etapa final;
- a [página de resultados do OpusClip](https://help.opus.pro/docs/article/get-clips-faq-1) concentra transcrição, edição e exportação no próprio resultado;
- o [Subject Tracking do OpusClip](https://help.opus.pro/docs/article/subject-tracking) identifica falante por voz/movimento, acompanha suavemente e permite correção por cena;
- o [Auto Reframe do Adobe Premiere](https://helpx.adobe.com/premiere/desktop/add-video-effects/commonly-used-effects/auto-reframe-overview.html) aplica o reenquadramento ao clipe/sequência preservando os cortes.

Por isso, **Exportar** foi removido do menu lateral. **Cortes sugeridos** agora tem duas áreas internas: **Cortes encontrados** e **Editar e salvar**. A primeira geração prepara a versão vertical de cada sugestão; **Atualizar prévia após ajustes** existe apenas para refletir uma correção manual, não como uma segunda geração automática.

## Resultado final dos testes

- 191 testes automatizados aprovados;
- `pip check`: nenhuma dependência quebrada;
- 53/53 botões com sinal conectado;
- detecção multipessoa e gatilho de falante aprovados no vídeo real;
- progresso `N/A` aprovado em regressão e render real;
- nenhum build ou instalador criado.

## Limitações restantes

1. A precisão do falante é probabilística; 26 de 75 decisões do trecho real ficaram incertas e usam enquadramento estável/de grupo. A correção manual continua tendo prioridade.
2. Detectar o vídeo completo em AV1 1080p/60 fps é pesado em CPU e merece otimização de decodificação/amostragem.
3. A lista pode preparar até 50 versões verticais, conforme a quantidade escolhida; isso pode exigir bastante tempo e espaço de cache em vídeos longos.
4. Não há garantia de viralização nem sinal de tendência em tempo real.
