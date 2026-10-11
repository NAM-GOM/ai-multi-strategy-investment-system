# MR-W03 Final Audit

최종화 일자: 2026-10-11 UTC / KST. 감사 결과: **FINAL_ARTIFACT_CONSISTENCY_PASS**. 전략 결과: **M2 MR_W03_HOLD**.
감사 PASS는 파일·계산 정합성 판정이며 전략 PASS 또는 APPROVED/PAPER를 뜻하지 않는다. M1 HOLD / M3 REJECT_CANDIDATE 권고를 유지한다.

## 감사 범위와 근거

이번 실행은 기존 문서·CSV·Freeze·코드·로그를 읽고 대조했다. 추가 Backtest 0회, Parameter 최적화 0회, Registry 및 운영 상태 변경 0회다.
`intermediate/mr_w03/verify.py`는 기존 CSV와 보조 진단값만 검사하는 스크립트다. 이를 실행하고 새 최종화 검사로 중복 키, Freeze/runner Hash, OAT/비용 설정, CSV 간 지표, 모든 시나리오의 자산·시간 합계 및 HOLD 기준을 재계산했다. Engine·전략 runner·pytest는 실행하지 않았다.
자료는 기존 로컬 원본과 같은 이름의 6개 저장된 파일이다. 저장된 파일 ID·byte size도 연결했다. 이번에는 원격 파일의 download bytes를 다시 비교하지 않았으므로 원격 byte-exact 재감사라고 주장하지 않는다.

| 검증 항목 | 결과 | 근거 |
| --- | --- | --- |
| 최초 Preflight Freeze | PASS | 최종 preflight는 original frozen prefix를 그대로 보존; SHA 아래 참조 |
| freeze.json 및 run.py | PASS | decision.json에 기록된 SHA와 일치 |
| 11 시나리오 | PASS | Baseline1 + OAT8 + Stress2; 중복/누락 없음 |
| sensitivity.csv | PASS | 55행 = 11 × (FULL/3 UTC windows/COMMON_READY) |
| temporal.csv | PASS | 30행 = 3 비용 시나리오 × (3 windows/7 calendar years) |
| asset_consistency.csv | PASS | 132행 = 11 × 3 assets × (FULL/3 windows) |
| OAT 설정 | PASS, 범위 제한 별도 기록 | 각 이웃은 period/sigma/ema/stop_atr 중 하나만 변경; 비용 동일 |
| 비용 Stress | PASS | parameter는 baseline; 10/10 및 20/20 bps per side |
| 기간·자산 회계 | PASS | 각 시나리오 MTM 합계와 FULL 일치, abs tolerance 1e-6 USDT |
| Gross/Fee/Slippage/Net | PASS | raw gross − fee − slip = trade net; 이중 차감 없음 |
| CSV 간 대조 | PASS | 시간구간 count/PnL/MDD/PF/Expectancy 일치; 자산 거래 수 합계 일치 |
| 부분 연도·경계 | PASS | UTC, 2020/2026 partial; continuous state; 실제 마지막 cutoff 포함 |
| 사전 판정 기준 | PASS | 9 PASS gates/3 REJECT gates 및 LOW_SAMPLE 모두 원본 decision.json과 동일 |
| MR-W01 Baseline 원장·summary | PASS | 동결 manifest의 SHA와 byte-exact |
| 독립 MR-W03 전 시나리오 재현 | 이번 범위 밖 | MR-R01은 당시 자료 미제공으로 BLOCKED; 이번 감사로 닫지 않음 |

36 tests, 6 Stop/gap synthetic checks, 24 prefix checks 및 300 baseline trades/equity parity PASS는 기존 preflight/log의 실행 기록이다. 이번에 재실행한 검사가 아니며 독립 새 검증으로 세지 않는다.

## 11개 시나리오 고정 목록

| ID | Period | σ | EMA | ATR Stop 배수 | Fee/Slip bps per side | FULL Net USDT |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| BASELINE | 20 | 2.0 | 200 | 2.5 | 10/5 | -51.98 |
| period_16 | 16 | 2.0 | 200 | 2.5 | 10/5 | -3,223.90 |
| period_24 | 24 | 2.0 | 200 | 2.5 | 10/5 | 7,531.02 |
| sigma_1.6 | 20 | 1.6 | 200 | 2.5 | 10/5 | -7,856.88 |
| sigma_2.4 | 20 | 2.4 | 200 | 2.5 | 10/5 | 28.27 |
| ema_160 | 20 | 2.0 | 160 | 2.5 | 10/5 | 2,690.92 |
| ema_240 | 20 | 2.0 | 240 | 2.5 | 10/5 | -2,656.42 |
| stop_atr_2 | 20 | 2.0 | 200 | 2.0 | 10/5 | -3,789.29 |
| stop_atr_3 | 20 | 2.0 | 200 | 3.0 | 10/5 | 693.69 |
| MODERATE | 20 | 2.0 | 200 | 2.5 | 10/10 | -2,699.68 |
| SEVERE | 20 | 2.0 | 200 | 2.5 | 20/20 | -15,447.98 |

## 동결 판정 확인

Positive는 Net>0 AND PF>1 AND USDT Expectancy>0이다. undefined PF는 통과가 아니다.
우선순위는 Preflight 실패/LOW_SAMPLE→HOLD, REJECT 조건 하나 이상→REJECT, PASS 조건 전부→PASS, 나머지→HOLD다.
Threshold·우선순위·시나리오를 변경하지 않았다. Baseline 300건, 각 window 99/125/76건, 각 asset 105/98/97건이므로 LOW_SAMPLE=False. 세부 asset-window 30건 미만은 일반화 제한으로 남기며 전체 기준으로 소급 확대하지 않는다.

| PASS gate | 충족 |
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

REJECT PERSISTENT_LOSS/JOINT_FRAGILITY/SEVERE_RISK는 모두 False다. OAT Positive 4/8, 가족별 1/2; 시간구간 2/3, 자산 2/3이다.
Full-year 양수 손익 상위2년 비중 82.90259356%, 양수 자산 최대 기여 87.44618887%로 80% 한도를 넘었다. Baseline과 Moderate 음수도 유지됐다. 결과는 HOLD이며 Registry에 제안하는 cycle label은 MR_W03_HOLD다.
SEVERE 비용 MDD는 Parameter neighbor 위험 gate에 임의 포함하지 않았다. 동결 기준을 더 엄격하거나 유리하게 다시 정의하지 않는다.

## Final Artifact, Hash와 Git 근거

- Baseline source repository: NAM-GOM/ai-multi-strategy-investment-system.
- Baseline source Git commit: `bc2ca95d98c4d3e0e7bf3ca9e5e52f545848447e`. 실제 GitHub commit과 Bollinger source를 읽어 확인했다.
- Final payload archive Git commit: `50281aabbc91816dab7bd26067eddeffa7660474`. **격리된 보존용 저장소의 commit**이며 upstream research/운영 branch에 push하지 않았다.
- Original Freeze SHA256: `05093a863a309412e13d028928dd1791ece0c759f8e0deb8732bdb3cb33a281c`.
- freeze.json SHA256: `d5069dfabfb1374d75bb742de6ccef63f5ee449b1d9a38cc46d0b51dc4676b22`.
- original runner SHA256: `1e24300bca2b3dc66d9c91e83f366e5c457fda1353c9d760ee66fedd3fa1a63c`.
- Payload SHA256SUMS.json SHA256: `e7f9e2da0ad51ed4b8987b9a5d9f51ddc92bbbf9c0eb65e16b8fe97454a3910b`.
- Git bundle SHA256: `ea85ec35d337cd77e8a149f4514fa21d4f52d37114115fa3e37d639779b09d1b`.

Git bundle은 위 commit의 전체 Git 객체를 포함하고 `git bundle verify`를 통과했다. 기존 6개 결과, Freeze, 실행 코드·테스트 기록·진단 보조 CSV, baseline source/tests, 기존 clean history와 snapshot lock, W01 manifest/trades/summary를 byte-preserving 복사해 보존했다. 세부 파일은 payload SHA256SUMS.json과 library_sources.json에 있다.
MR-W01 signals/equity 전체 CSV는 이 로컬 원본 폴더에 없으므로 최종 묶음에 새로 만들지 않았다. 원본 source commit과 manifest Hash 참조를 유지했다. 11개 시나리오의 전체 trade/equity ledger가 묶음에 모두 있다는 주장도 하지 않는다.

| 기존 MR-W03 Final 결과 | SHA256 (raw local bytes) |
| --- | --- |
| MR-W03_sensitivity.csv | `74a49f8d4af2fe4291c1ae373ec3642a50891761d7a7c9d5ecbba4e4b40fde12` |
| MR-W03_temporal.csv | `cb08f60ad82491055d3894e9b17fe8783256113c47b04f847ecba1744d8c6a1d` |
| MR-W03_asset_consistency.csv | `8cd8e092c152e1e0b24721590cd1534465d45045cbf4569a02ea9b6442882993` |
| MR-W03_preflight.md | `a0a000f0f50fb8ef2a4e5294da9bfd2c5fda8a028127b3bb78992e6b0c05d791` |
| MR-W03_report.md | `3d71ac62cd4e92e1e51ef34faea0c41730d6985b43ae1634d71d346d07a92784` |
| MR-W03_decision.md | `48ea6af21b469c5435aebeef19014bef730b1e2560c2302a6a214561d796fb21` |

M2 v0.1은 Period20/σ2(ddof0)/EMA200(adjust=False)/ATR20×2.5, next-open, signal ATR 고정, exit 우선, BTC→ETH→SOL cash allocation, risk0.005/cap0.333, fee10/slip5를 그대로 보존한다. entry는 이전 Close<이전 하단밴드, 현재 Close≥현재 하단밴드와 Close>EMA200이며, exit는 Close≥SMA20이다.

| Baseline source file | upstream manifest SHA256 | preserved local copy SHA256 |
| --- | --- | --- |
| src/trading_system/research/mr_w01/__init__.py | `524c816f927d1e3c9edad3e644f8bff71d9d98489183c1f66308d02a68633444` | `524c816f927d1e3c9edad3e644f8bff71d9d98489183c1f66308d02a68633444` |
| src/trading_system/research/mr_w01/data.py | `8df8c895b51ecb879d1a35e7c79927744a351022d6967fa75eea3a7c1a20c86f` | `8df8c895b51ecb879d1a35e7c79927744a351022d6967fa75eea3a7c1a20c86f` |
| src/trading_system/research/mr_w01/engine.py | `8452be44a6b7b85d40d5cea763ca3419ded87f5c0ca237b5e9eebb9ff92b214a` | `8452be44a6b7b85d40d5cea763ca3419ded87f5c0ca237b5e9eebb9ff92b214a` |
| src/trading_system/research/mr_w01/reporting.py | `40db4b44435afbb4283c5c7ada15b9f0e53e1f964eb19aaf0e718822470ee3c5` | `e632af02d40f7bdcac0961f6d122990ec951ab1a7dba85b63afb20b511ff3aa7` |
| src/trading_system/research/mr_w01/run.py | `d5ec548c38a7bbe6f0bfb865c7fac92c98a2c8fb2958173221364b85703a5de7` | `6c9a96a2c6a5b7ef960ba7c95a04afe1f579a80cfc06aee0d720f994dee8dfd6` |
| src/trading_system/research/mr_w01/strategies.py | `b72182d5bff7f690f478dd46d52f4a6b23c2cc062c0a31f6f7a3b3182aa88082` | `b72182d5bff7f690f478dd46d52f4a6b23c2cc062c0a31f6f7a3b3182aa88082` |

일부 기존 local source는 fetch 과정에서 마지막 LF가 추가되어 upstream manifest와 raw bytes가 다를 수 있다. 검사에서 원본 raw 또는 마지막 LF 한 개를 제거한 bytes만 허용했고, 실제 copy Hash를 위에 함께 기록했다. 원본을 수정하거나 source byte-exact라고 일반화하지 않는다. 정식 Baseline identity는 upstream commit에 고정된다.

최종 ZIP은 payload export, Git bundle, 이번 3개 문서와 seal_receipt.json을 포함한다. Git 객체의 content-addressed identity와 SHA는 내용 변경을 탐지하며 배포 파일은 read-only로 표시한다. 파일 저장소의 관리자 삭제/교체를 막는 WORM 또는 retention lock을 설정한 것은 아니다. 기존 Final을 덮어쓰지 않고 모든 변경은 별도 Version/새 commit·새 seal로 남긴다.

## 보존 범위와 남은 제한

Trend W03/W04, NUC Observer, DEV 운영 코드를 편집·실행·배포하지 않았다. 실제 Strategy Registry를 읽거나 변경하지 않고 schema-neutral 제안만 작성했다.
데이터는 이미 관찰된 과거 자료이며 Genuine Unseen OOS가 아니다. MR-R01의 독립 전 시나리오 검증 BLOCKED, raw-page provenance 누락, decimal/binary64 Stop equality 합성 경계 한계는 이번 정합성 PASS로 해결됐다고 주장하지 않는다.
후속 실행은 handoff 검토 후 Registry의 연구 판정/history 반영 여부를 사용자가 승인하는 일이다. M2의 APPROVED/PAPER 승격은 제안하지 않는다. 새로운 Mean Reversion 아이디어는 별도 Version의 별도 연구 사전 계획으로 시작한다.
