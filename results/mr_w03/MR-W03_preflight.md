# MR-W03 Preflight — 실행 전 Freeze

## 고정 시점과 범위

이 문서의 아래 설계·기준은 MR-W03 신규 민감도 결과를 계산하기 전에 고정한다.
MR-W01/MR-W02 Baseline 성과와 2024년 손실은 이미 알려져 있다. 따라서 새로운 사전 미관측 실험이라고 주장하지 않는다.
Threshold는 이번 연구의 운영 판단 기준이며 통계적 유의성이나 보편적 금융 기준이 아니다.
M1 HOLD / M3 REJECT_CANDIDATE 권고와 Trend W03/W04·운영 Observer는 유지한다.

Source commit: bc2ca95d98c4d3e0e7bf3ca9e5e52f545848447e.
동일 MR-W01 clean snapshot, UTC, 4H, BTC/ETH/SOL 공동 100,000 USDT.
기간 2020-09-13 16:00~2026-10-02 12:00 UTC. 0.5% risk / 33.3% cap / fee10+slip5 bps per side.
BTC→ETH→SOL 현금 배분 순서, next-open, exit 우선, 고정 signal ATR20, intrabar Stop, adverse gap, final accounting 보존.
Baseline: Period20 / sigma2(ddof0) / EMA200(adjust=False) / ATR20×2.5.
MR-W02 군집·종가경로·환경 계산은 원장과 대조한다. 원본 report의 below_entry_ratio가 Stop보다 작게 나온 것은 추가 검토 대상으로 삼고 신호·거래 계산에는 사용하지 않는다.

## OAT (One-at-a-Time: 한 번에 하나만 변경)

| 가족 | Baseline | 이웃 1 | 이웃 2 |
|---|---:|---:|---:|
| Bollinger Period | 20 | 16 | 24 |
| Standard Deviation 배수 | 2.0 | 1.6 | 2.4 |
| EMA Period | 200 | 160 | 240 |
| ATR Stop 배수 | 2.5 | 2.0 | 3.0 |

8개 사전 지정 이웃을 전부 보고한다. 조합 실험·순위 기반 선택·최적값 채택은 하지 않는다.
Bollinger Period는 하단 밴드와 청산 평균선의 기간에 함께 적용한다. ATR indicator 기간20은 유지한다.
Baseline 규칙은 변경하지 않고 별도 진단 harness에서만 실험한다.
기존 엔진은 Stop2.5가 상수이므로 harness에서 함수 서명에 stop_multiple을 노출하고 해당 distance 표현 한 곳만 대체한다.
기존 source 파일은 수정하지 않으며 stop_multiple2.5에서 원본 엔진과 모든 거래·equity가 정확히 같은지 검사한다.
EMA240은 같은 초기 이력에 240봉이 필요하므로 최초 39개 evaluation 봉에서 EMA를 계산할 수 없다. 이를 INIT_WINDOW_DIFFERENCE로 표시한다.
모든 주 결과의 시작·끝은 동일하게 유지하며, 보조 비교는 전체 변형의 indicator-ready 시점 이후 동일 구간도 보고한다. 새 이력을 추가하지 않는다.

## 시간·경계 처리

UTC 캘린더 구간은 [2020-01-01,2023-01-01), [2023-01-01,2025-01-01), [2025-01-01,2027-01-01)이다.
실제 데이터에 clip하여 첫 구간은 2020-09-13 16:00부터, 마지막은 2026-10-02 12:00까지다.
2020·2026은 PARTIAL_YEAR로 표시한다. 2021~2025만 full-year 집중도 계산에 사용한다.
현금·포지션은 전체 sample에서 연속 운용한다. 경계 강제 청산이나 자본 재설정은 하지 않는다.
시작 직전 equity mark를 기초로 (start,end] 종가 평가 손익을 귀속한다. 실제 최종 경계에만 MR-W01 terminal accounting을 포함한다.
Trade PF/Expectancy/Win Rate는 entry>=start AND exit<end인 완결 거래만 사용한다.
경계 보유 거래는 trade ratio에서 제외하고 개수·손익을 별도로 보고한다. Equity에는 해당 기간 MTM 변화가 포함된다.
별도 연도별 청산 원장은 exit UTC 연도로 전체 거래 손익을 귀속한다. MTM 연도 손익과 혼동하지 않는다.
trade_count는 완결 거래 수, boundary_trade_count는 구간과 겹친 미완결 거래 수, allocated_exit_trade_count는 청산 연도 기준 수다.
전체100건, 시간구간30건, 자산30건 미만은 LOW_SAMPLE이며 최종 HOLD. 연도·조건별30건 미만은 설명용 표본으로 표시한다.

## 비용·2024 진단

비용 시나리오는 Baseline fee10/slip5, Moderate fee10/slip10, Severe fee20/slip20 bps/side.
이번 비용 stress는 같은 엔진으로 수량·현금·Stop 영향을 포함해 full rerun한다. MR-W02의 fixed-trade repricing과 구분한다.
Baseline보다 유리한 비용 가정으로 바꾸지 않는다. Stop 손실/비Stop 손실/양수 거래/비용을 분해한다.
2024와 나머지 full years를 비교하고 자산·월·환경별 Stop 비율, 신호 후 추가 하락, 손실 기여를 보고한다.
환경은 MR-W02 정의: EMA200의30봉 변화±1%, 이전60봉 변동성을 과거 expanding median과 비교한다.
새로운 필터로 사용하지 않는다. Gap Loss는 raw fill이 Stop 아래인 추가 손실이며 Net에서 중복 차감하지 않는다.

## PASS / HOLD / REJECT — 판정 우선순위

Positive = Net PnL>0 AND PF>1 AND Expectancy>0. undefined PF는 Positive를 입증하지 못한다.
먼저 Preflight 실패/자료 부족이면 HOLD. 계산 오류는 결과 판정을 중단하고 원인을 보고한다.

REJECT는 다음 중 하나일 때:
1. Baseline 비양수이고 시간구간3/3 비양수, 자산2/3 이상 비양수.
2. Baseline 비양수이고 이웃6/8 이상 비양수 AND 가족3/4 이상에서 이웃2개 모두 비양수 AND 시간구간 또는 자산2/3 이상 비양수.
3. Baseline |MDD|>=20%, 또는 어느 이웃에서 |MDD|>=15% AND Baseline의2배 이상.
첫 두 조건은 손실과 취약성이 여러 축에서 함께 반복되는지 확인한다. 한 조건의 작은 악화만으로 Reject하지 않는다.

PASS는 다음을 모두 충족:
- Baseline Positive.
- 시간구간2/3 이상 Positive.
- 자산2/3 이상 Positive.
- 이웃6/8 이상 Positive AND 각 가족에서 최소1/2 Positive.
- 모든 이웃 |MDD|<=Baseline |MDD|의1.5배.
- Moderate cost full rerun Positive.
- Full-year 양수 손익의 상위2개 연도 비중<=80%.
- 양수 자산 Net 손익의 최대 자산 비중<=80%.

그 외 HOLD. 집중도는 양수 Net 기여끼리 계산하며 총손익이 0에 가까운 값으로 나누지 않는다.
Baseline이 MR-W02에서 소폭 음수였으므로 재현이 정상이라면 PASS의 Baseline 항목은 충족되지 않을 가능성이 이미 알려져 있다.
결과를 보고 이 기준을 완화하지 않는다. 최종 판정은 v0.1 연구 경로 권고이며 APPROVED/PAPER 승격이 아니다.

## 실행 결과 (실행 후 append)

아직 MR-W03 결과를 계산하지 않았다. 위 Freeze 텍스트 SHA256을 별도 기록하고 실행 후 변경 여부를 검사한다.



### 실행 결과 append

RESULT: MR_W03_PREFLIGHT_PASS

Freeze SHA256: 05093a863a309412e13d028928dd1791ece0c759f8e0deb8732bdb3cb33a281c
Preflight 완료 UTC: 2026-10-10T14:39:13.878845+00:00

- 36 existing MR-W01/MR-W02 tests PASS
- all 300 baseline trade rows reproduced
- MR-W02 cost/PnL/stop count reproduced
- Baseline indicator harness exact parity PASS
- Stop-parameter harness exact full trade/equity parity PASS
- 6 adverse gap/entry Stop tests across 2/2.5/3 ATR PASS
- 24 OAT prefix invariance checks PASS

11개 사전 지정 시나리오(기본1+OAT8+비용stress2), 시나리오별 accounting 검사 PASS.
Baseline 시간구간·연도·자산 MTM 합계가 full Net와 일치. 원본 코드/테스트/W03 lock 변경 없음.
MR-W02 보조 below_entry_ratio 집계 오류는 report에서 별도로 명시했다. 원장·PnL 재현에는 영향 없음.

표기 정정: EMA240 초기 부족 봉은 Freeze 원문의39가 아니라 실제38봉이며 common-ready 시작은 index239이다. 마지막 부분 연도 판별은 exclusive endpoint 직전 연도를 사용한다. 판정 설계와 주 실험 경계는 변경하지 않았다.
