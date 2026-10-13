# 범용 Codex Cloud Setup 안내

## 즉시 재사용 가능한 구성

이 PR은 project-local 구성만 제공한다. 사용자 홈과 실제 Cloud 환경 설정은 수정하지 않았다.
적용은 PR 검토·수동 병합 후 새 task에서 수행한다. 자동 병합하지 않는다.
다른 프로젝트에는 기존 AGENTS를 backup하고 충돌 검토 후 내용을 병합한다.
소프트웨어 프로젝트별 safety/mandatory checks를 그대로 유지한다.

- AGENTS.md: 기존 규칙 + portable appendix.
- .agents/skills/codex-efficient-workflow/: 명시 요청용 자체 Skill.
- tools/codex-optimization/available-skills/: inactive reviewed Skill 3개와 license.
- sources.lock.json: 7개 upstream commit, 상태, staged file hash.
- checkpoint.template.md: 민감정보 없는 revision-aware handoff.
- verify_setup.py/cloud-setup.sh: offline/read-only 무결성 검사, 전역 쓰기 없음.

Cloud 환경 편집 화면의 Setup Script에는 repository root 기준 다음을 추가할 수 있다:

```bash
bash tools/codex-optimization/cloud-setup.sh
```

이 script는 이미 checkout된 파일을 확인할 뿐, proxy/MCP/worker/plugin을 설치하지 않는다.
기존 Setup Script를 대체하지 말고 필요한 project checks 다음에 병합한다.
실제 화면의 기존 script 값은 이번 task에서 조회하지 못했으므로,
사용자가 기존 값을 백업한 뒤 변경·저장·재게시해야 한다.
재게시 메뉴를 확인할 수 없으므로 UI의 구체적인 버튼 이름은 단정하지 않는다.
저장 후 새 task를 시작하고 setup log와 실제 Skill discovery를 확인한다.
지원되지 않는 UI/host라면 지침을 직접 요청해 읽도록 하고 자동 활성화라고 표시하지 않는다.

## Shell 네트워크 복구

현재 unrestricted/enforced policy와 실제 proxy 실패가 동시에 관찰된다.
환경 설정의 HTTP destination 허용 및 proxy runtime readiness를 점검하고
지원되는 환경 재시작/재게시 절차를 사용한다.
직접 route, proxy 해제, TLS 검증 해제, 임의 권한 확대를 사용하지 않는다.

새 환경에서 원인 수정 후만 다음을 재확인한다:

```bash
git ls-remote https://github.com/NAM-GOM/ai-multi-strategy-investment-system.git HEAD
```

GitHub connector 성공은 이 shell 명령 성공을 대체하지 않는다.
네트워크가 다시 실패하면 동일 명령 반복 대신 환경 상태와 실제 오류를 기록한다.

## Serena: 별도 승인/설정 후 검증 경로

공식 README의 설치 명령은 uv tool install -p 3.13 serena-agent다.
재현성용으로 공식 source-execution 방식에 검토 SHA를 추가할 수 있다:

```bash
uvx -p 3.13 --from git+https://github.com/oraios/serena@737ccc29a72aec5e6a2404d1caef1d0c0d9fb663 serena --help
```

current metadata는 Python >=3.11,<3.15이나 권장 실행 환경은 3.13이다.
uv cache/tool/python 설치 경로는 writable project work/로 지정한다.
공식 source execution도 dependency download/build를 포함하므로
새 버전과 LSP 다운로드를 검토해야 한다. latest로 자동 업그레이드하지 않는다.
GPT/Cloud host의 MCP 연결이 실제 제공될 때만 project-local 설정을 작성한다.
Codex context와 project를 지정하고 read-only mode/no-memories를 고려한다.
tools list --all 및 실제 MCP tools/list로 노출 도구를 확인하여
symbol overview/search/references에 필요한 최소 집합만 남긴다.
현재 .codex/config.toml 예시는 배포하지 않았다. host가 runtime MCP 등록을
지원하는지 아직 확인되지 않아 미검증 설정을 자동 적용하지 않기 위해서다.
설치/stdio protocol 성공, fixture symbol accuracy, host 호출 성공을 각각 기록한다.

## Headroom: 로컬 기능부터

격리 environment에 검토한 headroom-ai==0.40.0 core를 먼저 설치한다.
[all] 또는 proxy extras를 자동 설치하지 않는다.
테스트는 benchmark의 synthetic error/cause/recovery fixture만 사용한다.
byte size와 token counter estimate, 실제 provider billed tokens를 구분한다.
압축 출력에서 핵심 정보, 누락 unique error, recovery facts를 검사한다.
Cloud proxy endpoint를 실제 확인하기 전 wrap/mcp install을 실행하지 않는다.
프로젝트 프롬프트/키/API routing 변경은 별도 승인·endpoint 검토가 필요하다.

## Optional Skill 선택

staged Skill은 모델 효과가 검증되지 않아 기본 비활성이다.
명시적으로 필요한 Skill 하나만 읽거나 아래처럼 project discovery 경로로
복사할 수 있다. 같은 이름이 이미 있으면 덮어쓰지 않는다.

```bash
test ! -e .agents/skills/ponytail
cp -R tools/codex-optimization/available-skills/ponytail .agents/skills/
```

기존 파일이 있으면 이 두 명령을 별도 무조건 실행하지 않는다.
설치 여부를 확인하고 기존 내용·source revision을 비교한 다음 중복을 해결한다.
Ponytail의 자동 trigger는 범용적이므로 선택적 사용 목적에 맞게 검토한다.
현재 task 중 파일 복사만으로 host 재로딩 성공을 주장하지 않는다.
Kit의 Windows helper/profiles는 Linux에 실행/복사하지 않는다.
Superpowers의 전체 bootstrap/brainstorm/subagent는 기본 설치 대상이 아니다.
Codex Token Optimizer는 license/배포 허가 확보 전 vendoring하지 않는다.

## Claude-Mem 보류 해제 조건

사용자가 observer의 목적지·전송 데이터·quota/유료 서비스·보존 정책을 승인하고,
전역 설정을 수정할 수 있는 지원 환경과 native hooks/MCP 경로가 필요하다.
DO_NOT_TRACK=1, CLAUDE_MEM_TELEMETRY=0,
CLAUDE_MEM_TELEMETRY_ERRORS=0, CLAUDE_MEM_ONLINE_OPTIN=false 등
공식 opt-out을 검토하되, 이를 offline observer 보장으로 해석하지 않는다.
installer는 worker/Bun을 시작하고 ~/.codex 및 다른 설정을 수정할 수 있다.
승인 전에는 npx installer, worker, provider를 실행하지 않는다.
설치 후 synthetic data만으로 first task store / second task recall을 시험한다.
DB file survival과 실제 새 Cloud task 기억 정확도는 별개의 합격 조건이다.
이 task에는 두 검증 모두 없다.

## 롤백

본 구성은 전역 설정을 변경하지 않아 global rollback이 없다.
추가한 opt-in Skill과 portable appendix를 PR diff 기준으로 제거할 수 있다.
optional Skill을 별도 복사했다면 그 복사본만 제거한다.
기존 AGENTS 전체를 지우거나 기존 project instruction을 대체하지 않는다.
staged file hash가 바뀌면 verify_setup은 실패한다. 합법적 변경이면
upstream revision·license를 다시 검토한 뒤 lock을 갱신한다.

## 사용자가 수행할 항목

1. PR 검토·수동 병합 여부 결정.
2. Cloud proxy 문제 해결 후 supported setup workflow로 재시작/재게시.
3. 기존 Setup Script backup 후 offline checker를 선택적으로 추가.
4. 새 task에서 project Skill discovery 확인.
5. Serena/Headroom 설치·실제 host MCP/압축 비교를 재검증.
6. license 확인 및 Claude-Mem 데이터 전송 승인 여부 결정.
