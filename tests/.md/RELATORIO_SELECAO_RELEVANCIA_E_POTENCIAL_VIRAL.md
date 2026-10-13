# Relatório de decisão — seleção de ideias completas, relevantes e com potencial viral

Data: 13 de agosto de 2026  
Projeto: CortaFlow AI 0.1.0  
Status: mudanças técnicas aprovadas e implementadas em 13 de agosto de 2026. Nenhum programa ou modelo foi instalado/baixado e nenhum build foi criado.

## 1. Resposta direta

O CortaFlow ainda não consegue afirmar com segurança que encontrou “o trecho que vai viralizar”. Ele calcula sinais úteis, mas hoje pode dar nota alta a um trecho que começa ou termina no meio do assunto.

O conserto recomendado tem duas decisões separadas:

```text
1. Este trecho é uma ideia completa, fiel ao contexto e compreensível sozinho?
   NÃO → ampliar os limites ou rejeitar.
   SIM → pode participar do ranking.

2. Entre os trechos válidos, qual tem maior potencial de prender, entregar valor
   e provocar compartilhamento para a audiência escolhida?
```

Uma frase chamativa, uma pergunta ou uma emoção forte não poderá mais compensar um corte incompleto. “Validade editorial” será uma barreira obrigatória; “potencial de desempenho” será uma nota usada somente depois dela.

O nome correto da segunda nota é **Potencial editorial**, não “probabilidade de viralizar”. Antes da publicação o programa só possui indicadores. Viralização real depende também da audiência, personalização, concorrência, época, distribuição da plataforma e desempenho observado.

## 2. Defeito encontrado no CortaFlow atual

### 2.1 O programa confunde pontuação com conclusão do assunto

O gerador atual considera um limite natural quando:

- uma palavra termina com `.`, `!`, `?`, `:` ou `;`;
- há silêncio próximo;
- há uma mudança de cena próxima.

Isso encontra limites de frase ou de imagem, mas não comprova que a ideia terminou. Em entrevista e podcast, a câmera pode mudar enquanto a mesma frase ou discussão continua. Uma pausa também pode ser apenas hesitação.

### 2.2 A duração desejada domina o pré-filtro

Antes da IA semântica, cada intervalo recebe uma pontuação rápida composta por:

- 55% proximidade da duração preferida;
- 20% início considerado natural;
- 20% fim considerado natural;
- 5% pergunta ou exclamação.

Esse pré-filtro conserva somente alguns finais por início. Assim, o corte semanticamente completo pode ser descartado antes de o Ollama avaliá-lo, enquanto um corte de aproximadamente 60 segundos, mas incompleto, avança.

### 2.3 A IA não vê o contexto necessário

O prompt atual envia somente o texto do próprio candidato, limitado a 420 caracteres — começo e final do trecho. Ele não recebe claramente:

- as falas imediatamente anteriores;
- a continuação depois do corte;
- a pergunta que originou uma resposta;
- o mapa do assunto completo;
- quem está respondendo a quem;
- o objetivo, nicho e audiência do usuário;
- dados atuais de tendências ou desempenho do canal.

Sem o trecho anterior e posterior, a IA não consegue saber se “ele”, “isso”, “porque”, “mas”, “então” ou uma resposta curta dependem de algo que ficou de fora.

### 2.4 Uma nota alta consegue esconder uma falha obrigatória

A nota atual mistura limites, hook, fluxo, valor, emoção, áudio, cena e rosto numa média. Depois, a nota semântica vale 55% e a heurística 45%. Não existe uma reprovação obrigatória para:

- pergunta sem resposta;
- resposta sem a pergunta necessária;
- história sem desfecho;
- enumeração interrompida;
- pronome sem referência;
- argumento cujo contra-argumento ou conclusão ficou fora;
- frase interrompida no limite máximo.

Além disso, o motivo começa sempre com “ideia com início e fim naturais”, mesmo quando os componentes não demonstram isso. A explicação pode transmitir uma certeza que não foi validada.

### 2.5 Evidência no vídeo real já transcrito

Foi repetido o ranking heurístico atual sobre a transcrição real de 11min07s armazenada na auditoria. Entre os 12 primeiros resultados:

- o primeiro recebeu `0,898`, começou com “Agora você tá ali...” e terminou com “Então era tipo, dois anos depois...”;
- sete terminaram objetivamente em reticências ou pergunta ainda sem resposta;
- outros começaram com referências como “Pergunta é por quê?”, “Você não tem que ganhar nada não” e “Por quê? Porque o cara...”, que precisam da fala anterior;
- um corte terminou iniciando outra história: “Então tem uma cena...”.

Isso confirma o relato do usuário: o tema ainda está sendo debatido, mas a duração, pontuação, densidade e hook fazem o intervalo subir no ranking.

Os testes atuais verificam duração, pontuação, alinhamento e baixa repetição temporal. Eles não possuem um conjunto de conversas anotadas que comprove começo independente, desenvolvimento e conclusão semântica.

## 3. O que as ferramentas pesquisadas declaram avaliar

O [OpusClip](https://help.opus.pro/docs/article/virality-score) divide sua nota pública em:

- **Hook**: a abertura chama atenção e está relacionada ao assunto principal;
- **Flow**: a história progride de forma lógica e possui conclusão satisfatória;
- **Value**: entrega utilidade, emoção ou conexão pessoal;
- **Trend**: combina com interesses e tendências atuais;
- também mede relevância em relação ao pedido do usuário.

O [ClipAnything do OpusClip](https://help.opus.pro/docs/article/9947095-clip-anything) declara usar sinais visuais, áudio e sentimento para conteúdo com ou sem diálogo. Isso é importante para esporte, gameplay, reação e cenas em que o destaque não está apenas nas palavras.

O [2short.ai](https://www.2short.ai/) declara usar as palavras faladas para localizar as partes envolventes e depois aplicar rastreamento facial, legenda e ajustes. Isso é adequado a podcasts, entrevistas, aulas e comentários.

A API do [Submagic Magic Clips](https://docs.submagic.co/api-reference/magic-clips) expõe componentes separados para força do hook, qualidade da história, impacto emocional e compartilhamento. O [HeyGen AI Clipping](https://help.heygen.com/en/articles/9278954-ai-clipping-explained) também mostra Hook, Flow, Value e Trend, além do texto completo para revisão.

Essas páginas descrevem os critérios públicos dos produtos, não revelam seus modelos, dados de treino ou fórmulas proprietárias. Logo, o CortaFlow pode adotar uma avaliação explicável semelhante, mas não deve alegar que reproduz o algoritmo de outro produto.

## 4. O que realmente pode ser medido sobre viralização

O [YouTube](https://support.google.com/youtube/answer/11914225?co=YOUTUBE._YTVideoType%3Dshorts&hl=en) informa que, ao recomendar Shorts, observa se as pessoas escolhem assistir, a duração média, o percentual médio assistido e sinais de satisfação. Também existem personalização por histórico/interesse, concorrência e variação do interesse no tema.

Nos relatórios de retenção do [YouTube Analytics](https://support.google.com/youtube/answer/9314415?hl=pt-BR), picos podem significar repetição ou compartilhamento, mas também falta de clareza; quedas indicam abandono ou salto. Portanto, um pico não pode ser usado sozinho como prova de que uma parte é boa.

O [TikTok](https://newsroom.tiktok.com/how-tiktok-recommends-videos-for-you?lang=en) descreve recomendações baseadas em interações, informações do vídeo e preferências individuais, dando mais peso a sinais fortes como terminar de assistir. As [práticas criativas oficiais do TikTok](https://ads.tiktok.com/help/article/creative-best-practices?lang=en) recomendam apresentar a proposta nos primeiros três segundos e priorizar o hook nos primeiros seis. Essa orientação é publicada para anúncios e deve ser usada como heurística criativa, não como revelação do algoritmo orgânico.

A pesquisa acadêmica de Berger e Milkman encontrou associação entre compartilhamento e utilidade, interesse, surpresa e emoções de alta ativação, como admiração, ansiedade ou raiva; tristeza, uma emoção de baixa ativação, teve menor transmissão no conjunto estudado ([Journal of Marketing Research](https://journals.sagepub.com/doi/pdf/10.1509/jmr.10.0353)). O resultado veio de artigos e experimentos, portanto ajuda a formar indicadores, mas não garante desempenho de um Short específico.

Conclusão: antes de publicar é possível estimar:

- chance de parar a rolagem;
- chance de a pessoa entender e permanecer;
- valor, novidade e emoção;
- chance de a pessoa querer comentar, salvar ou compartilhar;
- adequação a uma audiência e assunto.

Somente depois de publicar podem ser medidos retenção, conclusão, repetição, compartilhamentos e conversão reais.

## 5. Novo fluxo recomendado para decidir os cortes

### Etapa A — construir um mapa de assuntos

O texto inteiro deve ser dividido primeiro em falas e blocos semanticamente coerentes, não em janelas arbitrárias de 60 segundos.

O mapa deve registrar:

- assunto e subassunto;
- pergunta e resposta associada;
- afirmação, justificativa, exemplo e conclusão;
- história: contexto, acontecimento e desfecho;
- mudança de tema;
- continuidade com o bloco seguinte;
- possíveis falas de participantes diferentes;
- resumo curto e timestamps.

Pesquisas de segmentação de diálogo mostram que dividir conversas em tópicos é difícil porque as falas são curtas, informais e cheias de referências. Modelar a coerência entre falas adjacentes melhora essa divisão ([NAACL 2025](https://aclanthology.org/2025.naacl-long.252/), [SIGDIAL 2021](https://aclanthology.org/2021.sigdial-1.18/)). Isso confirma que pontuação e silêncio não bastam.

Implementação possível sem baixar outra IA:

1. agrupar palavras por pausa, pontuação e turno provável;
2. enviar blocos sobrepostos do texto ao Ollama já instalado;
3. pedir relações entre falas adjacentes e limites de assunto em JSON;
4. reconciliar limites nas áreas sobrepostas;
5. manter silêncio e cena apenas como apoio, nunca como prova de conclusão.

### Etapa B — gerar unidades narrativas completas

Dentro de cada assunto, o programa procura unidades de 5 a 179 segundos:

- pergunta + resposta;
- problema + explicação/solução;
- afirmação + evidência + conclusão;
- história + desfecho;
- opinião + justificativa;
- surpresa + explicação;
- piada + preparação + resultado.

A duração preferida vira um critério secundário. Se a ideia termina aos 73 segundos, não deve ser cortada aos 60. Se a conclusão ultrapassa 179 segundos e não existe uma subideia completa, o candidato deve ser rejeitado, não interrompido.

### Etapa C — auditoria obrigatória com contexto anterior e posterior

Cada candidato deve ser avaliado junto com duas a quatro falas anteriores e posteriores, ou aproximadamente 15 a 30 segundos de cada lado.

O avaliador deve responder campos objetivos:

```json
{
  "inicio_independente": true,
  "fim_resolvido": true,
  "pergunta_respondida": true,
  "referencias_compreensiveis": true,
  "mesmo_assunto_apos_o_fim": false,
  "risco_de_distorcao": "baixo",
  "acao": "manter | ampliar_inicio | ampliar_fim | rejeitar",
  "evidencia": "explicação curta baseada nas falas"
}
```

Regras de reparo:

- se começar em resposta, incluir a pergunta necessária;
- se um pronome não tiver referência, ampliar o início;
- se terminar em pergunta, incluir a resposta;
- se a fala seguinte concluir o mesmo raciocínio, ampliar o fim;
- se iniciar outro tema nos segundos finais, recuar o fim;
- se não couber completo em 179 segundos, procurar uma subideia ou rejeitar;
- se houver debate, não cortar de maneira que atribua ao participante uma posição diferente da apresentada no contexto.

Esse processo pode repetir no máximo algumas vezes até estabilizar, evitando laço infinito.

### Etapa D — barreira de validade editorial

Antes de qualquer nota viral, o candidato precisa passar por:

| Verificação | Resultado exigido |
|---|---|
| Início compreensível sem fala anterior | aprovado |
| Conclusão ou payoff presente | aprovado |
| Pergunta/resposta e referências resolvidas | aprovado |
| Fidelidade ao contexto | risco baixo |
| Transcrição suficiente para avaliar | aprovada ou marcada para retranscrição |
| Duração de 5 a 179 segundos | aprovada |
| Sem repetição relevante de outro corte | aprovada |

Os limites iniciais sugeridos de confiança devem ser calibrados com testes humanos; não devem ser transformados imediatamente em verdades fixas.

### Etapa E — relevância

“Relevante” precisa ser definido. A interface deve oferecer quatro objetivos:

1. **Equilibrado — recomendado:** assunto principal + momentos fortes e compreensíveis;
2. **Resumo fiel:** prioriza os temas centrais do vídeo;
3. **Potencial viral:** permite histórias laterais se forem muito fortes e autossuficientes;
4. **Tema solicitado:** o usuário informa assunto, pessoa, público ou objetivo.

O candidato recebe dois valores diferentes:

- **relevância para o vídeo/pedido**: quanto representa o assunto ou atende à instrução;
- **interesse independente**: quanto funciona sozinho para alguém que não viu o vídeo original.

No modo “Tema solicitado”, baixa relevância deve reprovar o candidato. No modo “Potencial viral”, um caso paralelo engraçado ou surpreendente pode permanecer, desde que o programa explique que é um assunto lateral.

### Etapa F — nota de Potencial Editorial

Somente candidatos válidos recebem nota de 0 a 100:

| Componente | Peso proposto | Pergunta avaliada |
|---|---:|---|
| Hook | 18 | Os primeiros 3–6 s apresentam tensão, curiosidade, promessa ou afirmação clara? |
| Fluxo/retenção | 18 | A progressão é clara, sem enrolação, lacunas ou queda longa? |
| Payoff/valor | 16 | Entrega resposta, aprendizado, revelação, humor ou conclusão memorável? |
| Compartilhamento | 14 | É citável, útil, identificável ou provoca conversa? |
| Emoção | 10 | Há humor, surpresa, admiração, indignação ou outra ativação genuína? |
| Novidade/especificidade | 10 | Possui exemplo, detalhe, opinião ou história pouco genérica? |
| Adequação à audiência | 8 | Combina com o público, nicho e objetivo escolhidos? |
| Força audiovisual | 6 | Voz, ritmo, expressão, cena e enquadramento sustentam o momento? |

Tendência não deve receber nota inventada. Sem consulta atual autorizada, a tela mostrará **“Tendência: não avaliada”**. Numa fase futura, a tendência poderá ser um ajuste pequeno e datado, nunca capaz de aprovar uma história incompleta.

### Etapa G — explicação útil, não apenas número

Cada sugestão deve mostrar:

- assunto do corte;
- por que começa e termina corretamente;
- hook encontrado nos primeiros segundos;
- payoff;
- para qual público pode funcionar;
- por que alguém poderia compartilhar;
- principal risco de retenção;
- nível de confiança;
- componentes da nota;
- indicação “tendência não avaliada” quando aplicável.

Exemplo:

```text
Potencial editorial: 82/100 — confiança média
Validade: aprovada
Hook: pergunta concreta sobre uma regra antiga da dublagem.
Payoff: o convidado explica a mudança e dá um caso específico.
Compartilhamento: curiosidade de bastidores e informação pouco conhecida.
Risco: a preparação demora 7 segundos; revisar se é possível iniciar na pergunta.
Tendência: não avaliada.
```

## 6. Como a IA local deve avaliar melhor

O Ollama e o modelo `cortaflow-qwen3:4b` já presentes são suficientes para testar esta arquitetura. Não é necessário baixar outro modelo agora.

Em vez de uma única pergunta pedindo uma nota livre, devem existir funções distintas:

1. **Segmentador:** cria mapa de tópicos e relações entre falas;
2. **Validador:** decide manter, ampliar ou rejeitar usando contexto externo ao corte;
3. **Avaliador:** atribui níveis por componente e cita evidências;
4. **Crítico:** procura dependência, distorção, pergunta sem resposta e final interrompido;
5. **Ranqueador global:** compara apenas candidatos aprovados e garante diversidade.

Para evitar notas quase iguais e excessivamente altas:

- usar rubricas discretas de 0 a 4 por componente;
- converter essas rubricas em pontos no código;
- exigir evidência textual/timestamp para notas altas;
- comparar candidatos do mesmo assunto entre si;
- fazer uma comparação global final;
- manter a heurística como apoio técnico, não como 45% obrigatório de uma decisão semântica;
- exibir confiança separadamente da qualidade.

Análises visuais e de áudio entram depois do texto: pesquisas de detecção de highlights mostram que áudio e imagem juntos recuperam melhor os momentos do que uma única modalidade em diversos tipos de vídeo ([ICCV 2021](https://openaccess.thecvf.com/content/ICCV2021/html/Badamdorj_Joint_Visual_and_Audio_Learning_for_Video_Highlight_Detection_ICCV_2021_paper.html)).

## 7. Aprendizado com resultados reais — fase opcional futura

O melhor preditor para um canal é o histórico do próprio canal. Com autorização explícita do usuário, uma fase futura pode:

- importar manualmente CSV de vídeos publicados; ou
- conectar a conta do próprio usuário pela API oficial do YouTube Analytics.

As métricas oficiais incluem duração média assistida, percentual médio, visualizações engajadas, curtidas, comentários, compartilhamentos e inscritos ganhos ([YouTube Analytics API](https://developers.google.com/youtube/analytics/metrics)). O programa poderia aprender, por exemplo, que determinada audiência prefere histórias de 35–50 segundos ou explicações de 70–90 segundos.

Essa integração não está aprovada neste relatório. Ela exigiria consentimento, OAuth, política de privacidade, armazenamento mínimo e opção de desconectar/apagar os dados. O sistema local deve funcionar sem conta conectada.

## 8. Fases de implementação propostas

### Fase 1 — corrigir falsas conclusões

- separar cena, pausa, frase e limite semântico;
- remover a afirmação automática de “ideia completa”;
- criar bloqueios para reticências, conectivos pendentes, perguntas sem resposta e referências sem antecedente;
- enviar contexto anterior/posterior ao validador.

Teste: casos sintéticos e os 12 cortes reais auditados. Nenhum resultado com pergunta aberta ou continuação explícita poderá ser aprovado.

### Fase 2 — mapa de assuntos

- segmentar o texto completo em tópicos e unidades narrativas;
- gerar candidatos a partir dessas unidades;
- usar duração somente como preferência;
- ampliar ou rejeitar quando a ideia não couber.

Teste: comparar limites contra marcação humana, tolerância por fala/timestamp e conservação de pergunta-resposta.

### Fase 3 — duas notas e nova interface

- validade editorial: aprovado/reprovado, com motivo;
- potencial editorial: 0–100, componentes e confiança;
- relevância separada;
- quatro objetivos de seleção;
- tendência marcada como não avaliada por padrão.

Teste: um hook alto nunca poderá superar uma reprovação editorial.

### Fase 4 — avaliação multimodal dos finalistas

- emoção/prosódia, ritmo e energia;
- rosto/falante e mudança de cena;
- qualidade visual e enquadramento;
- verificação no MP4 final.

Teste: entrevista, podcast multipessoa, aula, gameplay e vídeo sem fala.

### Fase 5 — conjunto de validação humano

- pelo menos dez vídeos controlados de gêneros diferentes;
- duas pessoas marcam começo, fim, completude, relevância e melhores momentos;
- comparação cega entre ranking atual e novo;
- registrar taxa de cortes completos, precisão dos primeiros resultados, diversidade e erros de limite.

Meta inicial proposta:

- 95% ou mais das sugestões sem dependência evidente de fala externa;
- 100% sem pergunta objetivamente aberta no final;
- nenhum corte terminado apenas por atingir a duração preferida;
- pelo menos 80% dos primeiros resultados considerados relevantes por revisores humanos;
- nenhum corte autoaceito com risco de distorção médio ou alto.

As metas devem ser confirmadas depois de construir o conjunto anotado.

### Fase 6 — calibração pós-publicação, somente se aprovada depois

- importar métricas autorizadas;
- comparar previsão com retenção/compartilhamento real;
- calibrar pesos por canal e gênero;
- nunca treinar ou enviar dados sem consentimento.

## 9. Mudanças que não exigem instalação

As Fases 1 a 5 podem usar:

- Faster-Whisper já armazenado;
- Ollama/Qwen já instalado;
- FFmpeg, PyAV, OpenCV e MediaPipe existentes;
- código determinístico para validações e pontuação.

Não é necessário instalar nova IA. Diarização de voz avançada, consulta online de tendências ou integração de Analytics ficam fora do escopo até nova autorização explícita.

## 10. Recomendação para aprovação

Recomendo aprovar as Fases 1 a 5 nesta ordem, sempre com teste antes de avançar. A Fase 6 deve permanecer separada porque envolve dados de conta e autorização externa.

Decisões propostas:

- aprovar “validade editorial” como barreira obrigatória;
- aprovar mapa de assuntos antes da geração dos cortes;
- aprovar contexto anterior/posterior e reparo de limites;
- aprovar Potencial Editorial, Relevância e Confiança como valores separados;
- aprovar os quatro objetivos de seleção;
- não afirmar que um vídeo “vai viralizar”;
- não inventar nota de tendência sem dados atuais autorizados;
- não baixar ou instalar nada;
- não criar build.

## 11. Registro da implementação aprovada

Foi implementado:

- separação entre mudança visual de cena e limite real de fala;
- corte somente entre palavras e em pausa detectada quando a análise de áudio está disponível;
- nova segmentação de discussões contínuas maiores que 179 segundos, mantendo cada corte entre 5 e 179 segundos;
- estado obrigatório de revisão para subideias retiradas de discussões maiores que 179 segundos;
- contexto de até 30 segundos antes/depois enviado à IA semântica local;
- segunda validação explícita de início independente, conclusão, relevância e importância da subideia longa;
- limites temporais protegidos: a IA semântica pode selecionar/rejeitar, mas não pode deslocar o início ou fim já validado;
- Potencial Editorial, Validade, Relevância e Confiança separados;
- tendência exibida como “não avaliada”, sem inventar dados atuais;
- objetivos Equilibrado, Fiel ao conteúdo, Maior potencial e Tema específico;
- bloqueio de aceite automático/em lote quando a validade editorial ainda exige revisão;
- aceite individual mantido como decisão humana explícita após assistir ao corte;
- maior diversidade: candidatos com sobreposição temporal relevante não são repetidos.

Perguntas completas podem ser limites físicos seguros, mas ficam em revisão e não são autoaceitas. A validação semântica consulta o contexto posterior para impedir que uma pergunta seja separada da resposta.

### Testes executados

- testes de limites, corte no meio da fala e conteúdo acima de 179 s: aprovados;
- testes do contrato semântico e rejeição editorial: aprovados;
- testes da interface, objetivos e aceite: aprovados;
- persistência e integração do fluxo automático: aprovados;
- regressão total: **198 testes aprovados**;
- teste real com a transcrição/pausas já armazenadas do vídeo de 11min07s: 331 candidatos detalhados, 8 finalistas locais e somente 1 aprovado pela IA após a calibração conservadora;
- finalista real: 230,180–408,400 s, duração 178,220 s, extraído de unidade discursiva maior que 179 s e submetido à segunda validação.

O teste real usou o Ollama/Qwen já existente na máquina. Não houve nova instalação, download, renderização ou build.

### Limites honestos restantes

- “potencial” continua sendo uma estimativa editorial, não garantia de viralização;
- a Fase 5 ainda precisa da avaliação cega por duas pessoas reais para validar relevância humana; testes automatizados não substituem revisores;
- métricas pós-publicação e tendências atuais continuam fora do sistema até autorização específica.
