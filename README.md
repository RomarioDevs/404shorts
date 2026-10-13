[# CortaFlow AI

Aplicativo desktop local para transformar vídeos autorizados em cortes verticais. A interface é feita com Qt Widgets/PySide6; FFmpeg executa os cortes e a renderização; Faster-Whisper, PySceneDetect, MediaPipe, OpenCV e PyAV fazem as análises locais.

## Estado do projeto

As Fases 0 a 9 do plano foram implementadas e testadas. A Fase 10 cobre testes e documentação. O build do executável e o instalador estão deliberadamente suspensos por orientação do usuário: nenhum empacotamento foi executado ou validado nesta etapa.

O plano corretivo aprovado na auditoria de cortes automáticos também foi concluído na ordem A → D → B → C → E. Ele acrescentou o fluxo automático de um clique, seleção configurável entre 5 e 179 segundos, ranking semântico local opcional, correções de legenda/render e avaliação reproduzível de qualidade. Nenhum build foi gerado durante esse trabalho.

Recursos disponíveis:

- importação local e consulta/download de URL autorizada com confirmação;
- player, marcação de entrada/saída e linha do tempo com sete faixas;
- transcrição com timestamps por palavra e fallback automático de CUDA para CPU;
- edição e exportação de legendas JSON, SRT e ASS;
- detecção de cenas, silêncios, rostos e sugestões de cortes;
- botão **Gerar cortes sugeridos**, que executa obtenção → transcrição → cenas/voz → rostos/falante → validação do enquadramento → ranking → legenda → versão vertical de cada resultado;
- ranking híbrido: pré-filtro multimodal determinístico, Qwen3-4B local pelo Ollama e fallback heurístico sem perda dos resultados;
- durações mínima, preferida e máxima configuráveis entre 5 e 179 segundos, quantidade de resultados e aceitação automática por nota;
- marca-d'água opcional com PNG, WebP, JPG ou BMP válido, posicionável por arrastar e redimensionar diretamente sobre a prévia vertical, além de dez posições, tamanho, transparência e margem;
- enquadramento vertical automático, falante ativo e correção por keyframes manuais;
- editor com propriedades, atalhos, desfazer/refazer e estilos persistidos no projeto;
- prévia obrigatória, fila sequencial, cancelamento, NVENC e fallback para `libx264`;
- projetos JSON portáteis, autosave, recuperação e histórico/fila/configurações em SQLite.

## Requisitos

- Windows 10 ou 11 de 64 bits;
- CPython 3.11 de 64 bits;
- FFmpeg e FFprobe 8.1 ou compatíveis, acessíveis pelo `PATH` ou instalados pelo pacote oficial do WinGet usado no ambiente validado;
- build do FFmpeg com `libass`, H.264 (`libx264`) e AAC;
- NVIDIA CUDA 12 e cuDNN 9 para transcrição por GPU com as versões atuais do CTranslate2; sem isso, o aplicativo usa CPU;
- arquivo oficial `.task` do MediaPipe já existente no computador; o aplicativo o localiza automaticamente e ainda permite seleção manual;
- opcionalmente, Ollama já instalado e em execução com o modelo local `cortaflow-qwen3:4b`; se não estiver disponível, o ranking heurístico continua funcionando.

O Qt for Python recomenda um ambiente virtual e Python oficial. O Faster-Whisper atual requer Python 3.9 ou superior e, para GPU, cuBLAS/CUDA 12 e cuDNN 9. Consulte as fontes oficiais: [Qt for Python](https://doc.qt.io/qtforpython-6/gettingstarted.html), [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper), [FFmpeg](https://ffmpeg.org/documentation.html) e [MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker).

## Preparação e execução

No PowerShell, a partir da raiz do projeto:

```powershell
.\scripts\setup_windows.ps1
.\.venv\Scripts\python.exe -m cortaflow.main
```

O script usa somente o Python 3.11 local, cria `.venv` quando necessário e instala o projeto em modo editável. Para conferir o ambiente sem alterar arquivos:

```powershell
.\scripts\check_environment.ps1
```

O aplicativo não baixa modelos silenciosamente. Se um modelo Faster-Whisper ou semântico não estiver no cache, a interface pede autorização explícita antes de qualquer obtenção oficial. Os modelos ficam no cache do usuário e não são incorporados ao código-fonte. O Ollama existente é consultado somente em `127.0.0.1`; o CortaFlow não executa `ollama pull`.

## Fluxo de uso

Para o fluxo rápido, importe a mídia e clique em **Gerar cortes sugeridos**. A tela **Cortes sugeridos** abre imediatamente e mostra a etapa em andamento. Antes de renderizar, cada intervalo recebe verificação do rosto principal/falante em amostras de 250 ms, inclusive nas trocas de pessoa e câmera. Depois, o próprio MP4 vertical pronto é analisado novamente: a versão só recebe `Legenda + rosto conferido` quando o rosto completo e centralizado foi confirmado no arquivo renderizado. A coluna **Enquadramento** informa `Validado`, `Sem rosto · centro` ou `Revisar`; um resultado inseguro não pode ser aceito em lote. Selecione uma linha e use **Assistir corte**: primeiro é mostrado temporariamente o intervalo original e depois a versão vertical com legenda. Todas as sugestões solicitadas recebem versão vertical no cache. Use **Anterior** e **Próximo** para revisar uma por vez.

Na própria página **Cortes sugeridos**, a área **Editar e salvar** mantém exatamente o início/fim do resultado selecionado. Nela é possível corrigir a legenda, abrir o mesmo intervalo no Editor completo e arrastar/redimensionar uma marca-d'água válida. A marca é posicionada dentro da área real do vídeo, sem usar as barras pretas do player; ao concluir a prévia, o estado confirma que ela foi gravada no MP4. **Atualizar prévia após ajustes** é opcional para conferir o resultado; **Salvar este corte** e o botão superior **Salvar cortes** gravam diretamente o corte aberto com as configurações atuais, sem exigir aceitação da lista. A aceitação continua necessária somente para operações em lote. **Editar e salvar aceitos em lote** permanece no mesmo espaço. Não existe mais uma aba lateral Exportar duplicando esse fluxo.

No editor incorporado em **Cortes sugeridos**, `1080 × 1920 · máxima` gera o maior formato vertical oferecido pelo aplicativo. A qualidade real continua limitada pelo vídeo original; ampliar uma fonte pequena não cria detalhes novos. No campo **Qualidade**, números menores preservam mais qualidade, mas aumentam o arquivo. Qualquer correção de legenda ou mudança na imagem, posição, tamanho ou transparência da marca-d'água invalida a aprovação anterior e exige uma nova prévia.

Para controle etapa a etapa:

1. Em **Importar**, selecione um arquivo local ou analise uma URL autorizada.
2. Em **Legendas**, escolha idioma/modelo, transcreva e revise o texto.
3. Em **Analisar**, detecte cenas, silêncios, rostos e falante ativo.
4. Em **Cortes sugeridos**, assista, aceite/rejeite ou abra **Editar e salvar**.
5. Em **Editor completo**, ajuste a linha do tempo ou keyframes manuais quando necessário.
6. Volte a **Cortes sugeridos**, atualize a prévia, aprove e escolha a pasta.
7. Salve o projeto como `*.cortaflow.json`. A aba **Histórico** permite reabri-lo.

O autosave é escrito ao lado do projeto com o sufixo `.autosave`. Ao abrir um projeto cuja cópia automática seja mais recente, o programa oferece a recuperação.

## Dados locais

Os diretórios reais são exibidos em **Configurações** e seguem `platformdirs`:

- dados: banco `cortaflow.db` com histórico, configurações e estados da fila;
- cache: modelos e prévias temporárias;
- logs: diagnósticos locais sem cookies ou tokens.

Mídias, áudio e caixas faciais não são enviados a serviços externos pelo pipeline de análise. O sistema usa identificadores temporários de rosto e não faz reconhecimento de identidade.

## Testes

Execute a suíte completa:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

As fixtures são locais e legalmente controladas; os testes não dependem de vídeos aleatórios da internet. A avaliação gera dez vídeos sintéticos redistribuíveis, incluindo podcast com dois participantes, aula, entrevista, vídeo sem fala e pouca luz, e mede precisão contra cortes humanos, diversidade, fala cortada e legibilidade. Há também cobertura para caminhos com espaços e acentos, falta de CUDA/FFmpeg, persistência, cancelamento e renderização real com FFmpeg.

## Solução de problemas

- **FFmpeg não encontrado:** execute `ffmpeg -version` e `ffprobe -version`. Reabra o terminal após instalar pelo WinGet.
- **CUDA/cuDNN indisponível:** a transcrição tenta CPU automaticamente. A GPU exige versões compatíveis das bibliotecas NVIDIA no `PATH`.
- **Modelo facial ausente:** selecione manualmente um arquivo `.task` oficial do MediaPipe; quando ele já está no cache/auditoria local, o aplicativo o preenche automaticamente. O projeto não baixa executáveis ou modelos de fontes desconhecidas.
- **Exportação mostra `out_time=N/A`:** alguns codecs, especialmente no início do AV1/Opus, não informam tempo imediatamente. O aplicativo trata esse valor como 0% até chegar o primeiro timestamp válido.
- **Ollama/modelo semântico indisponível:** mantenha o Ollama local em execução e registre o GGUF verificado como `cortaflow-qwen3:4b`; sem ele, escolha o modo heurístico. Nenhum modelo é puxado automaticamente.
- **Arquivo final já existe:** escolha outro destino. O renderizador não sobrescreve a saída silenciosamente.
- **Falha durante exportação:** a saída é criada em arquivo temporário e só é renomeada após sucesso. A tarefa interrompida fica registrada como falha para não parecer concluída.
- **Interface sem vídeo:** confirme que o formato possui decodificador compatível no Qt/FFmpeg e use o diagnóstico do ambiente.

## Segurança, licenças e limitações

Use apenas conteúdo próprio, licenciado ou autorizado. O aplicativo não contorna DRM, paywalls, vídeos privados ou controles de acesso e não importa cookies do navegador. Processos externos recebem argumentos separados e usam `shell=False`.

O falante ativo é uma estimativa probabilística baseada em movimento de boca, energia e VAD; a correção manual tem prioridade. FFmpeg, fontes e modelos não são distribuídos neste repositório. Antes de qualquer distribuição futura, revise [as condições legais do FFmpeg](https://ffmpeg.org/legal.html), as obrigações do Qt/PySide6 e o arquivo [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

O script `scripts/build_windows.ps1` permanece somente como preparação para uma etapa futura autorizada. Ele não foi executado nesta validação.
#   4 0 4 s h o r t s 
 
 ](https://github.com/RomarioSantos-Oficial/404shorts)
