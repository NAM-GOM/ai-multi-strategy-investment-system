# DEV-M05 NUC 배포·DRY_RUN·Rollback 지침

**이 문서는 배포 준비 산출물이다. Codex는 아래 서버 명령을 실행하지 않았다.**
NUC Connector의 배포 권한은 비활성화되어 있다. 코드 검토와 별도 배포 승인 후
사용자가 `gomi-mini`에 SSH로 접속해 실행한다. 자동 주문·allocation·실제 Testnet
주문은 이 절차에 포함되지 않는다. 최종 상태는 실환경 TEST-02–07 완료 전 HOLD다.

## 1. 기존 자료 보존과 사전 확인

확인 대상은 Ubuntu 24.04, Python 3.14.7, uv / uv.lock이다. 현재 서비스·시계·디스크를
확인한다. 아래 명령은 키나 환경변수 내용을 출력하지 않는다.

```bash
hostname
lsb_release -ds
uv --version
timedatectl status
df -h /srv/CryptoAutoTrading /var/lib/CryptoAutoTrading
systemctl list-units --all 'crypto-*'
pgrep -f trading_system || true
sudo stat -c '%U %G %a %n' /home/gomi/.config/cryptoautotrading/testnet.env
sudo stat -c '%U %G %a %n' /var/lib/CryptoAutoTrading/state/testnet-e01/testnet_execution.sqlite
```

기존 프로세스의 PID와 관리 방식은 로컬에서 확인한다. 24H 작업을 새 DB에 연결하거나
기존 release를 수정하지 않는다. 같은 새 DB를 쓰는 legacy 작업/cron/tmux가 있으면
운영자가 종료 순서와 재시작 영향을 검토한다. 새 서비스 WriterLease를 지우지 않는다.

다음 경로는 보호 대상이다.

- `/srv/CryptoAutoTrading/releases/dev-m04`
- `/srv/CryptoAutoTrading/releases/dev-e01`
- `/var/lib/CryptoAutoTrading/state/close-validation-01/`
- `/var/lib/CryptoAutoTrading/state/testnet-e01/testnet_execution.sqlite` 및 WAL/SHM

기존 E01 writer가 실행 중이면 sqlite 파일을 `cp`로 복사하지 않는다. SQLite Backup
API로 새 백업을 생성한다. DB나 WAL/SHM을 삭제·덮어쓰기·자동 복원하지 않는다.
아래 예시는 백업 디렉터리와 파일이 이미 존재하면 중단한다. 실행용 Python 경로를
먼저 로컬에서 확인한다. root 소유 백업은 채팅이나 GitHub로 업로드하지 않는다.

```bash
backup_dir="/var/backups/CryptoAutoTrading/m05-$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -d -m 0700 /var/backups/CryptoAutoTrading
sudo mkdir -m 0700 "$backup_dir"
sudo /srv/CryptoAutoTrading/releases/dev-e01/.venv/bin/python - "$backup_dir" <<'PY'
import sqlite3,sys
from pathlib import Path
source=Path('/var/lib/CryptoAutoTrading/state/testnet-e01/testnet_execution.sqlite')
target=Path(sys.argv[1])/'testnet_execution.sqlite'
if not source.is_file() or target.exists():
    raise SystemExit('Backup source missing or destination already exists')
a=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
a.execute('PRAGMA query_only=ON')
b=sqlite3.connect(target)
try:
    a.backup(b)
    if b.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
        raise SystemExit('Backup integrity HOLD')
    print({'orders':b.execute('SELECT count(*) FROM exchange_orders').fetchone()[0],
           'fills':b.execute('SELECT count(*) FROM executions').fetchone()[0]})
finally:
    b.close();a.close()
PY
sudo chmod 0600 "$backup_dir/testnet_execution.sqlite"
```

24H 원본은 별도로 기존 운영 Backup API 절차를 따르거나 읽기 전용으로 보존한다.
새 continuous DB에 원본을 restore/merge하지 않는다. 사용자 제공 수동 거래
`1507111`, `0.00009000 BTC`는 이후 read-only reconciliation에서 확인할 기준이며,
이번 코드 작업에서 DB를 직접 읽어 재확인한 사실은 아니다.

## 2. 새 release 준비 — 기존 브랜치/릴리스 덮어쓰기 금지

검토한 M05 PR의 정확한 SHA를 사용한다. 아래 SHA는 **검토한 PR HEAD로 직접 지정**한다.
기존 경로가 있으면 중단하고 별도 release 이름과 unit 경로를 검토한다. 저장소 기준
브랜치는 M04이며 main 병합은 별도 검토 대상이다.

```bash
m05_sha='REPLACE_WITH_REVIEWED_M05_COMMIT_SHA'
case "$m05_sha" in REPLACE_*|'') exit 1 ;; esac
sudo test ! -e /srv/CryptoAutoTrading/releases/dev-m05
sudo install -d -o gomi -g gomi -m 0755 /srv/CryptoAutoTrading/releases/dev-m05
sudo -u gomi git clone --no-checkout https://github.com/NAM-GOM/ai-multi-strategy-investment-system.git /srv/CryptoAutoTrading/releases/dev-m05
sudo -u gomi git -C /srv/CryptoAutoTrading/releases/dev-m05 checkout --detach "$m05_sha"
cd /srv/CryptoAutoTrading/releases/dev-m05
git rev-parse HEAD
uv python install 3.14.7
uv sync --frozen --group dev
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen ruff format --check .
scripts/m05-preflight.sh
python scripts/m05-verify-units.py
bash -n scripts/m05-runtime.sh scripts/m05-preflight.sh
```

`uv` 관리 Python/venv가 `/home/gomi`를 참조하면 ProtectHome 때문에 서비스에서 실행할 수
없다. 서비스 사용자도 실행 가능한 interpreter를 release의 `/opt` 기반 읽기 전용 경로
등에 설치하고 `uv sync --python /opt/.../bin/python3.14`로 venv를 재생성한다.
서비스로 테스트하기 전에 `readlink -f .venv/bin/python`과 `namei -l`로 경로를 확인한다.
release는 준비가 끝난 후 root 소유 읽기 전용으로 고정하며 서비스 사용자는 수정할 수
없어야 한다. 필요 시 `sudo chown -R root:root /srv/CryptoAutoTrading/releases/dev-m05`를
실행하고 디렉터리 traverse와 파일 read/스크립트 execute 권한을 확인한다.

## 3. 역할 계정·상태 디렉터리·읽기 전용 ACL

배포 승인 후 root 권한으로 한 번만 실행한다. 기존 동명 계정은 목적/그룹을 확인하고
재사용할 수 있는지 운영자가 검토한다. 사용자 계정에 sudo를 부여하지 않는다.

```bash
sudo groupadd --system crypto-read
sudo useradd --system --gid crypto-read --home-dir /nonexistent --shell /usr/sbin/nologin crypto-collector
sudo useradd --system --gid crypto-read --home-dir /nonexistent --shell /usr/sbin/nologin crypto-observer
sudo useradd --system --gid crypto-read --home-dir /nonexistent --shell /usr/sbin/nologin crypto-bridge
sudo install -d -o root -g crypto-read -m 0750 /var/lib/CryptoAutoTrading/state/continuous-01
sudo install -d -o crypto-collector -g crypto-read -m 0750 /var/lib/CryptoAutoTrading/state/continuous-01/market
sudo install -d -o crypto-observer -g crypto-read -m 0750 /var/lib/CryptoAutoTrading/state/continuous-01/observer
sudo install -d -o crypto-bridge -g crypto-read -m 0750 /var/lib/CryptoAutoTrading/state/continuous-01/bridge
```

기존 부모 `/var/lib/CryptoAutoTrading`와 `state`가 0700이면 crypto-read 그룹에 필요한
traverse만 ACL로 부여한다. 기존 owner/mode를 통째로 변경하지 않는다. `setfacl`이
없으면 Ubuntu `acl` 패키지를 준비한다. 다음 ACL은 **읽기/탐색만** 부여한다.

```bash
sudo setfacl -m g:crypto-read:--x /var/lib/CryptoAutoTrading /var/lib/CryptoAutoTrading/state
sudo setfacl -m u:crypto-bridge:r-x /var/lib/CryptoAutoTrading/state/testnet-e01
sudo setfacl -m d:u:crypto-bridge:r-x /var/lib/CryptoAutoTrading/state/testnet-e01
sudo find /var/lib/CryptoAutoTrading/state/testnet-e01 -maxdepth 1 -type f -name 'testnet_execution.sqlite*' -exec setfacl -m u:crypto-bridge:r-- {} +
```

기존 E01 writer가 새 sidecar를 만들 때 default ACL이 유지되는지 확인한다. Bridge에
write ACL을 주거나 기존 E01 DB owner를 바꾸지 않는다. SQLite 버전이 read-only WAL
조회에 필요한 sidecar를 만들려고 하며 실패하면 운영자가 existing writer로 sidecar를
준비하고 읽기 전용 ACL을 점검한다. Bridge 권한을 쓰기로 확장해 해결하지 않는다.

정적 권한 검증:

```bash
sudo -u crypto-collector test -w /var/lib/CryptoAutoTrading/state/continuous-01/market
sudo -u crypto-collector test ! -w /var/lib/CryptoAutoTrading/state/continuous-01/observer
sudo -u crypto-observer test -w /var/lib/CryptoAutoTrading/state/continuous-01/observer
sudo -u crypto-observer test ! -w /var/lib/CryptoAutoTrading/state/continuous-01/market
sudo -u crypto-bridge test -r /var/lib/CryptoAutoTrading/state/testnet-e01/testnet_execution.sqlite
sudo -u crypto-bridge test ! -w /var/lib/CryptoAutoTrading/state/testnet-e01/testnet_execution.sqlite
sudo -u crypto-bridge test ! -w /var/lib/CryptoAutoTrading/state/testnet-e01
sudo -u crypto-collector test ! -r /home/gomi/.config/cryptoautotrading/testnet.env
sudo -u crypto-observer test ! -r /home/gomi/.config/cryptoautotrading/testnet.env
sudo -u crypto-bridge /srv/CryptoAutoTrading/releases/dev-m05/scripts/m05-preflight.sh --host-check
sudo -u crypto-collector /srv/CryptoAutoTrading/releases/dev-m05/scripts/m05-preflight.sh
sudo -u crypto-observer /srv/CryptoAutoTrading/releases/dev-m05/scripts/m05-preflight.sh
```

## 4. 키와 주문 비활성화

키는 기존 `/home/gomi/.config/cryptoautotrading/testnet.env`에만 보존한다. `cat`,
`printenv`, `set -x`, `systemctl show ... Environment` 또는 채팅 붙여넣기를 사용하지
않는다. 로컬 `sudoedit`으로 아래 두 값이 정확히 OFF인지 확인한다. Collector와
Observer에 EnvironmentFile을 추가하지 않는다. Bridge 서비스는 systemd가 파일을
읽어 넘기므로 서비스 계정의 home 파일 접근 권한을 확대할 필요가 없다.

```text
BINANCE_TESTNET_TRADING_ENABLED=OFF
BINANCE_TESTNET_AUTOMATED_ENABLED=OFF
```

systemd EnvironmentFile의 값이 unit Environment를 덮어쓸 수 있다. 코드에서도 OFF를
검사하므로 잘못된 unlock은 종료 78/HOLD로 차단된다. 실제 Testnet 계좌·주문을 바꾸는
POST/DELETE/자동 활성화 옵션은 Runtime에 없다. 두 값을 바꿔도 trader로 전환되지 않는다.

## 5. 승인된 서비스 설치와 startup — TEST-02/03

기존 동명 unit이 있으면 덮어쓰지 않고 검토한다. journald의 기존 정책을 확인하고
운영 보존 기간/용량을 정한다. persistent journald 설정 변경은 사용자 운영 범위에서
수행한다. 역할별 JSON 로그는 10MB 파일 6개까지 보존한다.

```bash
sudo test ! -e /etc/systemd/system/crypto-market-collector.service
sudo test ! -e /etc/systemd/system/crypto-strategy-observer.service
sudo test ! -e /etc/systemd/system/crypto-testnet-bridge.service
sudo install -m 0644 ops/systemd/crypto-market-collector.service /etc/systemd/system/
sudo install -m 0644 ops/systemd/crypto-strategy-observer.service /etc/systemd/system/
sudo install -m 0644 ops/systemd/crypto-testnet-bridge.service /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/crypto-market-collector.service /etc/systemd/system/crypto-strategy-observer.service /etc/systemd/system/crypto-testnet-bridge.service
sudo systemctl daemon-reload
sudo systemctl start crypto-market-collector.service
sudo systemctl start crypto-strategy-observer.service
sudo systemctl start crypto-testnet-bridge.service
sudo systemctl status crypto-market-collector.service crypto-strategy-observer.service crypto-testnet-bridge.service --no-pager
sudo journalctl -u crypto-market-collector.service -u crypto-strategy-observer.service -u crypto-testnet-bridge.service --since '15 minutes ago' --no-pager
sudo -u crypto-bridge scripts/m05-runtime.sh status
```

Collector bootstrap 중 Observer DATA_HOLD는 정상이다. 3개 종목의 부족 데이터·gap이
해소되기 전 평가를 강행하지 않는다. `STARTING`, `HOLD`, `READY`, `STOPPED`, `FAILED`를
구분한다. Bridge `READ_ONLY_TESTNET_CONNECTED`는 Testnet 인증·잔고·공개 WS bookTicker와
E01 reconciliation을 **임시 복사본에서만** 수행한다. POST order/test는 호출하지 않는다.
REST bookTicker를 새로 구현하지 않고 기존 E01 WS quote를 재사용한다.

동일 CLI를 두 번 실행해 중복 서비스 lease 차단을 확인할 수 있다. systemd 실행 중인
역할과 동일 계정으로 `scripts/m05-runtime.sh observer --smoke-seconds 5`를 실행하면
exit 78이어야 하고 기존 heartbeat를 바꾸지 않아야 한다. 정상 smoke 종료는 자동
재시작하지 않는다. 실패는 30초 간격 최대 3회/600초, 영구 오류는 78로 중단한다.

## 6. 실제 4H 신호와 Preview — TEST-04/05

봉 마감(KST 01/05/09/13/17/21시) 전 서비스를 READY로 유지한다. 마감 예정 시각 자체를
검증 결과로 쓰지 않는다. `latest-preview.json`과 journald에서 실제 COMMITTED 봉을
확인한다. 기존 초기 backfill은 LIVE가 아니며 보고서에 자동 주문 통과로 쓰지 않는다.

```bash
sudo -u crypto-bridge scripts/m05-runtime.sh status
sudo -u crypto-bridge /srv/CryptoAutoTrading/releases/dev-m05/.venv/bin/python - <<'PY'
import json
from pathlib import Path
p=Path('/var/lib/CryptoAutoTrading/state/continuous-01/bridge/latest-preview.json')
r=json.loads(p.read_text())
print({'mode':r['mode'],'order_calls':r['order_calls'],
       'execution_enabled':r['execution_enabled'],'validations':r['validations'],
       'signals':r['signals'],'manual_baseline':r['manual_baseline']})
PY
```

실제 신규 봉마다 WS_LIVE 3개, LIVE_OBSERVATION/COMMITTED 결정 9개, T1 정책 3개와
Shadow 6개, Frozen/input/decision hash 검증, E01 결과를 저장한다. NO_ACTION이라도
9개 신호 검증은 가능하다. T1 allocation이 아직 없으면 후보는
STRATEGY_ALLOCATION_REQUIRED여야 한다. 가상 자본을 실제 계좌에 할당하지 않는다.
실제 T1이 없으면 가짜 LIVE를 만들거나 기존 수동 매수를 소급 귀속시키지 않는다.

Preview cursor와 실제 Router checkpoint는 별개다. 배포 전 Backup API snapshot의
signal_receipts/router_checkpoints/strategy_allocations/원장 논리 내용을 비교한다.
독립 E01 작업이 concurrently journal을 변경했다면 그 변경을 별도로 설명하고
M05의 변경으로 오인하지 않는다. 기존 수동 BTC 매수는 MANUAL_BASELINE으로만 보고한다.

## 7. 정상 종료·장애·재부팅 — TEST-06/07

실제 주문 OFF 상태에서만 다음을 검증한다. DB 손상, 429 유발 트래픽, E01 원장 잠금,
network firewall 변경은 운영 원장에 주입하지 않는다. 이 사례는 별도 임시 DB와
Mock Testnet 테스트로 검증하며 실환경 미수행으로 표시한다. Collector 실패만 서비스
중단으로 주입하고 Observer/Bridge가 HOLD가 되는지 확인한다.

```bash
sudo systemctl stop crypto-market-collector.service
sudo -u crypto-bridge scripts/m05-runtime.sh status
# 최소 heartbeat 허용 시간 30초 후 다시 상태를 확인한다.
sudo systemctl start crypto-market-collector.service
sudo systemctl stop crypto-testnet-bridge.service crypto-strategy-observer.service
sudo systemctl start crypto-strategy-observer.service crypto-testnet-bridge.service
sudo -u crypto-bridge scripts/m05-runtime.sh status
```

Graceful Shutdown 후 새 Observer run, 체크포인트 연속성, gap 복구, DB integrity,
9개 batch 수와 유일성을 확인한다. downtime 봉은 backfill/stale로 차단되어야 한다.
60초 실행 창을 지난 신호는 주문 가능 신호로 재실행하지 않는다. 비정상 종료 smoke가
필요하면 운영자가 시각/손실 창을 정한 후 해당 role 프로세스만 SIGKILL하고 30초
재시작·WriterLease 해제·commit 원자성·중복 방지를 확인한다.

재부팅 복구는 별도 운영 일정 승인 후 아래처럼 enable하고 재부팅한다. 재부팅 명령은
이 문서에 포함된 배포 승인만으로 자동 실행하지 않는다.

```bash
sudo systemctl enable crypto-market-collector.service crypto-strategy-observer.service crypto-testnet-bridge.service
# 사용자가 정한 재부팅 일정에 reboot 수행 후:
sudo systemctl status crypto-market-collector.service crypto-strategy-observer.service crypto-testnet-bridge.service --no-pager
sudo -u crypto-bridge /srv/CryptoAutoTrading/releases/dev-m05/scripts/m05-runtime.sh status
```

재부팅 전 heartbeat의 boot_id를 그대로 받아들이지 않는지, 새 프로세스에서 원장
내역·수동 매수·실제 receipt/checkpoint가 보존되는지 확인한다. TEST-02–07의 실제
결과·시각·run ID·decision hash·계정 reconciliation을 validation 문서에 기록한 후
별도 코드 검토로 최종 PASS/PASS_WITH_FLAGS/HOLD를 판정한다.

## 8. Rollback — 원장과 데이터 삭제 금지

M05 문제 시 Bridge → Observer → Collector 순서로 정상 종료하고 enable을 해제한다.
서비스 설치 전 보호한 기존 release는 변경하지 않았으므로 파일 교체 복원이 필요 없다.
새 DB/로그/Preview cursor 및 기존 Testnet 원장은 증거로 그대로 보존한다.

```bash
sudo systemctl disable --now crypto-testnet-bridge.service
sudo systemctl disable --now crypto-strategy-observer.service
sudo systemctl disable --now crypto-market-collector.service
sudo journalctl -u crypto-testnet-bridge.service -u crypto-strategy-observer.service -u crypto-market-collector.service --since today --no-pager
```

기존 E01 DB를 백업으로 덮어쓰지 않는다. 실제 주문 UNKNOWN/체결/취소 상태를 잃을 수
있다. DB 문제는 보존된 별도 snapshot에서 비교하고 복원은 추가 검토로 진행한다.
기존 M04 24H 작업을 재개하려면 사용자가 기존 검증 절차와 W04 시각을 검토한다.
계정/ACL rollback은 새 서비스가 중단된 뒤 운영자가 사전 권한 기록과 비교해 필요한
정확한 ACL 항목만 제거한다. `rm -rf`, SQLite 초기화, 기존 owner 변경은 하지 않는다.

Testnet 포지션이 존재할 때 서비스 중단은 소프트웨어 Stop도 중단한다. LIMIT/GTC와
소프트웨어 ATR Stop은 서버 중단 중 자동 보호를 보장하지 않는다. 이 위험과 잔여
주문을 수동 확인한 뒤 DRY_RUN 종료를 판단해야 한다. TEST-08 활성화 및 TEST-09 신규
T1 소액 주문 1건은 각각 별도 승인과 검증을 받아야 하며, 본 절차에서는 실행하지 않는다.

계정 reset·원장 불일치·입력 정합성 오류는 `bridge/preview-hold.json`에도 영구 기록된다.
프로세스/서버 재시작으로 해제되지 않는다. 원인과 실제 E01 원장을 별도로 확인한 뒤,
운영자가 해제를 승인한 경우에만 이 **Preview 전용** 파일을 날짜가 붙은 증거 파일로
이동해 보존하고 서비스를 다시 시작한다. 실제 E01 hold/kill과 allocation에는 영향을
주지 않으며 자동 주문을 승인하는 절차가 아니다. 보존 없이 삭제해 오류를 우회하지 않는다.
