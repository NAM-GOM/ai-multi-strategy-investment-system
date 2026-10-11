# MR-W03 Registry Handoff — 승인 대기 제안

**PROPOSED / NOT_APPLIED / USER_APPROVAL_REQUIRED**. 이번 작업은 실제 Registry 상태를 변경하지 않았다. 현재 Registry schema/행을 직접 조회한 patch가 아니라 사용자 제시 판정에 근거한 schema-neutral 변경 제안이다. 승인 전 적용·자동화·merge하지 않는다.

| 전략 | 보존할 MR-W01 이력 | 보존할 MR-W02 연구 권고 | 추가할 연구 판정 / 제안 | 운영 승격 |
| --- | --- | --- | --- | --- |
| M1 meanrev_rsi_v0.1 | NEGATIVE_DIAGNOSTIC | HOLD | HOLD 유지; 신규 승인 상태 없음 | 없음 |
| M2 meanrev_bollinger_v0.1 | NEGATIVE_DIAGNOSTIC | CONTINUE_RESEARCH (historical) | MR-W03: **MR_W03_HOLD**; latest research recommendation HOLD | APPROVED/PAPER 아님 |
| M3 meanrev_shock_v0.1 | NEGATIVE_DIAGNOSTIC | REJECT_CANDIDATE 권고 | 권고 유지; 연구 중단 권고 | 없음 |

MR-W02의 CONTINUE_RESEARCH는 과거 연구 단계 권고로 남기고 MR-W03의 최신 HOLD를 덧붙인다. 이전 판정을 삭제·치환하지 않는다. M3 REJECT_CANDIDATE는 연구 권고이며 사용자 승인 없이 운영 state enum을 REJECT로 바꾸지 않는다.

## 제안할 M2 연구 기록

```json
{
  "strategy_id": "meanrev_bollinger_v0.1",
  "cycle": "MR-W03",
  "cycle_result": "MR_W03_HOLD",
  "research_recommendation": "HOLD",
  "artifact_status": "FINAL",
  "approval_requested": "research record and history only",
  "approval_or_paper_promotion": false,
  "source_commit": "bc2ca95d98c4d3e0e7bf3ca9e5e52f545848447e",
  "final_artifact_commit": "50281aabbc91816dab7bd26067eddeffa7660474",
  "evidence_type": "observed historical robustness diagnostics",
  "genuine_unseen_oos": false,
  "registry_write_status": "NOT_APPLIED"
}
```

이 키는 제안용이며 실제 Registry field 이름을 가정하지 않는다. 현재 operational status/권한은 그대로 유지하며 research label을 operational status로 자동 매핑하지 않는다.

근거: Baseline −51.98 USDT, PF0.998711,300건; OAT4/8 Positive; 각 가족1/2; 시간구간2/3·자산2/3 Positive. Moderate −2,699.68 USDT. Positive full-year 상위2년82.9026%, Positive 자산 최대87.4462%. PASS 다섯 gate 실패, REJECT 세 gate 미충족, LOW_SAMPLE=False에 따라 사전 기준의 HOLD가 유지됐다.

연결할 근거 파일: MR-W03_final_audit.md, MR-W03_specification_deviation.md, 기존 Preflight/report/decision/세 CSV, MR-W03_final_artifact.zip의 Git bundle 및 SHA256SUMS. Original Freeze Hash `05093a863a309412e13d028928dd1791ece0c759f8e0deb8732bdb3cb33a281c`.

## 적용 작업과 사용자 승인 범위

1. 사용자는 **M1 HOLD / M2 MR_W03_HOLD / M3 REJECT_CANDIDATE 연구 권고 및 이력 추가**라는 제안을 검토한다.
2. 사용자 승인 후 실제 Registry 최신 행·schema와 충돌을 확인하고, 해당 research/history 필드만 변경한 diff를 만든다. 본 제안 승인으로 운영 코드 변경·전략 승격·Paper·실주문·NUC 실행 권한을 얻지 않는다.
3. 승인 근거/시각과 적용 commit을 기록하고 기존 MR-W01/MR-W02 history 및 운영 status 보존을 검증한다. 해당 실행 전까지 현재 NOT_APPLIED를 유지한다.

다음 사용자의 실행 작업은 이 연구 기록 제안의 승인 여부 결정이다. 이번 최종화에서는 승인 질문으로 작업을 중단하지 않고 검토 가능한 파일을 완성했다.

## 연구 경로

현재 v0.1의 추가 검증 단계 진입은 HOLD다. 좋은 neighbor·ETH/SOL·유리한 연도만 골라 기존 전략을 개선하거나 승격하지 않는다. 새 Mean Reversion 전략은 별도 Version의 새 규칙·사전 기준으로 연구해야 한다. 이번 제안은 새 연구 cycle 실행을 요청하지 않는다.
MR-R01의 MR-W03 BLOCKED는 원본 전달·독립 검증 이슈로 유지한다. 이번 산출물 정합성 감사와 전체 독립 재현을 구별한다. Trend W03/W04, NUC Observer, DEV 및 Formal Clock에 대한 변경은 없다.
