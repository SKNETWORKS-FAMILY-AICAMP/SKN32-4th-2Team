"""RunPod가 학습 가능한 상태인지 빠르게 검사한다."""

from __future__ import annotations

import shutil
import sys


def main() -> int:
    errors: list[str] = []
    if sys.version_info < (3, 10):
        errors.append("Python 3.10 이상이 필요합니다.")
    try:
        import torch

        if not torch.cuda.is_available():
            errors.append("PyTorch가 CUDA GPU를 인식하지 못합니다.")
        else:
            props = torch.cuda.get_device_properties(0)
            vram_gib = props.total_memory / 1024**3
            print(f"GPU: {props.name} / VRAM {vram_gib:.1f} GiB")
            if vram_gib < 20:
                errors.append("7B QLoRA 실험에는 24GB급 GPU를 권장합니다.")
        print(f"PyTorch: {torch.__version__} / CUDA: {torch.version.cuda}")
    except ImportError:
        errors.append("torch가 설치되어 있지 않습니다. RunPod PyTorch 템플릿을 사용하세요.")

    if shutil.disk_usage(".").free < 30 * 1024**3:
        errors.append("현재 경로의 여유 공간이 30GB 미만입니다.")

    if errors:
        for error in errors:
            print(f"[실패] {error}")
        return 1
    print("[통과] CUDA, Python, 디스크 기본 검사가 완료되었습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

