# 10월 12일 데이터 갱신 중단 수정

## FACT — 확인한 원인

2026-10-12 15:20 KST 조회에서 계좌 데이터는 10월 11일 22:54:11 KST,
시장 데이터는 22:45:58 KST에 멈춰 있었다. Collector는 COMPLETED,
Observer는 STOPPED였다. 대시보드 API는 close-validation-01의 과거 검증 DB를
고정해서 읽고 있었다. API 조회 시각과 서버 online 표시는 데이터 수신 시각이 아니다.

## 구현

M05 Collector/Observer 상시 서비스와 별도로 GET 전용 계좌 동기화 서비스를 추가했다.
기본 30초마다 기존 E01 원장을 읽기 전용 Backup API로 임시 복사하고 기존 E01
reconciliation을 실행한다. 임시 복사본의 최신 잔고·주문·체결을 단일 JSON으로
원자적으로 저장한다. 실제 E01 원장, receipts, checkpoint, 수동 매수, allocation은
변경하지 않는다. 영구 원장에 매번 517개 잔고 행을 추가하지 않는다.

API 패치는 continuous-01/market 및 observer DB를 우선하고, 없으면 기존 검증
자료임을 명시한다. 최신 JSON의 세션·시간·모드·금액을 검증해 잔고 표시를 갱신한다.
주문·체결 표는 기존 E01 원장의 기록으로 표시하며 출처를 명시한다. JSON에는
GET로 재확인한 주문·체결도 보존된다. 잔고 갱신만으로 손익·계좌평가액을 추정하지 않는다.
가격 조회는 종목별 LIMIT 1로 제한하여 커진 DB의 전체 그룹 스캔을 피한다.

시장 가격/계좌 잔고의 지연, 4H 전략 결정의 정상 간격, 실제 각 서비스의 heartbeat를
구분한다. UI 자동 재조회만으로 원본 갱신을 대체할 수 없다. UI 코드는 수정하지 않았다.
OFF 두 개와 GET-only HTTP 경계를 유지하며 실제 주문 호출은 0이다.

## BLOCKED / NOT_TESTED

NUC dashboard 개발 job 500bc64f2064470ea7aed8db68983a04는 코드 실행 전에
`Project-level Codex configuration is not authorized`로 실패했다. 동일 실패 작업을
재시도하거나 설정 검사를 우회하지 않았다. trading 배포 권한도 비활성화다.
따라서 서버 파일 수정·서비스 설치·실제 API 조회·실제 최신 데이터 수신은 미수행이다.

NUC API 읽기 도구는 전체 파일을 반환하지 않았다. 패치는 확인한 파일 SHA256
51affe76a2f0c0b0de255534bdaf2c9430fba2bd07bd187121d2b046bcfcf65c와 확인한
snapshot 구조에 한정되며, 전체 실제 API에서 적용/테스트는 아직 수행하지 않았다.
변경된 파일에는 적용을 거부한다. 별도 fixture 기반 AST/contract 테스트를 완료했다.
실환경 검증 전 DEV-M05_HOLD를 유지한다.

## 사용자 SSH 절차 — 코드 검토와 배포 승인 후

먼저 DEV-M05-deployment-guide-ko.md 1–5절로 새 release, 역할 계정,
Collector/Observer/Bridge를 준비한다. 기존 release 또는 DB를 덮어쓰지 않는다.
아래 추가 서비스는 독립된 읽기 전용 계정을 사용한다. 디렉터리/계정이 이미 있으면
기존 권한을 먼저 검토한다. root 권한으로 EnvironmentFile을 읽는 systemd만 키를
전달한다. Collector/Observer에는 키를 전달하지 않는다.

```bash
cd /srv/CryptoAutoTrading/releases/dev-m05
sudo useradd --system --no-create-home --shell /usr/sbin/nologin --gid crypto-read crypto-account-sync
sudo install -d -m 2750 -o crypto-account-sync -g crypto-read /var/lib/CryptoAutoTrading/state/continuous-01/account
sudo setfacl -m u:crypto-account-sync:r-x /var/lib/CryptoAutoTrading/state/testnet-e01
sudo setfacl -m d:u:crypto-account-sync:r-x /var/lib/CryptoAutoTrading/state/testnet-e01
sudo find /var/lib/CryptoAutoTrading/state/testnet-e01 -maxdepth 1 -type f -name 'testnet_execution.sqlite*' -exec setfacl -m u:crypto-account-sync:r-- {} +
sudo -u crypto-account-sync test -r /var/lib/CryptoAutoTrading/state/testnet-e01/testnet_execution.sqlite
sudo -u crypto-account-sync test ! -w /var/lib/CryptoAutoTrading/state/testnet-e01/testnet_execution.sqlite
sudo -u crypto-account-sync test ! -w /var/lib/CryptoAutoTrading/state/testnet-e01
sudo test ! -e /etc/systemd/system/crypto-testnet-account-sync.service
sudo install -m 0644 ops/systemd/crypto-testnet-account-sync.service /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/crypto-testnet-account-sync.service
sudo systemctl daemon-reload
sudo systemctl start crypto-testnet-account-sync.service
sudo systemctl status crypto-testnet-account-sync.service --no-pager
sudo journalctl -u crypto-testnet-account-sync.service --since '5 minutes ago' --no-pager
```

기존 원장이 hold/UNKNOWN이면 영구 HOLD로 종료한다. 계좌 reset/불일치 역시
account/account-hold.json에 기록하며 재시작으로 해제하지 않는다. 429/네트워크 오류는
Retry-After 및 backoff를 적용하고 마지막 정상 스냅샷을 보존한다. 키/환경 내용은
출력하거나 보고서에 붙이지 않는다. ACL은 write 권한으로 확대하지 않는다.

Dashboard 개발 파일 패치는 기본적으로 SHA/구조 확인만 수행한다.
적용하려면 사용자가 SSH에서 다음 명령을 실행한다. 기존 개발 파일 backup을 새 이름으로
보존하고 원본 SHA가 다르면 중단한다. 이 명령은 dashboard 배포/재시작을 하지 않는다.

```bash
sudo -u nuc-coder /srv/CryptoAutoTrading/releases/dev-m05/.venv/bin/python /srv/CryptoAutoTrading/releases/dev-m05/ops/dashboard/apply_refresh_patch.py
sudo -u nuc-coder /srv/CryptoAutoTrading/releases/dev-m05/.venv/bin/python /srv/CryptoAutoTrading/releases/dev-m05/ops/dashboard/apply_refresh_patch.py --apply
```

그 후 NUC Connector의 dashboard offline 테스트 및 새 release plan을 확인한다.
실제 서비스 계정이 crypto-read 그룹 또는 동등한 읽기 전용 ACL로 continuous DB,
WAL/SHM, health.json, latest-account.json을 읽을 수 있는지 운영자가 확인한다.
개발 API/UI 최종 변경을 검토하고 **새 release_hash**를 승인한 뒤 dashboard-only
배포를 수행한다. 이전에 나온 release_hash는 이 수정이 포함되지 않아 사용하지 않는다.

배포 후 2회 이상 30초 간격 잔고 timestamp 증가, 시장 데이터 시간 증가,
Collector/Observer heartbeat, 4H 마감 시 9개 COMMITTED 결정, 원장 불변,
주문 호출 0을 확인한다. 성공 후에만 systemctl enable로 재부팅 시작을 등록한다.
데이터가 stale이면 upstream/ACL/서비스를 확인하고 최신 상태로 오인하지 않는다.

## Rollback

account-sync를 disable --now하고 JSON/hold/로그를 증거로 보존한다. Collector/Observer/
Bridge rollback은 기존 배포 지침을 따른다. E01 원장과 검증 DB는 삭제/복원하지 않는다.
Dashboard는 Connector의 이전 정상 release rollback 절차로 되돌린다. 개발 파일은
보존한 backup과 차이를 검토한 뒤 복구하며 후속 사용자 수정 내용을 덮어쓰지 않는다.
LIMIT/GTC 및 소프트웨어 stop은 서버 중단 중 체결 포지션을 자동 보호하지 않는다.
자동 주문 활성화는 이 수정의 범위에 포함되지 않는다.
