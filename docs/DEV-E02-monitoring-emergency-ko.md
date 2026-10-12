# DEV-E02 운영 조회와 긴급 정지

CLI는 executor 사용자 권한에서 검토된 release의 `scripts/e02-runtime.sh`로
실행한다. 일반 사용자는 원장/제어 파일 쓰기 권한을 갖지 않는다. 승인된
운영자는 해당 사용자로 CLI를 실행할 수 있는 제한된 sudo 정책을 별도 검토한다.

```bash
bash scripts/e02-runtime.sh status
journalctl -u crypto-t1-testnet-executor.service --no-pager -n 100
bash scripts/e02-runtime.sh off --confirm
bash scripts/e02-runtime.sh kill --confirm
```

status는 주문, 실제 체결 반영 포지션, allocation, 최근 명령 결과 및 runtime
PnL/protection 상태를 읽는다. `REQUESTED`는 성공 완료가 아니므로 responses와
health를 확인한다. Executor는 OFF시 30초/ON시 5초 주기로 처리한다. JSON
로그는 10MB×6 순환 보관하며 원장에는 주문/위험/복구 감사 기록을 보존한다.
로그/명령 결과에는 API secret을 넣지 않는다.

OFF는 즉시 durable mode를 바꾸어 다음 HTTP 주문 송신을 막는다. 이미
송신 중인 요청을 취소하거나 미체결 주문을 즉시 청산한다는 의미는 아니다.
KILL은 durable 파일과 원장 kill을 남긴다. 둘 다 신규 보호 주문도 차단한다.
서버를 내리면 software ATR 감시도 멈추므로 열린 주문/보유 수량을 먼저 확인한다.

기존 T1 미체결 주문만 명시적으로 취소한다. 수동1507111이나 소유권이 없는
주문은 CLI로 취소할 수 없다. 서비스는 60초가 지난 T1 LIMIT의 잔여 수량을
취소하고 부분 체결은 원장에 보존한다. 취소는 별도 DELETE 호출이며 capability,
정합성 및 Testnet 경로 규칙을 유지한다.

```bash
bash scripts/e02-runtime.sh cancel --confirm --client-id <existing_t1_client_id>
bash scripts/e02-runtime.sh recover --confirm
bash scripts/e02-runtime.sh status
```

recover는 GET 정합성 재확인만 한다. HOLD, UNKNOWN, reset을 자동 삭제하지
않는다. UNKNOWN은 기존 client ID로 조회하며 같은 주문을 재전송하지 않는다.
외부 주문/잔고 변경/계좌 reset/DB 실패는 로그·원본 백업을 보존하고 사용자의
검토를 요청한다. SQLite 직접 UPDATE/삭제, init-session, acknowledge-reset을
우회 해결책으로 사용하지 않는다.

KILL 해제는 실제 GET 결과, 미체결 없음, 원장 hold 없음, baseline/할당/B/C,
Collector/Observer READY를 확인한 뒤 status의 operator_review_token으로:

```bash
bash scripts/e02-runtime.sh reset-kill --confirm --token <operator_review_token>
```

이 명령은 OFF로만 복구한다. 새 전체 preflight와 사용자 ON 승인이 필요하다.
미확정/hold/open 주문이 있으면 해제하지 않는다. dust/일일 한도 부족/
손절 보호 불가 상태의 HOLD는 다음 운영 판단을 요구한다. 일일 제한을
늘리거나 실계좌/시장가 주문으로 전환하지 않는다.
