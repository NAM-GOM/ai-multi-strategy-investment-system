# DEV-E02 NUC 배포·롤백 가이드

**현재 배포 미승인·미실행. 자동 주문 OFF.** 아래는 검토용 절차이며 일괄
복사하여 실행하는 설치 스크립트가 아니다. read-only preflight 결과를 먼저
보고한 뒤 실제 배포/권한 변경과 ON을 각각 승인받는다.

## 승인할 배포 계획

1. PR head/CI PASS, pinned M05 base, Frozen hash, 실제 M05 증거와 NUC 경로를
   확인한다. 신규 release `/srv/CryptoAutoTrading/releases/dev-e02`를 준비하고
   Python3.14.7/locked 의존성을 배포 단계에서 설치한다. 기존 M05 release와
   unit을 덮어쓰지 않는다. 시작 스크립트는 설치/네트워크 의존성 갱신을 하지 않는다.
2. 원장의 현재 integrity/세션/주문/권한, 관련 unit, open FD를 기록한다.
   SQLite Backup API로 독립된 검토용 백업을 만들고 복사본 integrity를 확인한다.
   실계좌/운영 M03/M04 DB, close-validation-01은 접근/수정 대상에서 제외한다.
3. 기존 E01 writer/수동 CLI를 모두 정지한다. 단순 advisory lock만으로는
   그 CLI를 배제하지 못한다. 열린 writable FD가 남으면 이관하지 않는다.
4. `crypto-executor` 전용 비특권 사용자·그룹과 crypto-read 보조 그룹을 준비한다.
   **원본 E01 DB 내용/이름/스키마는 보존**하고 owner/mode만 명시 승인 후 이관한다:
   journal parent는 executor:crypto-read 2750, DB/기존 wal·shm은 executor:crypto-read
   0640. setgid parent로 새 sidecar도 bridge가 읽을 수 있게 한다. 기존 ACL이
   추가 writer를 허용하는지 확인하고 제거 범위를 승인한다. 재귀 chown/chmod 금지.
   원장 parent 외의 M03/M04/Bridge 권한은 바꾸지 않는다.
5. E02 control dir는 별도로 executor:executor 0750; `/etc/CryptoAutoTrading`과
   acceptance는 root 소유, group/other 쓰기 금지다. acceptance 템플릿은
   NOT_TESTED 유지; 실제 M05 증거 확인 후만 PASS로 기록한다.
6. dedicated Testnet env는 `/etc/CryptoAutoTrading/e02-testnet.env`, root0600,
   코드/로그/GitHub와 분리. 기존 M05 env는 수정하지 않는다. 두 legacy unlock
   및 E02 capability를 초기 OFF로 설치한다. populated env를 출력하지 않는다.
7. 새 unit만 설치한다. `bash -n` 및 `systemd-analyze verify` 후 daemon-reload,
   새 E02 서비스 시작을 승인 범위에서 수행한다. 새 서비스는 기존 서비스에
   Wants/After만 가지며 기존 M05 시작/정지 정책을 대신하지 않는다. 부팅
   자동 시작 enable은 OFF 상태·재시작 검증 후 별도 승인 범위에서 한다.
8. journal/health OFF, 실제 GET, old B/C 보존, 원장 writer 단일성, bridge 읽기,
   재시작 OFF/원장 복구를 확인하고 결과를 보고한다. 아직 ON/실제 주문하지 않는다.
9. allocation·ABC·보호 예산·M05 acceptance 및 최종 실제 preflight를 검토한 후
   별도 사용자 승인으로 capability 준비/ON. 재시작은 언제나 OFF다.

서비스 sandbox는 original E01 journal과 별도 E02 control만 쓰기 허용한다.
Collector/Observer DB는 read-only다. Linux 소유권 검사는 데이터 쓰기 이전과
최종 mutation 전에 다시 확인한다. Linux CI의 unit syntax PASS는 실제 UID,
ACL, systemd boot, 네트워크, credentials, 서비스 권한 PASS가 아니다.

## Rollback

1. OFF/KILL로 신규 송신을 차단하고 상태/실제 계좌를 조회한다. 기존 송신
   결과가 UNKNOWN이면 먼저 동일 client ID GET 복구를 끝내고 운영 HOLD를 유지한다.
2. T1 pending LIMIT 및 보유 수량/보호 상태를 확인한다. 단순 서비스 정지가
   포지션 청산이 아니므로 잔여 노출의 처리 계획을 승인받는다.
3. E02 서비스를 정지/disable하고 unit/명령/log/원장을 백업 보존한다. M05
   Collector/Observer/READ_ONLY Bridge와 그 원래 release는 그대로 유지한다.
4. **자동 주문 후 과거 SQLite 백업을 원본으로 복원하지 않는다.** 실제 거래와
   원장이 어긋나고 중복 주문 위험이 있다. 최신 원장을 보존한 채 E02를 OFF로
   두거나, 기존 CLI로 복귀해야 할 경우 모든 writer 정지 후 명시적인 권한
   역이관과 계좌·원장 정합성 검토를 한다. owner/mode는 기록한 범위만 복구한다.
5. 주문 전 롤백도 source/DB를 삭제하지 않는다. 증거 보존과 실제 상태 보고를
   우선하며 자동 reset/force init, M05 overwrite, Frozen 코드 변경을 하지 않는다.
