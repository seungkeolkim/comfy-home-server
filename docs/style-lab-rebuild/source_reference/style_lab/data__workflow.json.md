# Source Snapshot: data/workflow.json

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\data\workflow.json`
- Original Byte SHA-256: `4343204f4895a57352be76f966b3be6d9430a8b92dba597a28a2532ae3ade247`
- Snapshot Text SHA-256: `85713285cf2819f8d7ec766816f62866a932c93ad3713b9d8f27f5a8c8abb393`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```json
{
  "1": {
    "class_type": "UNETLoader",
    "inputs": {
      "unet_name": "anima_turboV11.safetensors",
      "weight_dtype": "default"
    }
  },
  "2": {
    "class_type": "CLIPLoader",
    "inputs": {
      "clip_name": "qwen_3_06b_base.safetensors",
      "type": "stable_diffusion",
      "device": "default"
    }
  },
  "3": {
    "class_type": "VAELoader",
    "inputs": {
      "vae_name": "qwen_image_vae.safetensors"
    }
  },
  "4": {
    "class_type": "CLIPTextEncode",
    "inputs": {
      "text": "",
      "clip": [
        "style_lab_negpip",
        1
      ]
    }
  },
  "5": {
    "class_type": "CLIPTextEncode",
    "inputs": {
      "text": "",
      "clip": [
        "style_lab_negpip",
        1
      ]
    }
  },
  "6": {
    "class_type": "EmptyLatentImage",
    "inputs": {
      "width": 896,
      "height": 1152,
      "batch_size": 1
    }
  },
  "7": {
    "class_type": "KSampler",
    "inputs": {
      "model": [
        "style_lab_negpip",
        0
      ],
      "positive": [
        "4",
        0
      ],
      "negative": [
        "5",
        0
      ],
      "latent_image": [
        "6",
        0
      ],
      "seed": 1924072827,
      "steps": 12,
      "cfg": 1.0,
      "sampler_name": "er_sde",
      "scheduler": "simple",
      "denoise": 1.0
    }
  },
  "8": {
    "class_type": "VAEDecode",
    "inputs": {
      "samples": [
        "7",
        0
      ],
      "vae": [
        "3",
        0
      ]
    }
  },
  "9": {
    "class_type": "PreviewImage",
    "inputs": {
      "images": [
        "8",
        0
      ]
    }
  },
  "style_lab_negpip": {
    "class_type": "CLIPNegPip",
    "inputs": {
      "model": [
        "1",
        0
      ],
      "clip": [
        "2",
        0
      ]
    },
    "_meta": {
      "title": "NegPip - Positive Prompt의 음수 가중치 적용"
    }
  }
}
```
