# Ponytail 지침 도입 및 적용 전후 검증

상태: **PONYTAIL_INSTALLED_WITH_DISCOVERY_FLAG**.
승인 범위: A — Ponytail 지침 4파일, Python 3.14.7/frozen uv 환경, 적용 전후 회귀 검증.
작업 브랜치: `chore/ponytail-skills`.
기준 코드: DEV-M03 `1b1bf582f34a526d9204a084dc4573c79efa124e`.
기계 판독 결과: [ponytail-validation.json](ponytail-validation.json).

## 도입 파일과 출처

```text
.agents/skills/ponytail/SKILL.md
.agents/skills/ponytail/agents/openai.yaml
.agents/skills/ponytail/LICENSE
.agents/skills/ponytail/UPSTREAM.md
```

[공식 Ponytail Skill](https://github.com/DietrichGebert/ponytail/blob/9cc65d03aa2da1db7121b912d03596409ee340b8/skills/ponytail/SKILL.md),
package version 5.1.0 / MIT를 검토하고 commit을 고정했다.
원본 Skill에 프로젝트 안전 조건을 덧붙였고 MIT notice 및 원본 SHA-256을 보존했다.
`agents/openai.yaml`의 `allow_implicit_invocation: false`로 명시적 호출을 설정했다.
Ponytail의 Node Hook, plugin manifest, installer, statusline 및 추가 Skill은 설치하지 않았다.
애플리케이션 의존성이나 lockfile은 변경하지 않았다.

## 안전 조건

원본의 최소 변경 지침은 사용자 요구와 다음 검증 조건을 생략할 근거가 아니다.

- Read-only 유지, 주문/취소/출금/이체/Futures/Margin 및 W04 Formal Clock 추가 금지.
- Decimal/UTC, 스트림 검증, k.x 확정, bounded queue, commit-before-ACK 보존.
- 가격 신선도, 중복/CONFLICT, source/ingested_at, SQLite transaction/Backup API 보존.
- credentials/.env/계정 응답/DB/WAL/SHM/백업 보호. 테스트 삭제나 검증 완화 금지.
- 모의/CI/실제/미실행 결과 구분, 기존 데이터/사용자 변경/브랜치 보존.
- 한국어 요청에는 한국어로 답하고 요청한 상세 보고서를 제공.

확인한 checkout과 상위 경로에 AGENTS.md가 없었고 기준 M03에도 Risk Engine 구현/명세를 찾지 못했다.
따라서 별도 Risk Engine과의 충돌 검증 완료를 주장하지 않는다. 추후 실제 AGENTS.md/명세가 추가되면
그 규칙을 먼저 대조해야 한다. upstream AGENTS.md로 프로젝트 규칙을 덮어쓰지 않았다.

## 실제 환경과 회귀 결과

사용한 명령:

```bash
UV_CACHE_DIR=/workspace/.cache/uv UV_PYTHON_INSTALL_DIR=/workspace/.python uv python install 3.14.7 --no-bin
UV_CACHE_DIR=/workspace/.cache/uv UV_PYTHON_INSTALL_DIR=/workspace/.python uv sync --frozen --group dev
.venv/bin/python --version
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

프로젝트 전용 CPython 3.14.7과 uv의 frozen 의존성을 사용했다. 시스템 기본 Python을 바꾸지 않았다.

| 항목 | 적용 전 | 지침 추가·직접 읽기 적용 후 |
| --- | --- | --- |
| Python | 3.14.7 | 3.14.7 |
| pytest | 245 passed / 8 skipped / 0 failed | 245 passed / 8 skipped / 0 failed |
| Ruff | PASS | PASS |
| format | PASS, 42 Python files | PASS, 42 Python files |
| 고정 코드 탐색 질문 | 6개 모두 관련 경로/일치 행 확보 | 같은 정규화 결과 6/6 |
| 보호된 기존 파일 | 48개 SHA-256 기록 | 48개 모두 동일 |
| 애플리케이션·테스트·CI·lockfile 변경 | 0 | 0 |

실제 Binance 네트워크 integration 8개는 기본 pytest에서 skip되었다. Public/Private live 테스트는
추가 실행하지 않았으며 account credentials를 도입 검증에 사용하지 않았다.
원격 M03 문서에 남은 과거 239/244개 기록과 달리, 위 245개는 이번 기준 코드에서 직접 실행한 결과다.

## 코드 탐색 비교의 범위

비교한 6개 질문은 miniTicker Decimal/UTC, 확정/중복, reconnect/STALE,
commit-before-ACK, Gap/conflict/provenance, online backup/restore이다.
같은 SHA의 설치 전 스냅샷과 현재 코드에서 `rg`의 경로/행 결과를 정규화하여 비교했다.
여러 파일의 병렬 출력 순서가 달라질 수 있으므로 출력 순서를 정확도 차이로 세지 않았다.

| 질문 | 기존 관련 파일 | 전/후 일치 행 수 |
| --- | --- | --- |
| M02 가격 검증 | market_data/parser.py, models.py | 24 / 24 |
| M02 확정/중복 | market_data/parser.py, state.py | 7 / 7 |
| M02 재연결/신선도 | binance/websocket.py, market_data/health.py | 28 / 28 |
| M03 commit 후 ACK | persistence/writer.py, store.py | 8 / 8 |
| M03 Gap/출처 | persistence/recovery.py, store.py, records.py | 38 / 38 |
| M03 백업/복원 | persistence/repository.py | 14 / 14 |

이 결과는 기존 탐색 대상과 코드가 보존되었다는 증거다. 모델 답안의 semantic precision/recall,
실제 버그 수정 diff 크기, 비용 절감 또는 성능 향상은 측정하지 않았다.
읽기 전용 설치 작업에 임의의 애플리케이션 수정 과제를 추가하지 않았다.
Ponytail 지침을 직접 읽어 이번 검증에 적용했지만, 모델/새 세션을 통제한 별도 A/B 실험은 아니다.

## Skill 자동 발견 검증과 환경 제한

관리형 환경의 executor Skill 목록은 파일 설치 전/후 모두 빈 목록이었다.
이 채팅의 catalog에 새 Skill이 자동 등록되었다고 주장하지 않는다.

설치된 Codex CLI 0.159.0-alpha.3의 app-server/skills-list 검증도 시도했다.
이 검증은 모델 turn을 시작하지 않았고 Hook을 끈 테스트용 프로세스였다.
하지만 app-server가 보호된 CODEX_HOME의 `installation_id`를 만들려다 EROFS로 종료하여
`skills/list`에 도달하지 못했다. 따라서 native Skill discovery는
**BLOCKED_READ_ONLY_CODEX_HOME_INSTALLATION_ID**로 기록했다.
홈/인증정보/시스템 권한을 변경하거나 sandbox를 우회하지 않았다.

파일 설치 및 공식 디렉터리/정책 형식은 확인했고, Skill 본문을 직접 읽어 사용했다.
자동 발견과 명시적 호출 정책의 호스트 enforcement는 별도 로컬/새 세션에서 확인해야 한다.

## 사용 방법

이 변경이 포함된 checkout에서 새 Codex 세션을 열고 다음처럼 명시적으로 요청한다.

```text
$ponytail
DEV-M03의 commit 후 ACK 경로를 검토해줘. 코드는 수정하지 말고 근거와 관련 테스트를 알려줘.
```

현재 호스트가 Skill을 발견하지 못하면 다음을 사용한다.

```text
.agents/skills/ponytail/SKILL.md를 읽고 이번 작업에 적용해줘.
기존 안전 조건과 테스트를 보존하고, 필요한 최소 변경만 수행해줘.
```

원본 Skill은 활성화 후 세션 내 유지와 `stop ponytail`/`normal mode` 종료를 안내한다.
이 도입은 자동 실행 Hook이나 추가 권한을 부여하지 않는다.
현재 main에는 이 Skill이 없으므로 변경 브랜치 또는 병합된 코드에서 사용해야 한다.

## 다음 단계

로컬/새 Codex 세션에서 발견 및 명시적 호출을 확인하면 discovery flag를 증거와 함께 갱신한다.
Serena 설치·실행은 승인된 A 범위에 포함되지 않아 수행하지 않았다.
Serena MCP/Hook/전역 Codex 설정/인증정보를 변경하지 않았다.
클라우드 환경 draft에 명시적 Ponytail 호출/수동 읽기 및 discovery 제한 안내를 저장했다.
기존 설치 스크립트, 저장소 목록, 네트워크와 인증 요구사항은 보존했다.
저장 결과는 saved / requires_publish=true이다. 이는 적용·Publish 완료를 의미하지 않는다.
환경 설정에서 변경사항을 검토·저장한 뒤 Publish해야 다음 환경에 반영된다.
새 환경 복원은 아직 검증하지 않았다.
