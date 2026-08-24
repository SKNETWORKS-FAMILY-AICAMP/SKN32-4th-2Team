# 데이터 작성 규칙

`candidates.jsonl`은 검수 작업용 마스터 파일입니다. 각 줄은 아래 필드를 가집니다.

- `id`: 중복되지 않는 샘플 ID
- `split`: `train` 또는 `valid`
- `intent_group`: 같은 의도의 패러프레이즈를 묶는 이름
- `category`: 팀 서비스의 8개 HR 카테고리 중 하나
- `case_type`: `grounded`, `no_context`, `personal_data`, `conflicting_documents`
- `question`, `answer`: 실제 학습할 질문과 답변
- `evidence`: `source_file`, `page`, `text`를 가진 근거 목록
- `approved`: 사람 검수가 끝났을 때만 `true`
- `reviewer`: 검수자 이름 또는 이니셜
- `holdout_overlap_reviewed_by`, `holdout_overlap_note`: 홀드아웃 질문과 문자 유사도가
  0.60~0.85인 경우 의미상 중복이 아님을 검토한 사람과 판단 근거

`data/holdout.jsonl`은 기존 34문항 평가 전용입니다. 학습 답변을 만들거나 질문을
변형하는 재료로 사용하면 안 됩니다. `prepare_dataset.py`는 완전 일치, 높은 문자
유사도, `intent_group` 충돌을 검사합니다. 유사도 0.60~0.85는 자동 승인하지 않고
별도 수동 검토 기록을 요구합니다.

최종 생성 명령은 다음과 같습니다.

```bash
python assemble_drafts.py
python validate_drafts.py
python create_data_review.py
# reports/training_data_review.csv를 사람이 검수하고 저장
python apply_data_review.py
python prepare_dataset.py
```

승인 샘플이 80/20 미만이면 의도적으로 실패합니다. 코드 파이프라인만 확인할 때는
`--allow-small`을 사용할 수 있지만, 그 결과는 성능 실험으로 인정하지 않습니다.
