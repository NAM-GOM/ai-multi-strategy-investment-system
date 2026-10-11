# DEV-E02 실제 활성화 Preflight

현재 실환경 판정은 **HOLD / NOT_TESTED**다. 개발용 Mock PASS는 NUC 또는
실제 Testnet의 연결·주문·체결 증거가 아니다. 아래 순서를 실제 운영자가
수행하고 결과를 검토한 뒤 배포/활성화를 각각 승인한다.

## 1. 우선 read-only inventory

승인한 검토용 E02 checkout에서 다음을 실행한다. 서비스 설치/시작, DB
쓰기, 키 조회, 주문 API 호출 없이 상태와 기존 원장을 읽는다.

```bash
cd /srv/CryptoAutoTrading/releases/dev-e02
bash scripts/e02-nuc-readonly.sh
```

경로가 실제 설치 위치와 다르면 먼저 출력과 unit의 경로를 대조한다. 이
단계에서는 디렉터리 생성, chown, init-session, 기존 DB 복사 덮어쓰기를
하지 않는다. 실행 중 DB 백업은 SQLite Backup API를 사용하고 단순 cp를
백업 완료 증거로 사용하지 않는다. 정지 상태 파일 검사는 원본·wal·shm을
일관된 집합으로 확인한다.

확인할 증거:

- Frozen source 109/기존 M05 72 hash와 기준 SHA 일치.
- 실제 M05 Collector/Observer/Bridge 상시가동, 재시작·재부팅, 장애/HOLD,
  신규 확정봉 관찰 등 기존 TEST-02..07 결과와 로그/시간/instance.
- 세 DB 경로 분리, integrity, 현재 세션·hold/kill·미확정 주문·외부 주문.
- 기존 Gate B/C 및 MANUAL 주문1507111의 원본 증거. C 누락이면 중단한다.
- 실제 observer LIVE 행/연속봉/워밍업/현재 run, 신호 발생 여부.
- 실행 중 원장 writer와 열린 writable FD, 소유권/권한/bridge 읽기 권한.

M05 가이드의 init/배포 명령 실패를 무시한 진행, 비어 있는 DB에도 7일만
수집하는 워밍업 경로, SQLite BUSY 영구 HOLD 가능성은 원본에서 그대로
남아 있다. E02는 M05 검증 완료를 대신하지 않는다. 실제 M05 기준을
만족하지 못하면 먼저 별도 검토/수정 작업으로 해결한다.

## 2. 승인 후 OFF 배포 및 GET 연결

배포는 별도 승인 후 수행한다. 기존 writer를 정지하고 전용 소유권을
넘긴 뒤, E02 서비스는 OFF로 시작한다. 환경 파일은 전용 Spot Testnet 키만
보관하며 기존 두 unlock은 OFF를 유지한다. 초기 capability도 OFF다.

Executor 사용자 권한으로, 키를 화면에 출력하지 않는 보호된 환경에서:

```bash
bash scripts/e02-runtime.sh preflight --online --connection-only
```

고정 Testnet GET 계좌/주문/체결/잔고와 Testnet WS 시세를 조회한다. 원장
원본은 read-only, reconciliation은 임시 복사본에만 쓴다. `canTrade=false`,
계좌 초기화/외부 거래/원장 불일치/원본 HOLD는 PASS로 간주하지 않는다.
계좌 GET PASS는 Gate C 또는 최초 자동 주문 PASS가 아니다.

## 3. 실제 allocation / gates / 최종 검토

보호된 `m05-acceptance.json`은 실제 로그를 확인한 운영자가 작성한다.
템플릿은 모두 NOT_TESTED다. CI 결과를 ACTUAL_NUC PASS로 복사하지 않는다.
파일과 부모 디렉터리는 root 소유, group/other 쓰기 금지로 보호한다.

`allocate --confirm`는 **원본 E01 원장 변경**이다. 사용자 승인 후 한 번만
실행하며 free USDT>=1000, 수동 baseline 및 계좌 정합성을 확인한다. 기존
checkpoint가 다른 source라면 먼저 status 결과/토큰을 검토한 뒤
`bind --confirm --token <operator_review_token>`로 감사 기록을 남긴다.
bind 후 A/D는 다시 검증하고 과거 행은 자동 실행하지 않는다.

서비스 capability는 배포 승인 범위에서만 `YES_E02_TESTNET_ONLY`로 준비한다.
이 값은 ON이 아니며 서비스 재시작도 OFF다. 실제 신규 T1 신호의 60초
허용 창에 `phase-a --confirm`를 요청한다. 없으면 WAITING을 유지한다.
누락 B 검증이 필요하면 새 실제 후보로 `order-test --confirm`을 사용한다.
이는 실제 POST /order/test이므로 승인 대상이나 주문·체결은 발생하지 않는다.
누락 C를 만들기 위해 가짜 신호/수동 주문을 새로 보내지 않는다.

```bash
bash scripts/e02-runtime.sh preflight --online
bash scripts/e02-runtime.sh status
```

ACTIVATION_PREFLIGHT_PASS의 실제 evidence를 검토한다: M05 acceptance,
현재 의존성 instance, 실제 ABC, 계좌 세션/수동 baseline, 1000 allocation,
projection hash, original journal 상태, source 경로, cap 8.31. 실제 보유 수량과
미체결 수량에 대한 최소 주문금액·잔고 및 남은 일일 보호 예산도 점검한다.
부분 체결 잔여분을 보호할 수 없으면 HOLD다. 보호 예산과 당일 주문 기록은
승인 토큰에도 포함하며 상태가 바뀌면 토큰은 무효다.
**결과를 사용자에게 보고하고 ON 승인 후에만**:

```bash
bash scripts/e02-runtime.sh on --confirm --token <activation_token>
```

현재까지 존재하는 신호는 모두 건너뛴다. 이후 발생한 실제 LIVE 신호만
주문하며 없으면 ON_WAITING_NEW_LIVE_SIGNAL이다. 최초 자동 주문 이후
order ID/client ID, 실제 체결/잔고/수수료/포지션/손절을 지속 확인한다.
