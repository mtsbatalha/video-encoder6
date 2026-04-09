# Video Encoder - FFmpeg + CUDA

Gerenciador de conversão de vídeo com aceleração GPU via FFmpeg (NVENC/CUDA). Suporta conversão de arquivo único e em lote, com detecção automática de legendas externas.

## Perfis de Conversão

| Perfil | Descrição | Bitrate |
|--------|-----------|---------|
| 4K HDR → 4K SDR | Tonemap HDR→SDR (Hable), BT.709 | 20M VBR |
| 4K HDR → 4K HDR | Mantém HDR/DV, main10 10-bit | 20M VBR |
| 4K HDR → 1080p HDR | Downscale + mantém HDR | 6M VBR |
| 4K HDR → 1080p SDR | Downscale + tonemap SDR | 4.5M VBR |

## Requisitos

- Python 3.10+
- FFmpeg com suporte a `hevc_nvenc` (NVIDIA GPU com drivers CUDA)
- NVIDIA GPU compatível com NVENC

## Instalação

```bash
pip install -r requirements.txt
```

## Uso

```bash
python main.py
```

### Menu Principal

1. **Converter arquivo único** — Selecione um arquivo e um perfil de conversão
2. **Conversão em lote** — Selecione uma pasta; todos os vídeos serão convertidos
3. **Configurações** — Pasta de saída, número de conversões paralelas
4. **Sair**

### Estrutura de Saída

Cada conversão cria uma subpasta na pasta de saída:

```
conversions/
├── NomeDoFilme_4K_SDR/
│   ├── NomeDoFilme_4K_SDR.mkv
│   └── NomeDoFilme_4K_SDR.srt    (se legenda externa existir)
└── NomeDoFilme_1080p_HDR/
    ├── NomeDoFilme_1080p_HDR.mkv
    └── NomeDoFilme_1080p_HDR.srt
```

### Legendas Externas

O scanner detecta automaticamente legendas (.srt, .ass, .ssa, .sub, .idx, .vtt) que compartilham o mesmo nome base do vídeo e as copia para a pasta de destino.

### Configuração

O arquivo `config.json` é criado automaticamente na primeira execução:

```json
{
  "output_dir": "./conversions",
  "max_parallel": 2,
  "ffmpeg_path": "ffmpeg"
}
```

## Estrutura do Projeto

```
├── main.py                 # Entry point - menu interativo com TUI
├── requirements.txt        # Dependências (rich)
├── config.json             # Configuração (gerado automaticamente)
├── src/
│   ├── profiles.py         # Perfis de conversão (comandos FFmpeg)
│   ├── encoder.py          # Engine de execução FFmpeg (async)
│   ├── file_scanner.py     # Descoberta de arquivos e legendas
│   └── tui.py             # Componentes de interface (Rich)
└── README.md
```
