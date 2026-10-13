# Relatório de decisão — fluxo eficiente para vídeos longos

Data: 13 de agosto de 2026  
Projeto: CortaFlow AI 0.1.0  
Status: proposta para aprovação; nenhum código, programa ou modelo foi alterado ou baixado nesta análise.

## 1. Decisão recomendada

Para vídeos longos, o CortaFlow deve compreender todo o conteúdo falado, mas não deve executar detecção facial pesada em todo o vídeo antes de saber quais trechos interessam.

O melhor fluxo é uma análise em cascata:

```text
link ou arquivo local
→ metadados e áudio/legendas
→ transcrição e índice de todo o conteúdo falado
→ candidatos de 5 a 179 segundos
→ ranking e remoção de repetições
→ análise detalhada de cenas, rostos e falante somente nos candidatos
→ legenda precisa e reenquadramento somente nos finalistas
→ prévias verticais
→ revisão/edição
→ salvamento na pasta escolhida
```

Assim, o programa continua examinando o assunto inteiro, mas usa o processamento caro apenas onde ele pode gerar um corte.

Uma exceção é conteúdo principalmente visual — esporte, gameplay, dança, clipes musicais ou montagens com pouca fala. Nesses casos, texto sozinho não basta. O programa deve fazer uma varredura visual leve e de baixa resolução no vídeo inteiro, sem executar o detector facial completo em todos os quadros.

## 2. O que o programa faz atualmente

A auditoria do código encontrou esta ordem no fluxo automático atual:

1. valida a mídia;
2. transcreve o áudio completo, quando o projeto ainda não possui transcrição;
3. detecta cenas no vídeo completo;
4. detecta silêncios no áudio completo;
5. percorre novamente o áudio completo para medir energia/voz;
6. percorre o vídeo completo para detectar rostos a cada 250 ms;
7. se houver vários rostos, procura o falante ativo no vídeo completo;
8. somente depois escolhe os cortes;
9. gera e valida as prévias dos melhores resultados.

O maior desperdício está no item 6. Embora a inferência facial seja feita aproximadamente a cada 250 ms, a implementação atual chama a decodificação de todos os quadros até chegar à próxima amostra. Em um vídeo 1080p/59,94 FPS, isso continua exigindo a leitura de centenas de milhares de quadros.

O teste real já registrado no projeto mediu 28,83 segundos de análise facial para um trecho de 30 segundos com múltiplas regiões. Uma execução no vídeo completo de 11min07s ultrapassou cinco minutos. Em vídeos de horas, o fluxo atual pode crescer para dezenas de minutos somente nessa etapa.

## 3. Será necessário baixar outro programa?

Não. A máquina já possui os componentes obrigatórios para o fluxo proposto:

| Componente | Estado encontrado | Uso no novo fluxo |
|---|---|---|
| FFmpeg 8.1.1 | instalado e localizado pelo CortaFlow | áudio de análise, busca por intervalo, proxy e render final |
| yt-dlp 2026.7.4 | instalado no ambiente do projeto | mídia, metadados, legendas e intervalos de links autorizados |
| Deno 2.9.5 + yt-dlp-ejs 0.8.0 | instalados no ambiente do projeto | desafios JavaScript do YouTube |
| Faster-Whisper `small` | completo no cache, aproximadamente 0,453 GiB | transcrição local |
| MediaPipe Face Landmarker | modelo local encontrado | rostos e reenquadramento dos candidatos |
| PySceneDetect/OpenCV/PyAV | instalados | cenas, vídeo e áudio |
| Ollama + `cortaflow-qwen3:4b` | executável e modelo local encontrados | ranking semântico opcional |

O diagnóstico atual usa CPU `int8`, pois cuBLAS 12 e cuBLASLt 12 não estão disponíveis para o CTranslate2. Instalar o runtime NVIDIA compatível poderia acelerar a transcrição, mas não é obrigatório e não deve ser feito agora. Primeiro deve-se corrigir o fluxo para evitar trabalho desnecessário. Qualquer instalação de CUDA continuaria dependendo de autorização separada e de download somente da fonte oficial.

Também não há motivo para baixar outro Llama: o Ollama e o modelo semântico necessário já estão disponíveis. O CortaFlow deve escolher um backend semântico local, não manter dois processos fazendo a mesma função.

## 4. O que mostram as ferramentas pesquisadas

O [2short.ai](https://www.2short.ai/) declara que usa as palavras faladas para compreender e extrair trechos, funciona melhor com vídeos falados e depois aplica rastreamento facial do falante, legendas e edição. Isso sustenta a estratégia de texto primeiro para podcasts, aulas e entrevistas.

O [OpusClip](https://help.opus.pro/docs/article/introduction-to-opusclip) declara seleção multimodal com sinais visuais, de áudio e sentimento. Seu [rastreamento de assunto](https://help.opus.pro/docs/article/subject-tracking) identifica o falante usando voz e movimento, mantém o assunto centralizado e oferece correção manual quando a escolha automática não é suficiente.

O [CapCut Long Video to Shorts](https://www.capcut.com/tools/long-video-to-shorts) descreve identificação de destaques, recorte inteligente, rastreamento do assunto, legendas automáticas, prévia e edição antes da exportação. Portanto, o resultado esperado é uma lista de cortes já reenquadrados e legendados para revisão — não uma análise pesada de todos os quadros antes de formar a lista.

As bibliotecas já usadas pelo CortaFlow oferecem as otimizações necessárias:

- o [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper/blob/master/README.md?plain=1) possui VAD para remover períodos sem fala, timestamps por palavra e transcrição em lote; sua API também aceita intervalos específicos (`clip_timestamps`) para uma segunda passagem precisa somente nos cortes;
- o [FFmpeg](https://ffmpeg.org/ffmpeg.html) permite buscar um intervalo com `-ss` e fazer busca precisa durante transcodificação;
- o [PySceneDetect](https://www.scenedetect.com/docs/head/cli.html) oferece redução de resolução e salto de quadros, assumindo uma perda controlada de precisão;
- o [yt-dlp](https://github.com/yt-dlp/yt-dlp/blob/master/README.md) permite obter legendas e baixar intervalos temporais, usando FFmpeg.

Esses produtos não publicam o algoritmo proprietário completo. A proposta copia o padrão de trabalho verificável — indexar, selecionar, reenquadrar, legendar, revisar — e não afirma reproduzir a fórmula interna deles.

## 5. Fluxo proposto em detalhes

### Etapa A — aquisição inteligente

Para arquivo local:

- não copiar nem recodificar o original;
- criar apenas um áudio de análise mono/16 kHz no cache;
- guardar hash, duração, resolução, FPS e codec para reutilização.

Para link autorizado:

- consultar metadados e legendas antes do vídeo completo;
- se existir legenda confiável no idioma correto, usá-la como índice inicial;
- se não existir, baixar primeiro apenas o áudio e transcrevê-lo;
- depois da seleção, baixar os intervalos candidatos em alta qualidade, com alguns segundos de margem;
- manter como opção “Guardar o vídeo original completo” para quem quiser arquivar ou procurar novos cortes sem outro download.

Essa abordagem reduz rede e disco em vídeos de várias horas. Se um site não permitir intervalo preciso, o programa deve explicar a limitação e oferecer o download completo; não deve contornar proteção, usar cookies ou ampliar permissões sem pedido do usuário.

### Etapa B — leitura de todo o conteúdo falado

- dividir a transcrição longa em blocos reiniciáveis, por exemplo 10 a 20 minutos, com pequena sobreposição;
- usar VAD para não transcrever silêncio;
- salvar cada bloco assim que ficar pronto, permitindo cancelar e continuar depois;
- na primeira passagem, timestamps por segmento são suficientes para localizar assuntos;
- depois, gerar timestamps por palavra apenas nos finalistas para produzir legendas exatas;
- quando uma legenda da fonte for usada, validar idioma, cobertura temporal e quantidade de texto antes de aceitá-la.

O áudio/texto do conteúdo inteiro continua sendo analisado. O que deixa de ser analisado integralmente em alta resolução são rostos e reenquadramentos.

### Etapa C — seleção textual e de áudio

- formar janelas completas entre 5 e 179 segundos em limites de frase, pausa e assunto;
- calcular hook, clareza sem contexto externo, conclusão, informação/valor, emoção, densidade de fala, energia e silêncio;
- gerar uma reserva de aproximadamente três vezes a quantidade solicitada;
- enviar somente essa reserva ao Ollama, em lotes, para nota semântica, título e motivo;
- eliminar sobreposição e repetição de assunto;
- preservar candidatos reservas caso algum trecho seja reprovado pela análise visual.

Não existe garantia matemática de viralização. A nota deve ser descrita como potencial editorial e mostrar seus componentes.

### Etapa D — varredura visual proporcional ao conteúdo

O programa deve escolher um perfil:

| Perfil | Quando usar | Análise integral |
|---|---|---|
| Falado rápido | podcast, entrevista, aula, comentário | texto, VAD, energia e silêncio |
| Misto | vlog, apresentação, conversa com imagens | itens acima + proxy visual leve |
| Visual | esporte, gameplay, show, dança, pouca fala | proxy visual integral, áudio e cenas |

No perfil falado, rosto, falante e reenquadramento são analisados somente na união dos intervalos candidatos, com 2 a 3 segundos de margem.

Nos perfis misto/visual, um proxy de baixa resolução e poucos quadros por segundo percorre o vídeo inteiro para detectar mudanças, movimento e momentos visuais. O MediaPipe completo ainda fica restrito aos candidatos.

### Etapa E — acabamento somente nos finalistas

1. ajustar início/fim em frase, pausa e mudança de cena;
2. retranscrever o intervalo com timestamps por palavra, se necessário;
3. detectar quantidade de rostos;
4. correlacionar boca, voz e movimento quando houver mais de uma pessoa;
5. gerar keyframes 9:16 com reinício em cada troca de câmera;
6. gerar legenda automática;
7. renderizar a prévia vertical;
8. reabrir a prévia renderizada e validar rosto, margem segura e legenda;
9. mostrar os cortes em sequência para aceitar, rejeitar ou editar;
10. salvar somente o corte aprovado na pasta escolhida pelo usuário.

As prévias podem ser geradas progressivamente: primeiras três imediatamente, demais em segundo plano ou quando o usuário solicitar. Isso reduz espera e uso de disco.

### Etapa F — cache, cancelamento e retomada

Cada resultado deve ser identificado pelo hash da mídia, intervalo, versão do modelo e configurações. Devem ser reaproveitados:

- metadados;
- áudio de análise;
- legenda/transcrição por bloco;
- evidência de VAD/energia;
- candidatos e notas;
- rastreamento facial dos intervalos já processados;
- prévias ainda válidas.

Uma alteração de texto de legenda não deve invalidar a transcrição ou o rastreamento facial; deve invalidar somente a prévia/render que contém aquela legenda.

## 6. Redução estimada de trabalho

Exemplo ilustrativo: vídeo de duas horas, pedido de dez cortes de 60 segundos e reserva de 30 candidatos.

| Trabalho visual detalhado | Fluxo atual | Cascata proposta |
|---|---:|---:|
| Detecção facial antes da seleção | 120 minutos de conteúdo | no máximo 30 minutos de candidatos |
| Detecção facial dos dez finalistas | incluída nos 120 minutos | 10 minutos |
| Amostras a cada 250 ms | 28.800 | 7.200 na reserva ou 2.400 nos finalistas |

Isso representa até 75% menos inferências faciais na reserva e 91,7% menos nos finalistas. A redução real depende da quantidade/duração dos candidatos, do codec, da resolução e de intervalos que se sobrepõem; não é promessa de tempo de execução.

O proxy visual leve também pode processar uma fração dos quadros usados pelo vídeo original. Essa passagem não substitui a verificação detalhada dos finalistas.

## 7. Mudanças possíveis no CortaFlow

### Fase 1 — medição e cache, sem alterar resultados

- registrar tempo e quantidade de segundos/quadros de cada etapa;
- criar manifesto de cache e retomada;
- impedir nova análise quando o resultado ainda é válido.

Teste de saída: repetir o mesmo projeto deve reutilizar transcrição e evidências; mudança de configuração deve invalidar somente o estágio afetado.

### Fase 2 — texto primeiro

- mover geração/ranking preliminar de candidatos para antes de rostos;
- unificar silêncio, VAD e energia para evitar múltiplas leituras do áudio;
- adicionar transcrição longa em blocos e retomada;
- usar legenda da fonte somente após validação.

Teste de saída: 100% da fala indexada dentro da tolerância definida, cancelamento e retomada sem perder blocos, candidatos sempre entre 5 e 179 segundos.

### Fase 3 — visão por intervalos

- fazer `analyze_faces` receber uma lista de intervalos;
- buscar diretamente o início de cada intervalo, sem decodificar o vídeo desde zero;
- juntar intervalos sobrepostos;
- analisar falante somente quando houver vários rostos;
- manter candidatos reservas para substituir reprovações.

Teste de saída: os mesmos casos de um, dois e três rostos; troca de câmera; rosto pequeno; 100% das amostras válidas dentro da área segura na prévia final.

### Fase 4 — modos de vídeo longo

- adicionar “Falado rápido”, “Misto” e “Visual” com seleção automática explicável;
- criar proxy visual leve apenas nos modos que precisam dele;
- oferecer “Guardar original completo” ou “Baixar somente partes em alta qualidade”.

Teste de saída: podcast, aula, gameplay e vídeo sem fala. O modo sem fala não pode retornar lista vazia apenas porque não há transcrição.

### Fase 5 — acabamento progressivo

- timestamps por palavra apenas nos finalistas quando a primeira passagem for aproximada;
- gerar primeiras prévias antes das demais;
- manter editor, marca-d'água, reenquadramento e salvamento individual já existentes.

Teste de saída: legenda sincronizada, marca-d'água dentro do 9:16, rosto validado após render e arquivo final criado somente na pasta escolhida.

### Fase 6 — benchmark e regressão final

- medir vídeos controlados de 10, 30, 60 e 120 minutos;
- comparar escolhas e notas antes/depois;
- medir duração transcrita, duração facial, quadros decodificados, RAM, disco e tempo;
- executar todos os testes automatizados após cada fase;
- não gerar build durante essas fases.

## 8. Critérios de aprovação do novo fluxo

O fluxo deve ser considerado aprovado quando:

1. todo o conteúdo falado tiver sido indexado, mesmo que a visão detalhada não percorra o vídeo inteiro;
2. os cortes tiverem de 5 a 179 segundos, sem repetição relevante;
3. nenhum candidato for aceito sem legenda e enquadramento conferidos no MP4 renderizado;
4. conteúdo com pouca fala mudar para análise visual leve, em vez de falhar silenciosamente;
5. análise facial detalhada ficar restrita à união dos candidatos;
6. cancelamento e retomada funcionarem por estágio;
7. nenhuma dependência/modelo for baixado sem autorização;
8. o usuário continuar escolhendo a pasta de salvamento;
9. a qualidade final usar a melhor fonte disponível para os intervalos aprovados;
10. não houver build até autorização explícita.

## 9. Recomendação para aprovação

Recomendo aprovar a arquitetura em cascata e executá-la fase por fase, com teste ao término de cada fase. Para o computador atual, a prioridade deve ser reduzir decodificação e inferência antes de considerar qualquer instalação de CUDA.

Decisões propostas:

- aprovar texto/áudio integral e rostos somente nos candidatos;
- aprovar os três perfis de conteúdo;
- aprovar o uso opcional de legendas da fonte e download somente dos intervalos em alta qualidade;
- não aprovar nenhuma instalação adicional agora;
- manter a opção de baixar/guardar o original completo;
- manter a regra de não criar build.
