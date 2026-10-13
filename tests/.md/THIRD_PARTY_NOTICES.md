# Avisos de terceiros

Versões principais instaladas e testadas no ambiente Windows x86-64 com CPython 3.11.9:

| Componente | Versão testada | Licença indicada pelo projeto | Origem oficial |
|---|---:|---|---|
| Python | 3.11.9 | PSF-2.0 | [python.org](https://www.python.org/) |
| PySide6 / Qt for Python | 6.11.1 | LGPL-3.0-only, GPL-3.0-only ou comercial | [Qt Project](https://doc.qt.io/qtforpython-6/) |
| platformdirs | 4.11.2 | MIT | [PyPI](https://pypi.org/project/platformdirs/) |
| Pydantic | 2.13.4 | MIT | [PyPI](https://pypi.org/project/pydantic/) |
| yt-dlp | 2026.7.4 | Unlicense | [GitHub](https://github.com/yt-dlp/yt-dlp) |
| yt-dlp-ejs | 0.8.0 | Unlicense, MIT e ISC | [PyPI](https://pypi.org/project/yt-dlp-ejs/) |
| Deno | 2.9.5 | MIT | [Deno](https://deno.com/) |
| FFmpeg Essentials Build | 8.1.1 | GPL-3.0 para a configuração testada com `libx264` | [FFmpeg](https://ffmpeg.org/legal.html) / WinGet `Gyan.FFmpeg.Essentials` |
| faster-whisper | 1.2.1 | MIT | [GitHub](https://github.com/SYSTRAN/faster-whisper) |
| CTranslate2 | 4.8.1 | MIT | [GitHub](https://github.com/OpenNMT/CTranslate2) |
| PyAV | 18.1.0 | BSD-3-Clause | [PyAV](https://pyav.org/docs/stable/) |
| NumPy | 2.4.6 | BSD-3-Clause | [numpy.org](https://numpy.org/) |
| pysubs2 | 1.8.1 | MIT | [GitHub](https://github.com/tkarabela/pysubs2) |
| opencv-python | 5.0.0.93 | Apache-2.0 (metadados do pacote) | [PyPI](https://pypi.org/project/opencv-python/) |
| opencv-contrib-python | 5.0.0.93 | Apache-2.0 (metadados do pacote) | [PyPI](https://pypi.org/project/opencv-contrib-python/) |
| PySceneDetect | 0.7.1 | BSD-3-Clause | [Documentação](https://www.scenedetect.com/docs/latest/) |
| MediaPipe | 1.0.0 | Apache-2.0 | [Google AI Edge](https://ai.google.dev/edge/mediapipe/solutions/guide) |
| llama.cpp (Vulkan) | b10410 | MIT | [GitHub](https://github.com/ggml-org/llama.cpp/releases/tag/b10410) |
| Qwen3-4B-GGUF Q4_K_M | revisão bc640142 | Apache-2.0 | [Hugging Face/Qwen](https://huggingface.co/Qwen/Qwen3-4B-GGUF) |
| Ollama CLI/servidor local | 0.32.9 | MIT no repositório oficial | [GitHub/Ollama](https://github.com/ollama/ollama) |
| pytest | 9.1.1 | MIT | [pytest](https://docs.pytest.org/) |
| pytest-qt | 4.5.0 | MIT | [pytest-qt](https://pytest-qt.readthedocs.io/) |
| PyInstaller | 6.22.0 | GPL-2.0-or-later com exceção para distribuição | [PyInstaller](https://pyinstaller.org/) |

PySide6 contém Qt e componentes de terceiros com avisos próprios. Uma distribuição deve preservar as obrigações aplicáveis; consulte [as licenças oficiais do Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html).

FFmpeg é LGPL-2.1-or-later por padrão, mas partes opcionais como `libx264` tornam GPL a configuração utilizada. FFmpeg, seus executáveis, fontes e modelos de IA não são incorporados ao projeto nesta etapa.

O CortaFlow apenas reutiliza a instalação local do Ollama feita pelo usuário e sua API em `127.0.0.1`; não incorpora nem redistribui o aplicativo Ollama e não baixa modelos por essa API. A linha acima se refere ao CLI/servidor do repositório oficial, cuja licença é MIT.

Pacotes transitivos permanecem sujeitos às respectivas licenças e metadados instalados. Um inventário/SBOM completo e a validação em máquina sem Python são requisitos obrigatórios antes de qualquer empacotamento futuro. Nenhum build foi executado nesta validação.
