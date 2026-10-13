# Relatório de auditoria — cortes automáticos e comparação de mercado

Data da auditoria: 13 de agosto de 2026  
Projeto: CortaFlow AI 0.1.0  
Ambiente: Windows x86-64, Python 3.11.9, NVIDIA RTX 3060 8 GB  
Vídeo solicitado: `https://www.youtube.com/watch?v=sP3N8HRHFkw`

## 1. Resposta direta

É possível fazer o fluxo desejado:

```text
link/arquivo → áudio → transcrição → compreensão do texto → seleção dos melhores
momentos entre 5 e 179 s → corte → legenda → reenquadramento → prévia/exportação
```

O CortaFlow atual já executa várias partes desse fluxo, mas ainda não é equivalente ao 2short.ai ou ao OpusClip:

- transcreve localmente com Faster-Whisper;
- gera timestamps por palavra e legendas;
- detecta frases, silêncios e cenas;
- sugere trechos e calcula uma nota heurística;
- detecta e acompanha rostos;
- gera prévia/exportação vertical.

Porém, atualmente:

- não usa um modelo semântico para compreender assunto, contexto, valor ou emoção;
- não aceita uma faixa configurável de 5 a 179 segundos;
- usa alvos fixos de 15, 30, 45, 60 e 90 segundos;
- pode gerar um trecho um pouco menor para terminar em uma frase completa — no teste, gerou 10,8 segundos;
- apenas sugere cortes pendentes; não os aprova e exporta sozinho;
- não usa energia de áudio e presença de rosto na pontuação dos cortes, embora esses dados existam em outros serviços do projeto.

Para a seleção semântica comparável aos exemplos, será necessário baixar uma IA adicional uma vez. O Faster-Whisper entende **o que foi falado**, mas não foi projetado para decidir sozinho **qual trecho é mais importante ou atraente**.

## 2. Pesquisa dos produtos de referência

As informações abaixo são declarações públicas dos próprios produtos, não uma reprodução de seus algoritmos proprietários.

### 2short.ai

O [site oficial do 2short.ai](https://www.2short.ai/) informa que o serviço:

- usa conteúdo falado/legendas para localizar partes atraentes;
- exige que o vídeo possua legendas disponíveis;
- oferece rastreamento facial do falante;
- aplica legendas animadas;
- exporta em 1080p e oferece proporções vertical, quadrada e horizontal;
- possui ajustes de corte, marca e sobreposições.

Uma [demonstração pública do 2short.ai](https://app.2short.ai/shorts?language=en&youtubeVideoId=LsYnnI1H5rA) exibe cortes de duração variável, por exemplo 23, 28, 32, 41, 48, 53, 59, 81 e 88 segundos. O site não publica a fórmula exata de seleção.

### OpusClip

O [site oficial do OpusClip](https://www.opus.pro/) descreve um modelo multimodal que considera sinais visuais, áudio, texto e sentimento. A documentação informa:

- duração automática de até três minutos e faixas 0–30, 30–60, 60–90 e 90–180 segundos ([seleção de duração](https://help.opus.pro/docs/article/select-clip-length), [preferências da API](https://help.opus.pro/api-reference/schemas/curation-preferences));
- nota de viralidade de 0 a 99 baseada em **Hook**, **Flow**, **Value** e **Trend** ([Virality Score](https://help.opus.pro/docs/article/virality-score));
- rastreamento automático de falante com voz e movimento, além de correção manual ([Subject Tracking](https://help.opus.pro/docs/article/subject-tracking));
- layouts Fill, Fit, Split, três/quatro pessoas, compartilhamento de tela e gameplay ([Layout and Reframing](https://help.opus.pro/docs/article/layout-and-reframing));
- busca de momentos por palavras-chave ou instruções em linguagem natural ([Prompts](https://help.opus.pro/docs/article/select-keywords));
- edição por texto, remoção de frases, legendas, B-roll e publicação.

O CortaFlow tem uma vantagem potencial: seu pipeline principal é local e pode manter vídeo, áudio e rostos no computador. 2short.ai e OpusClip funcionam como serviços web.

## 3. Resultado dos testes

### 3.1 Vídeo solicitado

| Etapa | Resultado | Evidência |
|---|---|---|
| Validação da URL | Passou | URL pública HTTPS aceita |
| Consulta dos metadados | Passou após correção TLS | Título correto, YouTube, 668 s, miniatura e formatos encontrados |
| Download do vídeo | **Falhou** | HTTP 403 ao transferir o formato 360p |
| Causa do download | Identificada | Não há Deno/Node/QuickJS e o YouTube atual exige resolução de desafios JavaScript |

A documentação atual do [yt-dlp EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS) informa que downloads do YouTube precisam de um runtime JavaScript e dos scripts `yt-dlp-ejs`. Deno 2.3 ou superior é a opção recomendada. Isso não é uma IA e não deve ser instalado silenciosamente; a aplicação precisa detectar o requisito e obter consentimento do usuário.

Como o download real ficou bloqueado, as etapas seguintes foram validadas com fixtures locais controladas, a miniatura pública do próprio vídeo e voz sintética pt-BR do Windows. Não houve tentativa de contornar o bloqueio, usar cookies ou burlar controles de acesso.

### 3.2 Transcrição e legendas

| Teste | Resultado |
|---|---|
| Download inicial do Faster-Whisper `small` | Bloqueado inicialmente pela cadeia TLS; concluído na auditoria usando certificados confiáveis do Windows |
| Tamanho medido do modelo no cache | 463,7 MiB |
| Detecção da RTX 3060 | Detectou `CUDA/float16` |
| Inferência CUDA real | Falhou por bibliotecas CUDA/cuDNN de execução incompletas |
| Fallback para CPU | Passou automaticamente |
| Voz sintética pt-BR | 26 palavras, idioma pt com probabilidade 1,0 |
| Agrupamento | Quatro blocos de legenda |
| JSON, SRT e ASS | Passaram; arquivos válidos foram criados |
| Queima da legenda com FFmpeg/libass | Passou tecnicamente |
| Legenda em corte iniciado no meio do vídeo | **Falhou visualmente** |
| Legibilidade da legenda animada na prévia 540×960 | **Falhou visualmente**: texto excessivamente grande e cortado |

Problemas encontrados na legenda:

1. Os tempos das legendas não são recortados e deslocados em relação ao início do corte. Um corte iniciado em 4,35 s mostrou palavras do começo do vídeo.
2. A resolução lógica do ASS e o tamanho da fonte não são adaptados à resolução de prévia/saída.
3. A animação por palavra usa cores padrão inadequadas e parte do texto sai do quadro.
4. A regra de duas linhas e a margem segura não são garantidas no render final.

### 3.3 Cenas, silêncio e sugestão

Na amostra falada de 17,87 segundos:

- cenas detectadas: 0, como esperado para fundo estático;
- silêncios detectados: 2;
- sugestões: 1;
- corte sugerido: 4,35 s a 15,15 s;
- duração: 10,8 s;
- nota: 79,3%;
- título: “A inteligência artificial transforma a fala em texto”;
- motivo: frase completa, boa densidade de fala e pouco silêncio.

Isso comprova que a heurística atual gera uma sugestão coerente. Não comprova compreensão semântica profunda ou potencial de viralização.

### 3.4 Rostos, falante e reenquadramento

Foi usado o pacote oficial [MediaPipe Face Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/index), com 3.758.596 bytes.

Resultados:

- 89 observações faciais;
- um ID temporário consistente;
- 89 medições de boca;
- 89 keyframes de reenquadramento;
- 89 decisões de falante, 17 incertas;
- prévia 9:16 manteve o rosto centralizado;
- nenhuma identificação biométrica foi feita.

Limitação: a amostra usa imagem estática com um rosto. O pipeline funcionou, mas a precisão com duas pessoas falando alternadamente ainda precisa de um vídeo real anotado. A lógica atual também pode manter um rosto específico mesmo quando a decisão está marcada como incerta; o comportamento de enquadramento de grupo precisa ser corrigido e testado.

### 3.5 Renderização e exportação

| Teste | Resultado |
|---|---|
| Prévia vertical | Passou em 540×960 |
| Encoder | `h264_nvenc` |
| Velocidade medida na amostra | 10,7× |
| Arquivo temporário e publicação atômica | Passou |
| Progresso | Passou |
| Legenda no corte | Falhou na sincronização/legibilidade |
| Linha do tempo completa no render final | **Não implementada** |

A exportação profissional atual recebe um único intervalo, legendas e keyframes. Ela não recebe nem aplica a sequência completa da linha do tempo. Portanto, estes controles existem na interface e no projeto, mas ainda não alteram corretamente o vídeo final:

- remoção/movimentação de vários clipes da linha do tempo;
- transições entre clipes;
- volume configurado no painel;
- proporções 1:1, 4:5 e original;
- parâmetros configuráveis de suavização, velocidade e zoom em todo o pipeline.

### 3.6 Suíte automatizada

- 114 testes automatizados coletados e aprovados;
- testes unitários, integração FFmpeg e widgets Qt;
- inicialização em smoke-test aprovada;
- dependências sem conflitos reportados por `pip check`.

Os testes automatizados anteriores verificavam principalmente estrutura e geração de arquivo. A auditoria visual revelou problemas de sincronização e escala de legendas que não estavam cobertos.

## 4. Comparação resumida

| Capacidade | CortaFlow atual | 2short.ai | OpusClip |
|---|---|---|---|
| Transcrição | Local, Faster-Whisper | Usa legendas/fala | Automática, multilíngue |
| Compreensão semântica | Não; heurística textual | Declarada | Multimodal declarada |
| Duração variável | Parcial, alvos até 90 s | Variável | Até 180 s/API; auto até 3 min |
| Nota explicável | Nota heurística 0–100% e motivo | Não detalhada publicamente | Virality Score 0–99 com fatores |
| Corte automático sem revisão | Não | Fluxo simplificado | Sim, com revisão posterior |
| Legenda animada | Existe, mas falhou visualmente no corte | Sim | Sim |
| Rosto/falante | Local, parcialmente validado | Rastreamento central | Voz+movimento, layouts avançados |
| Editor por texto | Correção de legenda | Ferramentas de edição | Sim |
| Layouts múltiplos | Controles não ligados ao render | Várias proporções | Fill/Fit/Split/etc. |
| B-roll, marca e publicação | Não | Presets de marca | B-roll, marca e publicação |
| Privacidade local | Sim, no pipeline de análise | Serviço web | Serviço web |

## 5. Mudanças propostas

### Etapa A — Confiabilidade obrigatória

1. Adicionar e documentar o runtime Deno oficial e o pacote correspondente `yt-dlp-ejs`.
2. Detectar a ausência de EJS antes do download e apresentar instrução clara.
3. Integrar o armazenamento de certificados do Windows ao Hugging Face, sem desativar TLS.
4. Criar um gerenciador de modelos com origem, licença, tamanho, progresso, checksum e opção de remoção.
5. Fazer um teste real de CUDA/cuDNN no diagnóstico; não mostrar “CUDA” apenas porque a GPU foi enumerada.
6. Manter fallback CPU e mensagens que indiquem a biblioteca NVIDIA ausente.

Critério de aprovação: analisar e baixar um vídeo autorizado, baixar o modelo em uma instalação limpa, transcrever em GPU ou explicar/fazer fallback sem falha genérica.

### Etapa B — Seleção inteligente entre 5 e 179 segundos

1. Adicionar controles `duração mínima`, `duração máxima`, quantidade e modo automático.
2. Gerar candidatos em todos os limites de frase/pausa/cena dentro de 5–179 s, em vez de testar somente cinco alvos.
3. Combinar de verdade:
   - completude da ideia e ausência de fala cortada;
   - hook nos primeiros segundos;
   - fluxo e conclusão;
   - valor/informação, pergunta, opinião e emoção;
   - densidade de fala, energia, silêncio e prosódia;
   - mudanças de cena e presença/continuidade de rosto;
   - diversidade para não repetir o mesmo assunto.
4. Criar interface substituível `ClipRanker`, mantendo a heurística como fallback.
5. Exibir componentes da nota, não apenas um número opaco.
6. Permitir “aceitar automaticamente acima de X%”, mas conservar a prévia antes do render final.

### Etapa C — IA semântica local recomendada

Opção recomendada: arquitetura híbrida.

- Pré-filtro leve e determinístico reduz centenas de candidatos para aproximadamente 20–40.
- Um modelo semântico local avalia somente esses candidatos e retorna JSON validado com nota, título, motivo e limites sugeridos.
- O vídeo não sai do computador.
- Se o modelo não estiver instalado, a heurística continua funcionando.

Modelos tecnicamente possíveis para avaliação:

- [`multilingual-e5-small`](https://huggingface.co/intfloat/multilingual-e5-small), MIT, suporte multilíngue e embeddings leves; melhora agrupamento, relevância e diversidade, mas sozinho não raciocina como um editor;
- [`Qwen3-4B`](https://huggingface.co/Qwen/Qwen3-4B), Apache-2.0, 4 bilhões de parâmetros, mais de 100 idiomas e contexto nativo de 32.768 tokens; uma quantização GGUF de 4 bits deve ser avaliada com `llama.cpp` na RTX 3060.

O tamanho exato depende do artefato aprovado. Uma quantização de 4 bits de um modelo de 4B normalmente ocupa alguns gigabytes. Antes da implementação, será obrigatório escolher uma publicação confiável, validar SHA-256, licença e desempenho. Não se deve baixar uma quantização aleatória.

O [`llama.cpp`](https://github.com/ggml-org/llama.cpp) suporta CUDA e quantizações, mas acrescenta binários/DLLs e obrigações de empacotamento. Essa dependência só deve ser adicionada após aprovação.

### Etapa D — Corrigir legendas e ligar o editor ao render

1. Recortar as cues para cada intervalo e subtrair o tempo inicial do corte.
2. Recortar também timestamps por palavra para o destaque animado correto.
3. Definir `PlayResX/PlayResY`, quebra em até duas linhas, largura e margem segura.
4. Criar testes visuais em 540×960, 720×1280 e 1080×1920.
5. Fazer o render consumir a linha do tempo, transições, volume e proporção configurada.
6. Aplicar suavização, velocidade e zoom persistidos no projeto.

### Etapa E — Fluxo de um clique e validação de qualidade

1. Botão “Criar cortes automaticamente”.
2. Pipeline sequencial: obter mídia → transcrever → analisar → ranquear → reenquadrar → legendar → gerar prévias.
3. Tela de resultados ordenada por nota, com aceitação em lote.
4. Testes com pelo menos dez vídeos legalmente controlados, incluindo podcast com dois participantes, aula, entrevista, vídeo sem fala e vídeo com pouca luz.
5. Comparar as escolhas contra cortes marcados por uma pessoa e medir precisão, diversidade, fala cortada e legibilidade.

## 6. Opções para decisão

### Opção 1 — Heurística avançada, sem nova IA

- menor download e manutenção;
- totalmente local e rápido;
- permite 5–179 s e usa todos os sinais já existentes;
- não alcança compreensão contextual comparável ao OpusClip.

### Opção 2 — Híbrida local — recomendada

- corrige primeiro confiabilidade, legendas e integração do render;
- adiciona pré-filtro multimodal e uma IA local opcional;
- melhor equilíbrio entre qualidade, privacidade e RTX 3060 8 GB;
- exige download adicional de alguns gigabytes e validação de licença/GPU.

### Opção 3 — API externa opcional

- maior facilidade para testar modelos grandes e tendências atuais;
- custo, internet e envio do texto para terceiros;
- deve ser opcional e requerer consentimento explícito.

## 7. Recomendação final

Recomenda-se aprovar a **Opção 2 — híbrida local**, na ordem A → D → B → C → E: primeiro confiabilidade e correção do render, depois seleção configurável, IA semântica e fluxo de um clique. Cada etapa deverá terminar com testes, sem build durante o desenvolvimento.

Não se recomenda anunciar o CortaFlow atual como equivalente a 2short.ai/OpusClip ou como fluxo automático completo. A base técnica é aproveitável, mas os bloqueios de download/modelo, a sincronização de legenda, a pontuação semântica e a integração do editor com o render precisam ser concluídos primeiro.

## 8. Artefatos da auditoria

Arquivos temporários, modelos e prévias usados no teste estão em:

`C:\Users\limar\AppData\Local\CortaFlow\CortaFlowAI\Audit`

Modelo Faster-Whisper em cache:

`C:\Users\limar\AppData\Local\CortaFlow\CortaFlowAI\Cache\models\faster-whisper`

Nenhum build ou instalador foi criado nesta auditoria.

## 9. Validação após a aprovação das mudanças

Data da conclusão: 13 de agosto de 2026.

Esta seção atualiza os estados históricos registrados nas seções 1 a 5. O plano aprovado foi executado estritamente na ordem **A → D → B → C → E**, com teste ao final de cada fase e sem executar o script de build.

| Fase | Estado final | Evidência principal |
|---|---|---|
| A — confiabilidade | Concluída | Deno oficial/yt-dlp EJS detectados, vídeo autorizado baixado, cache de modelos e diagnóstico CUDA/CPU validados |
| D — legendas/render | Concluída | tempos recortados e deslocados, ASS responsivo em três resoluções, linha do tempo/volume/proporção ligados ao render |
| B — seleção 5–179 s | Concluída | todos os limites naturais enumerados, pré-filtro multimodal, componentes explicáveis, diversidade e aceitação por nota |
| C — IA semântica local | Concluída | Qwen3-4B Q4_K_M verificado por SHA-256, ranking JSON pelo Ollama local, fallback heurístico preservado |
| E — um clique/qualidade | Concluída | pipeline sequencial, prévias temporárias, revisão dos intervalos, exportação final dos aprovados e avaliação de dez vídeos controlados |

### Teste real solicitado

O vídeo `sP3N8HRHFkw` foi obtido com autorização no arquivo local de 143.253.599 bytes e duração aproximada de 668 segundos. O fluxo completo produziu 12 sugestões, aceitou automaticamente 6 conforme o limiar configurado, detectou 1.537 observações faciais e criou três prévias verticais em 83,01 segundos. O ranking semântico local pelo Ollama levou aproximadamente 45 segundos nessa mídia.

As três prévias foram abertas e inspecionadas: proporção 9:16 correta, rosto dentro do quadro e legendas legíveis, com contraste e margem segura. As durações foram 64,63 s, 59,90 s e 60,50 s.

### Avaliação controlada

Dez vídeos sintéticos e legalmente controlados são gerados pelo FFmpeg durante o teste. O conjunto cobre podcast com dois participantes, aula, entrevista, vídeo sem fala, pouca luz, depoimento, tutorial, notícia, debate e demonstração de produto. As escolhas automáticas são comparadas a intervalos marcados previamente como referência humana independente.

| Métrica | Resultado |
|---|---:|
| Precisão macro | 1,000 |
| Diversidade macro | 1,000 |
| Taxa de fala cortada | 0,000 |
| Legibilidade das legendas | 1,000 |

O conjunto é deliberadamente pequeno e controlado; os números validam regressão e funcionamento, não equivalência estatística com plataformas comerciais em conteúdo aberto.

### Suíte final

- 162 testes aprovados após separar prévia/final e adicionar marca-d'água;
- quatro execuções completas consecutivas aprovadas após corrigir a liberação do player multimídia nativo;
- dependências aprovadas por `pip check`;
- pipeline real, ranking local, prévias e inspeção visual aprovados;
- render real de marca-d'água aprovado em prévia e saída final, com posição, escala e transparência;
- a pasta final é escolhida somente depois da revisão e aprovação; as prévias automáticas permanecem no cache;
- nenhum build ou instalador novo foi criado.
