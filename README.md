# CortaFlow AI

Aplicativo desktop local para analisar vídeos autorizados, sugerir trechos e exportá-los em formato vertical com legendas. A interface usa PySide6 e o processamento de mídia usa FFmpeg, Faster-Whisper, PySceneDetect, MediaPipe, OpenCV e PyAV.

## Instalar em um computador Windows novo

O projeto é executado a partir do código-fonte. O `instalar.bat` prepara as dependências e inicia o aplicativo; ele não cria um instalador independente nem baixa uma cópia do código-fonte.

### O que o computador precisa

**Obrigatório para instalar e abrir:**

- Windows 10 ou 11 de 64 bits;
- conexão com a internet durante a instalação;
- WinGet (Aplicativo Instalador de Aplicativos / App Installer, disponível pela Microsoft Store);
- a pasta completa deste projeto, obtida por clone do Git ou download do ZIP do repositório;
- espaço livre em disco para Python, dependências, modelos de transcrição e arquivos de vídeo. Recomenda-se pelo menos 10 GB livres; modelos e vídeos podem exigir mais.

O BAT instala CPython 3.11 x64 e FFmpeg Essentials pelo WinGet, cria `.venv`, instala o projeto e suas dependências e abre o aplicativo. Na primeira instalação, o `pip` baixa várias bibliotecas Python; mantenha a conexão com a internet ativa. Se o Windows pedir autorização para instalar algum componente, confirme com uma conta que possa instalar programas.

### Passo a passo

1. Instale o **Git para Windows**, se ainda não tiver, ou baixe o ZIP do repositório e extraia-o. O Git só é necessário para clonar; para obter o código, use um dos métodos:

   ```powershell
   git clone https://github.com/RomarioSantos-Oficial/404shorts.git
   ```

2. Abra a pasta `404shorts` extraída/clonada. Confirme que nela aparecem `instalar.bat`, `pyproject.toml` e a pasta `scripts`.
3. Dê duplo clique em **`instalar.bat`**. O Windows poderá pedir confirmação para abrir o arquivo; autorize depois de confirmar que veio deste repositório.
4. Aguarde as instalações. Não feche a janela: ela informa se alguma etapa falhar. Ao concluir, o CortaFlow AI inicia.
5. Nas próximas vezes, inicie pelo `iniciar.bat` ou pelo comando abaixo na pasta do projeto:

   ```powershell
   .\.venv\Scripts\python.exe -m cortaflow.main
   ```

Se o WinGet não existir, atualize/instale **App Installer** pela Microsoft Store e execute novamente. Se baixou o ZIP, não mova nem apague a pasta do projeto antes de terminar a instalação.

### Inicialização rápida por script

O `instalar.bat` pode ser executado novamente com segurança: reutiliza o ambiente virtual existente, instala/atualiza dependências necessárias e inicia o programa. Para apenas criar ou reparar o ambiente sem abrir a interface, execute no PowerShell, na pasta do projeto:

```powershell
.\scripts\setup_windows.ps1
```

Para diagnosticar dependências já instaladas:

```powershell
.\scripts\check_environment.ps1
```

## Requisitos opcionais

- **GPU NVIDIA:** não é necessária. A transcrição usa CPU quando CUDA/cuDNN compatíveis não estão disponíveis. Para aceleração, é necessária GPU NVIDIA com drivers e bibliotecas CUDA 12/cuDNN 9 compatíveis com CTranslate2.
- **Ollama e modelo `cortaflow-qwen3:4b`:** opcionais, para classificação semântica local mais avançada. Sem eles, o ranking heurístico continua disponível. O CortaFlow não instala Ollama nem baixa esse modelo automaticamente.
- **Modelo facial MediaPipe `.task`:** necessário para algumas funções de detecção/rastreamento de rostos e validação de enquadramento. Obtenha o modelo Face Landmarker de uma fonte oficial do MediaPipe e selecione-o na página **Analisar**, caso o programa não o encontre localmente. O projeto não baixa o arquivo automaticamente.
- **Conteúdo de vídeo:** use arquivos locais ou links para conteúdo que você tenha direito de usar. A análise de links autorizados depende de conexão com a internet.

Os modelos Faster-Whisper são baixados apenas após confirmação explícita na interface quando ainda não estiverem em cache. Reserve espaço e tempo adicionais para esse primeiro download.

## Como usar

### Fluxo automático (recomendado para começar)

1. Na página **Importar**, clique em **Importar arquivo local** e escolha um vídeo. Também é possível analisar uma URL autorizada e confirmar o download.
2. Clique em **Gerar cortes sugeridos**. O programa prepara a mídia, transcreve a fala e analisa áudio, cenas, rostos e enquadramento. Na primeira execução, autorize o download do modelo de transcrição quando solicitado.
3. A página **Cortes sugeridos** mostra o andamento e os resultados. Selecione um resultado e clique **Assistir corte** para conferir o trecho original e a versão vertical com legenda.
4. Revise a legenda e o enquadramento. Se necessário, ajuste o texto e a marca-d'água em **Editar e salvar**. Resultados marcados para revisão devem ser conferidos antes de aceitar ou exportar.
5. Clique em **Salvar este corte** para exportar o resultado selecionado. Para operações em lote, aceite os resultados desejados e use o comando de salvar cortes. Escolha uma pasta de saída.
6. Salve o projeto como `*.cortaflow.json` para continuar depois. A página **Histórico** permite reabrir projetos recentes; o autosave oferece recuperação se houver uma interrupção.

### Fluxo manual, etapa por etapa

1. **Importar:** adicione o vídeo ou analise uma URL autorizada.
2. **Legendas:** escolha o idioma/modelo, transcreva e corrija o texto. As legendas podem ser exportadas nos formatos disponíveis pela página.
3. **Analisar:** detecte cenas, silêncios, rostos e falante ativo. O falante é uma estimativa; corrija manualmente se necessário.
4. **Cortes sugeridos:** assista, aceite/rejeite e escolha os intervalos que deseja editar ou exportar.
5. **Editor completo:** ajuste a linha do tempo, o enquadramento/keyframes e outros elementos quando necessário.
6. **Cortes sugeridos:** revise a prévia atualizada e salve um corte ou os aceitos em lote.
7. Salve o projeto `.cortaflow.json` para reabrir o trabalho depois.

## Arquivos e dados

Os projetos e exportações ficam nos locais escolhidos pelo usuário. O aplicativo também mantém dados locais do usuário:

- banco `cortaflow.db`: histórico, preferências e estado da fila;
- cache: modelos e prévias temporárias;
- logs: informações locais para diagnóstico.

Os caminhos são mostrados em **Configurações**. O pipeline de análise processa mídia localmente; não envia vídeo, áudio ou caixas faciais a serviços externos. Não há reconhecimento de identidade facial.

## Solução de problemas

- **`winget` não encontrado:** instale/atualize o App Installer na Microsoft Store, feche e reabra o terminal e execute `instalar.bat` novamente.
- **Python 3.11 não encontrado:** confira se o launcher Python (`py`) está instalado. Em um terminal novo, `py -3.11 --version` deve mostrar Python 3.11.
- **`ffmpeg` não encontrado:** execute `winget install --id Gyan.FFmpeg.Essentials -e`; depois feche e reabra o terminal. O pacote instala FFmpeg e FFprobe.
- **Instalação Python falhou:** confira a conexão, espaço livre e a mensagem do `pip`. Para reparar, execute novamente `instalar.bat`.
- **Transcrição lenta:** a CPU funciona sem configuração extra, mas pode ser mais lenta. CUDA/cuDNN são opcionais e dependem de hardware e versões compatíveis.
- **Modelo facial ausente:** selecione o arquivo `.task` oficial do MediaPipe Face Landmarker em **Analisar**. A ausência pode impedir recursos que dependem de detecção facial.
- **Ollama/modelo semântico indisponível:** o ranking heurístico continua funcionando; o Ollama e o modelo `cortaflow-qwen3:4b` são opcionais.
- **Arquivo final já existe:** escolha outro destino; o renderizador não sobrescreve a saída silenciosamente.
- **Falha ao exportar:** confira o espaço livre, os logs locais e se o formato de vídeo é compatível.

## Segurança, licenças e limitações

Use apenas conteúdo próprio, licenciado ou autorizado. O aplicativo não contorna DRM, paywalls, vídeos privados ou controles de acesso, e não importa cookies do navegador. FFmpeg, modelos e outros componentes de terceiros são instalados separadamente e seguem as licenças próprias; consulte [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) e as [condições legais do FFmpeg](https://ffmpeg.org/legal.html).

O falante ativo é uma estimativa baseada em movimento de boca, energia e detecção de voz; a correção manual tem prioridade. A qualidade de saída também depende da qualidade e resolução do vídeo de origem.
