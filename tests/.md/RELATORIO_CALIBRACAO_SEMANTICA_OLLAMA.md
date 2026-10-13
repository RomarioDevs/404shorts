# Relatório — calibração semântica local para seleção de cortes

Data: 13 de agosto de 2026  
Projeto: CortaFlow AI 0.1.0  
Status: Fases 1 e 2 aprovadas, implementadas e testadas. Nenhum programa/modelo foi instalado ou baixado e nenhum build foi criado.

## 1. Conclusão executiva

O resultado de zero cortes no vídeo do Leonardo Jardim não foi causado pela transcrição, pelas pausas, pelo Ollama ou pelo modelo errado. Foi causado por uma regra de decisão excessivamente rígida e por confiar em campos contraditórios produzidos por um modelo pequeno.

A solução recomendada é manter o `cortaflow-qwen3:4b` inicialmente e mudar a calibração em cinco pontos:

1. o código valida limites físicos de fala;
2. o Ollama devolve observações e evidências, não a decisão final;
3. o programa calcula a validade editorial sem aceitar campos contraditórios;
4. candidatos rejeitados por falta de contexto são ampliados e avaliados outra vez;
5. se nenhum passar, os melhores aparecem como **Revisar**, nunca como tela vazia e nunca autoaceitos.

Trocar diretamente para um modelo maior pode diminuir alguns erros, mas não corrige uma lógica que exige respostas internamente contraditórias. O melhor modelo compatível com o hardware para um teste posterior é o **Qwen3 8B Q4**, mas ele exige download oficial de aproximadamente 5,2 GB e somente deve ser instalado depois de autorização específica.

## 2. Evidência do teste real

Vídeo analisado:

`LEONARDO JARDIM RESPONDE ESCOLHA PELO FLAMENGO... [RSl2WV6a6Bo].mp4`

Resultados antes do Ollama:

- duração: 162,414 segundos;
- transcrição: 411 palavras e 65 grupos de legenda;
- idioma: português, confiança aproximada de 97%;
- pausas detectadas: 10;
- limites naturais enumerados: 1.247;
- candidatos detalhados: 89;
- finalistas heurísticos seguros: 3.

Finalistas:

| Intervalo | Duração | Situação anterior ao Ollama |
|---|---:|---|
| 00:00,000–00:59,060 | 59,060 s | validado fisicamente |
| 00:59,600–01:57,850 | 58,250 s | validado fisicamente |
| 01:39,430–02:41,800 | 62,370 s | validado fisicamente |

Para o terceiro corte, o Qwen devolveu simultaneamente:

- `editorial_valid = true`;
- `completeness = 4/4`;
- `relevance = 4/4`;
- `ending_complete = true`;
- `confidence = 1.0`;
- `opening_independent = false`;
- motivo textual dizendo que a ideia era relevante, completa e integrada ao contexto.

O programa exige que todos os campos booleanos sejam verdadeiros e, por isso, descartou o corte. Os outros dois também foram descartados. A interface apenas mostrou `0 cortes` e não explicou as reprovações.

Essa resposta demonstra dois problemas de calibração:

1. a confiança verbalizada pelo próprio modelo não é confiável: ele declarou 100% de confiança em uma resposta contraditória;
2. `editorial_valid` duplica outras decisões e permite estados logicamente impossíveis.

## 3. O que a pesquisa confirma

### 3.1 Saída estruturada garante formato, não coerência

O Ollama permite impor um JSON Schema e recomenda Pydantic para validar a resposta. A documentação também recomenda temperatura baixa — por exemplo, `0` — para saídas mais determinísticas. Entretanto, um schema garante tipos e campos; ele não garante que `editorial_valid=true` seja coerente com `opening_independent=false`.

Fonte: [Ollama — Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs).

### 3.2 Avaliadores LLM precisam de etapas e calibração

O G-Eval obteve melhor alinhamento humano ao decompor a avaliação em critérios/etapas e usar preenchimento estruturado, mas também documentou vieses dos avaliadores LLM. Trabalhos posteriores mostram viés de posição e recomendam testar a consistência ao inverter a ordem dos candidatos.

Fontes: [G-Eval, EMNLP 2023](https://aclanthology.org/2023.emnlp-main.153/), [estudo de viés de posição, IJCNLP/AACL 2025](https://aclanthology.org/2025.ijcnlp-long.18/), [Google Research — calibrating autoraters](https://research.google/pubs/judging-with-confidence-calibrating-autoraters-to-preference-distributions/).

### 3.3 Pensamento pode ser testado, mas não deve substituir regras

O Ollama suporta `think=true` para Qwen3, separando o raciocínio da resposta final. O Qwen3 oficial alterna entre modo thinking e non-thinking e suporta mais de 100 idiomas. Um A/B pode verificar se thinking reduz contradições, mas o resultado ainda precisa ser validado pelo código.

Fontes: [Ollama — Thinking](https://docs.ollama.com/capabilities/thinking), [Qwen3 oficial](https://qwenlm.github.io/blog/qwen3/).

### 3.4 “Viralidade” só pode ser um potencial anterior à publicação

O OpusClip publica quatro fatores: Hook, Flow, Value e Trend. YouTube informa que Shorts são classificados usando escolha de assistir, duração média, porcentagem assistida e satisfação. TikTok informa que interações e conclusão do vídeo têm peso importante. Sem métricas reais do canal, o CortaFlow só pode estimar sinais editoriais que favorecem retenção e compartilhamento; não pode prometer viralização.

Fontes: [OpusClip — Virality Score](https://help.opus.pro/docs/article/virality-score), [YouTube — Search and discovery tips for Shorts](https://support.google.com/youtube/answer/11914225?co=YOUTUBE._YTVideoType%3Dshorts&hl=en-GB), [TikTok — How TikTok recommends videos](https://newsroom.tiktok.com/how-tiktok-recommends-videos-for-you?lang=en).

## 4. Nova arquitetura de calibração proposta

```text
TRANSCRIÇÃO + PAUSAS
        │
        ▼
LIMITE FÍSICO SEGURO (código determinístico)
        │
        ▼
AUDITOR SEMÂNTICO INDIVIDUAL (Ollama)
  devolve observações + evidências
        │
        ▼
DECISÃO EDITORIAL (calculada pelo código)
        │
  ┌─────┴──────────┐
  │ válido         │ reparável
  ▼                ▼
ranking       ampliar/reduzir em pausas
  │                │
  │                └── reavaliar uma vez
  ▼
COMPARAÇÃO ENTRE FINALISTAS
        │
        ▼
PRÉVIAS / REVISÃO HUMANA
```

### 4.1 Porta A — segurança física obrigatória

Continuar determinística:

- início/fim em timestamps reais de palavras;
- usar pausas de áudio, nunca mudança visual de cena como pausa de fala;
- duração entre 5 e 179 segundos;
- não terminar no meio de palavra;
- para conteúdo maior que 179 segundos, extrair uma subideia e marcá-la para segunda verificação.

O Ollama não pode alterar timestamps físicos aprovados.

### 4.2 Porta B — observações semânticas, sem decisão duplicada

Remover do modelo o campo `editorial_valid`. Pedir campos observáveis:

- `topic_stated_in_clip`: o assunto é mencionado dentro do corte;
- `opening_dependency`: `none`, `repairable` ou `strong`;
- `unresolved_references`: lista curta de “isso”, “ele”, “essa questão” sem antecedente;
- `question_answer_complete`: pergunta e resposta estão juntas;
- `ending_state`: `complete`, `repairable` ou `ongoing`;
- `after_continues_same_answer`: o contexto posterior continua a resposta;
- `central_claim`: resumo de uma frase;
- `evidence_start` e `evidence_end`: pequenos trechos da transcrição que sustentam a decisão;
- notas de relevância, hook, valor e compartilhamento de 0 a 4.

O programa calcula a decisão. Estados contraditórios deixam de ser possíveis.

### 4.3 Regra editorial calculada pelo programa

Proposta inicial:

```text
VALIDADO se:
  limite físico seguro
  AND topic_stated_in_clip
  AND completeness >= 3
  AND ending_state == complete
  AND after_continues_same_answer == false
  AND relevance >= 2
  AND (opening_dependency == none OR question_answer_complete)

REPARAR se:
  limite físico seguro
  AND opening_dependency == repairable
  OR ending_state == repairable

REJEITAR se:
  fala cortada
  OR ending_state == ongoing
  OR relevância < 2
  OR dependência forte que não cabe em 179 s
```

A nota `3` significa “bom” na própria rubrica atual; exigir sempre `4` transforma “excelente” em requisito mínimo e elimina material válido. A mudança para `>=3` deve ser testada, não aplicada isoladamente.

### 4.4 Reparo automático dos limites

Quando o candidato for `repairable`:

1. se falta contexto no começo, ampliar para uma ou duas pausas seguras anteriores;
2. se a resposta continua, ampliar para uma ou duas pausas posteriores;
3. se passar de 179 s, localizar a subideia central mais importante dentro da unidade;
4. reavaliar somente uma vez para evitar loop;
5. preservar o candidato original como diagnóstico, sem exportá-lo automaticamente.

No vídeo do Leonardo Jardim, o corte de 01:39,430–02:41,800 deveria ser testado com uma ampliação anterior. Outra opção forte é avaliar o intervalo combinado de aproximadamente 00:59,600–02:41,800, ainda abaixo de 179 segundos.

### 4.5 Comportamento quando nenhum corte passa

Nunca mostrar apenas uma tabela vazia quando existirem candidatos físicos seguros.

Ordem recomendada:

1. executar reparo automático;
2. avaliar os próximos candidatos do pré-filtro;
3. se ainda não houver válido, mostrar até três candidatos como `Revisar conteúdo/limites`;
4. bloquear aceite automático/em lote;
5. explicar em cada linha exatamente o que faltou.

Assim o usuário não recebe um falso “não existe conteúdo”, e a regra de segurança continua intacta.

## 5. Ranking com menor risco de viés

Separar **aprovação** de **ordenação**:

1. avaliação individual: cada candidato passa ou não pela porta editorial;
2. ranking listwise/pairwise: somente os aprovados são comparados entre si;
3. inverter a ordem dos candidatos e repetir a comparação;
4. resultado estável somente se as duas ordens concordarem;
5. divergências ficam como `confiança baixa`.

Não usar `confidence` declarado pelo modelo. Calcular:

```text
confiança =
  40% concordância entre duas avaliações
  30% cobertura das evidências exigidas
  20% segurança dos limites físicos
  10% estabilidade com ordem invertida
```

Isso responde diretamente ao erro observado: `confidence=1.0` não terá poder para esconder contradições.

## 6. Potencial editorial proposto

Validade continua sendo porta, não componente compensável. Depois da aprovação:

| Componente | Peso inicial |
|---|---:|
| Hook e clareza nos primeiros segundos | 25% |
| Fluxo e entrega/conclusão | 25% |
| Valor concreto ou novidade | 20% |
| Relevância para tema/audiência | 15% |
| Emoção e possibilidade de compartilhamento | 10% |
| Áudio, rosto e qualidade visual | 5% |

`Trend` permanece **não avaliada** sem consulta atual autorizada. Duração não recebe peso alto: ela é restrição/preferência, não sinal de viralidade.

## 7. Configuração recomendada para o Ollama atual

Configuração proposta para teste A/B, sem trocar modelo:

- modelo: `cortaflow-qwen3:4b`;
- JSON Schema/Pydantic: manter;
- repetir o schema também no prompt, conforme recomendação do Ollama;
- temperatura: testar `0` contra o `0.1` atual;
- primeira etapa: candidato individual, não seis candidatos no mesmo julgamento;
- segunda etapa: ranking listwise apenas dos aprovados;
- `think=false` como teste rápido;
- `think=true` como variante de qualidade, registrando tempo e contradições;
- contexto antes/depois organizado em frases, não apenas caracteres truncados;
- nenhuma confiança verbalizada usada diretamente.

O thinking pode aumentar latência. Ele só deve ser adotado se reduzir erros no conjunto real.

## 8. Modelos locais alternativos

Hardware detectado:

- CPU: AMD Ryzen 5 5600G, 6 núcleos/12 threads;
- RAM: 31,8 GB;
- GPU: NVIDIA RTX 3060 com 8 GB de VRAM;
- Ollama: 0.32.9.

| Opção | Tamanho aproximado | Adequação | Recomendação |
|---|---:|---|---|
| Qwen3 4B atual | 2,5 GB | rápido; português; apresentou contradições | manter na Fase 1 |
| Qwen3 8B Q4 | 5,2 GB | cabe melhor na RTX 3060 8 GB; mesma família; mais capacidade | melhor A/B posterior |
| Gemma 3 4B | 3,3 GB | 140+ idiomas; alternativa de família | útil como comparação, não prioridade |
| Gemma 3 12B Q4 | 8,1 GB | modelo sozinho já excede/ocupa toda a VRAM disponível | não recomendado para uso interativo nesta máquina |
| Prometheus 2 | classe 7B/8x7B | especializado em rubricas de avaliação | pesquisa posterior; não otimizado especificamente para português/cortes |

Fontes: [Qwen3 no Ollama](https://ollama.com/library/qwen3/tags), [Qwen3-8B oficial](https://huggingface.co/Qwen/Qwen3-8B), [Gemma 3 oficial](https://ai.google.dev/gemma/docs/core/model_card_3), [Gemma 3 no Ollama](https://ollama.com/library/gemma3), [Prometheus oficial](https://github.com/prometheus-eval/prometheus).

Nenhum desses modelos deve ser baixado sem autorização. O Qwen3 8B é a única troca que recomendo testar logo depois da correção lógica.

## 9. Bibliotecas/modelos complementares

### 9.1 Sentence Transformers + modelo multilíngue pequeno

Uso:

- criar embeddings por frase;
- detectar mudança de assunto;
- eliminar cortes semanticamente duplicados;
- medir relevância a um tema solicitado.

O `paraphrase-multilingual-MiniLM-L12-v2` possui cerca de 0,1 bilhão de parâmetros, vetor de 384 dimensões e suporte declarado a 50 idiomas. É muito menor que um LLM gerador.

Fontes: [modelo oficial](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2), [documentação de similaridade](https://sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html).

Recomendação: **boa para Fase 2**, após autorização de instalação/modelo.

### 9.2 `ruptures`

Uso:

- aplicar detecção de mudança de ponto sobre embeddings das frases;
- criar unidades de tópico antes de gerar janelas de 5–179 s.

É uma biblioteca Python BSD para change-point detection e inclui PELT e modelos por kernel. Ela não entende texto sozinha; precisa dos embeddings.

Fonte: [`ruptures` oficial](https://github.com/deepcharles/ruptures).

Recomendação: **útil junto com embeddings**, não isoladamente.

### 9.3 `wtpsplit` / Segment Any Text

Uso:

- reconstruir limites de frase em transcrições com pontuação fraca;
- funciona sem depender apenas de `.?!`;
- lista português entre os idiomas suportados.

Fontes: [`wtpsplit` oficial](https://github.com/segment-any-text/wtpsplit), [artigo Segment Any Text](https://arxiv.org/abs/2406.16678).

Recomendação: **opcional**, principalmente se os testes encontrarem transcrições com pontuação ruim. Não corrige sozinho o zero cortes do caso atual.

### 9.4 BGE reranker multilíngue

O `BAAI/bge-reranker-v2-m3` é um reranker multilíngue de aproximadamente 0,6 bilhão de parâmetros. Pode receber uma intenção (“momentos mais relevantes sobre a escolha pelo Flamengo”) e devolver relevância para cada passagem.

Fonte: [modelo oficial BAAI](https://huggingface.co/BAAI/bge-reranker-v2-m3).

Recomendação: **opcional para relevância**, não para decidir se uma fala termina completa.

### 9.5 Bibliotecas que não resolvem este defeito

- `pyannote.audio`: melhora diarização e troca de falantes, mas exige outra pilha/modelos e não resolve contradição editorial;
- Silero VAD: pode melhorar detecção de voz, mas as dez pausas deste vídeo já foram encontradas corretamente;
- modelos de visão maiores: ajudam em vídeos sem fala, mas o defeito atual aconteceu depois da transcrição.

Não recomendo instalar essas opções para corrigir o problema de zero cortes.

## 10. Plano proposto para aprovação

### Fase 1 — correção lógica, sem nova instalação

- remover a decisão duplicada `editorial_valid` da resposta do modelo;
- criar estados `validado`, `reparável`, `rejeitado`;
- completude mínima inicial `>=3`, mantendo finais em andamento bloqueados;
- implementar reparo de limites;
- mostrar candidatos em revisão se o ranking final ficar vazio;
- temperatura 0;
- testes de consistência do JSON.

Teste obrigatório:

- vídeo Leonardo Jardim deve mostrar pelo menos um candidato validado ou candidatos explicados como Revisar;
- nenhum corte pode ser autoaceito com fala/ideia em andamento;
- resposta contraditória não pode zerar silenciosamente a tela.

### Fase 2 — avaliação estável, sem novo modelo

- duas avaliações com ordem invertida;
- confiança calculada pelo programa;
- comparação listwise apenas entre aprovados;
- testar `think=false` e `think=true`;
- registrar tempo, concordância e número de reparos.

### Fase 3 — segmentação semântica opcional

Somente com nova autorização:

- instalar Sentence Transformers e modelo multilíngue pequeno;
- opcionalmente instalar `ruptures`;
- formar mapa de tópicos e reduzir candidatos repetidos.

### Fase 4 — A/B com Qwen3 8B

Somente com autorização de download oficial:

- baixar `qwen3:8b` pelo Ollama oficial;
- repetir exatamente o conjunto de vídeos com 4B e 8B;
- comparar completude, contradição, relevância, tempo e VRAM;
- manter 8B somente se a melhora justificar latência/armazenamento.

### Fase 5 — calibração humana

- duas pessoas marcam limites, completude e melhores momentos;
- usar pelo menos dez vídeos e os dois vídeos reais já testados;
- calcular precisão, cobertura, concordância e taxa de tela vazia;
- calibrar pesos com essas marcações, não com a autoconfiança do modelo.

## 11. Critérios de aprovação

Recomendo aprovar agora apenas as Fases 1 e 2, porque não exigem instalação nem download.

Metas:

- zero cortes no meio da fala;
- nenhuma contradição lógica aceita;
- nenhuma tela vazia sem explicação quando houver candidatos físicos;
- pelo menos um reparo tentado antes de rejeitar todos;
- nenhum candidato `Revisar` autoaceito;
- redução mensurável de falsos zeros no conjunto real;
- potencial apresentado como estimativa, nunca promessa de viralização.

Fases 3 e 4 ficam aguardando autorização separada porque exigem bibliotecas ou modelos adicionais.

## 12. Resultado da implementação aprovada

### 12.1 Alterações efetivamente aplicadas

Fase 1:

- removido `editorial_valid` e os demais campos de decisão duplicada da resposta do modelo;
- o Ollama agora devolve assunto, dependência da abertura, estado do fim, contexto posterior, afirmação central e evidências curtas;
- completude mínima alterada de `4/4` para `3/4`, sem permitir fim em andamento;
- temperatura alterada de `0.1` para `0`;
- o pré-filtro conserva alternativas sobrepostas somente para poder ampliar começo/fim com limites físicos já seguros;
- um limite reparável é ampliado e reavaliado no máximo uma vez;
- falha técnica ou ausência de aprovado mostra até três itens `needs_review`, nunca os autoaceita e não deixa a tabela falsamente vazia.

Fase 2:

- cada lote é avaliado duas vezes com os mesmos índices e ordem invertida;
- a reconciliação é conservadora: divergência editorial não vira aprovação;
- a confiança passou a ser calculada pelo programa com acordo das decisões, evidências encontradas literalmente, segurança física e estabilidade à inversão;
- perguntas seguidas de respostas e aberturas que nomeiam explicitamente o assunto são verificadas também na própria transcrição, corrigindo falsos negativos do modelo 4B;
- o ranking final passou a proibir qualquer sobreposição temporal entre cortes; versões sobrepostas continuam existindo apenas durante o reparo.

O modo `think=false` foi mantido no caminho funcional. `think=true` não foi ativado: a dupla avaliação já elevou o teste real para aproximadamente seis minutos e ainda não existe um conjunto humano anotado que demonstre ganho de qualidade suficiente para justificar mais latência. Esse A/B permanece uma calibração posterior, sem instalação.

### 12.2 Testes do vídeo Leonardo Jardim

Arquivo:

`LEONARDO JARDIM RESPONDE ESCOLHA PELO FLAMENGO APÓS DIZER QUE NÃO TREINARIA OUTRO CLUBE NO BRASIL [RSl2WV6a6Bo].mp4`

Entrada repetida em todos os testes:

- duração: 162,414 s;
- transcrição local: 411 palavras e 65 legendas;
- 184 combinações de limites naturais no gerador atual;
- 100 candidatos passaram pela avaliação detalhada;
- 24 alternativas, incluindo expansões seguras, chegaram ao auditor semântico;
- nenhum download foi permitido pelo transcritor.

Evolução observada:

| Etapa | Resultado |
|---|---|
| implementação anterior | 0 cortes, devido à contradição booleana |
| Fase 1 | 1 corte validado, 01:33,950–02:26,320 |
| primeira execução da Fase 2 | 3 itens explicados como `needs_review`; revelou falso negativo sistemático do 4B |
| Fase 2 após verificação determinística do texto | 3 candidatos semanticamente validados, sem erro do Ollama |
| filtro final sem repetição | 2 dos 3 podem permanecer juntos; o terceiro é removido por sobreposição temporal |

Candidatos semanticamente válidos da última auditoria, antes do filtro final de repetição:

| Intervalo | Duração | Confiança calculada | Resultado |
|---|---:|---:|---|
| 00:09,020–01:13,720 | 64,700 s | 100,0% | validado |
| 00:59,600–01:57,850 | 58,250 s | 92,5% | validado, mas sobrepõe os outros e não entra junto no resultado final |
| 01:39,430–02:41,800 | 62,370 s | 77,5% | validado |

Com a regra final de não repetição, os intervalos 00:09,020–01:13,720 e 01:39,430–02:41,800 são compatíveis entre si. O intervalo intermediário é uma alternativa, não um terceiro corte simultâneo.

Tempo observado na auditoria completa da Fase 2: 372,5 s no computador testado, incluindo transcrição e oito consultas semânticas (`4 lotes × 2 ordens`). Esse número não inclui detecção visual, geração de prévia ou exportação.

### 12.3 Verificação automatizada

- testes focados de seleção e ranking semântico: `21 passed`;
- suíte completa: `202 passed`;
- casos novos cobrem ordem invertida, confiança calculada, divergência obrigando revisão, reparo único, falso negativo de assunto explícito e zero sobreposição final;
- nenhum instalador/build foi gerado.

### 12.4 Pendências que continuam exigindo aprovação separada

Não foram instalados Sentence Transformers, `ruptures`, outro reranker, Qwen3 8B, Gemma ou qualquer modelo adicional. As Fases 3 e 4 continuam apenas como proposta. A próxima evolução de qualidade deve começar por um conjunto de vídeos marcado por pessoas; só então vale comparar `think=true` ou um modelo maior com métricas objetivas.
