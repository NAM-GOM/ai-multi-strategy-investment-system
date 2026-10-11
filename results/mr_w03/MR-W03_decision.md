# MR-W03 Decision

RESULT: **HOLD** — meanrev_bollinger_v0.1

Freeze SHA256: 05093a863a309412e13d028928dd1791ece0c759f8e0deb8732bdb3cb33a281c. 사전 고정 기준을 그대로 적용했다. 이미 본 과거 데이터의 연구 판정이다.
M1 HOLD / M3 REJECT_CANDIDATE 연구 권고와 MR-W01 NEGATIVE_DIAGNOSTIC을 보존한다.
이 결과는 APPROVED/PAPER 승격이나 실제 Registry 자동 수정이 아니다.

## PASS 기준

| gate | pass |
| --- | --- |
| BASELINE_POSITIVE | False |
| TEMPORAL_2_OF_3 | True |
| ASSET_2_OF_3 | True |
| NEIGHBOR_6_OF_8 | False |
| EACH_FAMILY_1_OF_2 | True |
| NEIGHBOR_MDD_1_5X | True |
| MODERATE_POSITIVE | False |
| YEAR_TOP2_MAX_80 | False |
| ASSET_MAX_80 | False |

## REJECT 기준

| gate | triggered |
| --- | --- |
| PERSISTENT_LOSS | False |
| JOINT_FRAGILITY | False |
| SEVERE_RISK | False |

LOW_SAMPLE: False. Positive neighbors 4/8, 시간구간 2/3, 자산 2/3.
Full-year 양수 손익 상위2개 연도 비중 82.90%; 양수 자산 최대 기여 87.45%.
연도·자산 집중도는 총손익이 거의0인 분모 대신 양수 기여 합을 분모로 삼았다.
Baseline 손실만으로 자동 REJECT하지 않으며, 사전 복합 조건의 충족 여부를 위 표에 명시한다.

## 후속 조치

현재 v0.1의 후속 검증 단계 승격을 보류한다. 자료 부족과 취약성의 원인을 유지한 채 재검토한다.
유리한 이웃·연도·자산·환경을 새로운 Baseline으로 채택하지 않는다. 새로운 아이디어는 별도 후보/Version으로 시작하고 전체 검증을 다시 설계한다.
Trend W03/W04와 운영 Observer는 이번 작업에서 접근하거나 변경하지 않았다.
사용자는 이 판정을 05 Strategy Registry의 MR-W03 연구 판정 필드에 기록하고 기존 MR-W01/MR-W02 판정 이력을 함께 보존한다.
