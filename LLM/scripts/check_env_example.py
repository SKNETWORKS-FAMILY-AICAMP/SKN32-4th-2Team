"""`.env.example` 이 `Settings` 의 모든 설정 키를 담고 있는지 점검한다.

config.py 에 설정을 추가하고 .env.example 갱신을 잊으면, 팀원이 .env.example 을
복사해도 그 옵션의 존재를 모르게 된다. 실제로 한 번 발생해서 만든 가드다.

    python scripts/check_env_example.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 한국어 Windows 콘솔은 기본이 cp949 라 한글 출력이 깨진다.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import Settings  # noqa: E402

EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def main() -> int:
    declared = {name.upper() for name in Settings.model_fields}
    documented = set(re.findall(r"^([A-Z_]+)=", EXAMPLE.read_text(encoding="utf-8"), re.M))

    missing = sorted(declared - documented)
    extra = sorted(documented - declared)

    for key in missing:
        print(f"[누락] {key} : config.py 에는 있는데 .env.example 에 없습니다")
    for key in extra:
        print(f"[불필요] {key} : .env.example 에만 있고 config.py 가 읽지 않습니다")

    if missing or extra:
        return 1
    print(f"OK : 설정 키 {len(declared)}개가 .env.example 과 일치합니다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
