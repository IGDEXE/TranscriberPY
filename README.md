# 🎧 Video Transcriber (Whisper)

Transcritor de vídeos local usando OpenAI Whisper, com suporte a:

* divisão automática por silêncio
* processamento paralelo
* deduplicação de sobreposição entre chunks

---

## 🚀 Instalação

### 1. Clonar o projeto

```bash
git clone <seu-repo>
cd <seu-repo>
```

### 2. Instalar dependências Python

```bash
pip install -r requirements.txt
```

### 3. Instalar ffmpeg (obrigatório)

* **Windows:** https://ffmpeg.org/download.html
* **Mac:**

```bash
brew install ffmpeg
```

* **Linux:**

```bash
sudo apt install ffmpeg
```

---

## ▶️ Uso

### Transcrição básica

```bash
python transcriber.py video.mp4
```

### Definir arquivo de saída

```bash
python transcriber.py video.mp4 --output resultado.txt
```

### Escolher modelo

```bash
python transcriber.py video.mp4 --model medium
```

Modelos disponíveis:

* `tiny` (rápido, menor qualidade)
* `base`
* `small`
* `medium`
* `large` (melhor qualidade, mais lento)

---

## ⚙️ Opções úteis

### Ajustar tamanho dos chunks

```bash
--chunk-minutes 10
```

### Desativar paralelismo

```bash
--no-parallel
```

---

## 🧠 Como funciona

1. Detecta duração do vídeo via `ffprobe`
2. Identifica silêncios com `ffmpeg`
3. Divide o vídeo em chunks inteligentes
4. Extrai áudio (WAV 16kHz mono)
5. Transcreve cada chunk com Whisper
6. Junta os textos removendo sobreposição

---

## 📦 Saída

* Arquivo `.txt` com a transcrição completa
* Nome padrão: `<video>_transcript.txt`

---

## 🛡️ Segurança (Veracode)

Este projeto possui integração com **Veracode** para análise automatizada de segurança no pipeline CI.

### O que é validado

* **SCA (Software Composition Analysis)**
  Identifica vulnerabilidades em dependências Python

* **Static Analysis (SAST)**
  Analisa o código-fonte do projeto

* **Pipeline Scan**
  Execução rápida de validações durante o CI

---

### 🔐 Configuração necessária

Configure os seguintes *secrets* no repositório:

```text
VERACODE_ID
VERACODE_KEY
SCA
```

---

### 📊 Fluxo do pipeline

1. Criação do pacote de análise
2. Scan de dependências (SCA)
3. Upload e análise completa no Veracode
4. Pipeline Scan (validação rápida)
5. Execução do teste real de transcrição

> O job de execução do projeto só roda após as etapas de segurança.

---

## 🧪 CI (GitHub Actions)

O pipeline automatizado:

* instala dependências
* gera vídeo com fala sintética
* executa transcrição real com Whisper
* valida saída gerada
* roda análise de segurança com Veracode

---

## ⚠️ Observações

* Whisper baixa modelos automaticamente (primeira execução pode ser mais lenta)
* Uso intensivo de CPU/RAM dependendo do modelo escolhido
* Paralelismo aumenta performance, mas também o consumo de memória

---

## 📄 Licença (MIT)

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to do so, subject to the
following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.