# CODEX-OPT-01 설치·검증 보고서

조사일: 2026-10-13 (Asia/Seoul). 대상: NAM-GOM/ai-multi-strategy-investment-system.
브랜치: codex/code-opt-01-cloud-optimization.
분류: STANDARD 설정/문서 작업, 자격 증명·외부 전송 검토에는 STRICT 기준 적용.
애플리케이션 코드, 기존 테스트, 운영 데이터, 배포 설정은 변경하지 않았다.

## 결론

7개 저장소를 조사했다. 공개 README, 공식 설치 자료, 라이선스,
실행 요건, 관련 Hook/설정 변경 코드를 검토했다.
3개 도구의 일부 Skill 파일을 라이선스와 함께 프로젝트에 보존했다.
**플러그인 전체 설치 또는 현재 Cloud 세션 자동 활성화는 아니다.**
Serena/Headroom 패키지 설치는 실제 시도했으나 셸 네트워크가 실패했다.
Codex Token Optimizer 재배포와 Claude-Mem 활성화는 보류했다.

## 환경 확인

| 항목 | 관찰 |
|---|---|
| OS | Linux x86_64, kernel 6.18.44 |
| Python | 기본 3.12.14; 프로젝트용 3.14.7도 설치되어 있음 |
| Node / Codex CLI | v24.19.0 / 0.159.0-alpha.3 |
| 패키지 관리자 | uv, pip, npm; git, curl, rg 사용 가능 |
| 저장소 상태 | 최초 로컬 work, 59df61d, 변경 없음; GitHub main은 9024b4b |
| 기존 지침 | GitHub root AGENTS.md의 Universal Codex Efficiency Rules 전체 보존 |
| 기존 Skill | 프로젝트 내 추가 Skill 없음; 사용자 전역 .agents/.codex 읽기 전용 |
| MCP | codex mcp list: No MCP servers configured |
| Setup/Install Script | 저장소에 기존 setup 파일 없음; Cloud UI의 기존 Setup Script 값은 조회 불가 |
| 네트워크 정책 | enforced/unrestricted HTTP; VPN false, 직접 TCP grants 없음 |
| 실제 네트워크 | 셸 Git: proxy:8080 연결 실패; PyPI: tunnel/tcp open Operation not permitted |
| 허용된 대안 | 연결된 GitHub 도구로 공개 소스 읽기 및 요청된 브랜치/PR 작성 |
| 환경 변수 | HTTP_PROXY/HTTPS_PROXY/CODEX_HOME 존재 여부만 확인; 값 출력 안 함 |
| 외부 모델 키 | OPENAI/ANTHROPIC/GEMINI_API_KEY 미설정; runtime secret/identity binding 없음 |
| 프로젝트 요구 | Python >=3.14,<3.15; 캐시로 frozen dev 의존성 복원 성공 |

desired policy와 실제 연결 가능 상태를 구별했다. 프록시를 우회하거나 권한을 확대하지 않았다.
CODEX_HOME 위치를 변경하거나 전역 설정/자격 증명을 읽거나 수정하지 않았다.
호스트가 제공한 기존 connector/Skill 카탈로그는 이번 설치로 변경되지 않았다.

## 도구별 공식 설치 및 검토

### OPT-01 Serena

- 검토 버전 2.0.0.dev0; SHA는 sources.lock.json에 고정.
- README/설치: uv tool install -p 3.13 serena-agent.
  별도 소스 실행 방식도 공식 running 문서에 있다.
- requires-python >=3.11,<3.15. Python LSP 등 언어별 의존성 필요.
- 현재 라이선스: Serena GPL-3.0-or-later, SolidLSP MIT.
  과거 MIT 릴리스와 현재 라이선스를 혼동하지 않았다.
- 격리 uv tool 설치는 현재 3.12 interpreter로 시도했다
  (메타데이터 호환 범위 내, 공식 권장 3.13과는 다름).
  PyPI 연결 단계에서 실패하여 패키지 버전 설치는 확인하지 못했다.
- Codex context는 일반 파일/셸 도구 중복을 제외한다.
  일부 언어 서버는 추가 다운로드가 필요하며 설정/캐시를 사용자 디렉터리에 쓴다.
- MCP 미등록, 코드 심볼 검색 미실행. FAILED, 활성화 안 함.

### OPT-02 Headroom

- 검토 버전 0.40.0; Apache-2.0; Python >=3.10.
- 공식 pip/uv 설치, proxy, MCP, Python compress 경로를 확인했다.
  all extra는 ML·모델 다운로드 등 범위가 크므로 기본 core만 시도했다.
- headroom-ai==0.40.0을 격리 target에 설치 시도, PyPI 연결 실패.
- Codex installer는 config/provider/auth helper를 수정하고 API traffic을
  proxy로 전달할 수 있다. provider endpoint/key 설정 오류 위험이 있으므로
  wrap/mcp install/proxy를 실행하지 않았다.
- core의 로컬 압축과 실제 Cloud 모델 요청 프록시 연결은 별도 검증 항목이다.
  두 항목 모두 미검증. FAILED, 활성화 안 함.
- 의존성의 upstream security exclusion을 검토했지만 전체 공급망 감사는 하지 않았다.

### OPT-03 Ponytail

- 검토 버전 5.2.0; MIT.
- 공식 Codex plugin marketplace 설치 또는 SKILL.md 복사 설치 경로 확인.
- 기존 프로젝트 설치 없음. 핵심 SKILL.md 1개만 복사하고 LICENSE 보존.
- Node Hook은 mode/config/state 파일을 수정하고 context를 주입한다.
  activate/runtime/subagent Hook과 manifest를 읽었지만 실행/등록하지 않았다.
- 최소 변경, 기존 기능 재사용, 안전 제어 유지 규칙을 확인했다.
  파일 읽기/metadata/무결성은 검증, 모델 행동 개선은 측정하지 못했다.
- PARTIAL: optional skill files staged. 전체 plugin 및 Cloud 자동 로딩 미검증.

### OPT-04 Codex Token Optimizer Kit

- MIT, 공식 token-efficient-workflow Skill과 템플릿 검토 및 복사.
- helper는 Windows PowerShell 경로를 가정한다. Linux에서 실행하지 않았다.
- 기존 root AGENTS 규칙과의 중복을 검사하고 추가한 부분은 portable appendix에 제한했다.
- 원본 Skill은 비활성 보존. Linux용 opt-in codex-efficient-workflow Skill은
  자체 작성하여 rg/필수 검증/안전한 handoff 지침만 포함했다.
- upstream simple/standard/deep 대신 기존 FAST/STANDARD/STRICT가 우선한다.
  1–3 파일 제한은 필요한 안전 검증을 막는 절대 제한으로 적용하지 않는다.
- PARTIAL. Desktop profiles/PowerShell 및 현재 host discovery 미검증.

### OPT-05 Codex Token Optimizer

- README와 SKILL.md, 전체 경로 목록 검토.
- 검토한 tree에 LICENSE와 메타데이터 license grant가 관찰되지 않았다.
  공개 저장소라는 사실만으로 재배포 허가를 가정하지 않았다.
- Skill은 work/에 검토용으로 읽었으며 PR에 복사하지 않았다.
- scope/output/handoff 기능은 기존 지침과 겹친다.
  범용적으로 독립 작성한 checkpoint 템플릿만 추가했다.
- SECURITY_HOLD: 라이선스/배포 허가 확인 필요. 설치/host loading PASS 아님.

### OPT-06 Claude-Mem

- 검토 버전 13.37.0; Apache-2.0; Node >=20.12.0, Bun >=1.1.31.
- 공식 npx installer, Codex plugin manifest/MCP/hooks,
  CodexCliInstaller, provider 문서 및 telemetry consent 코드를 확인했다.
- Bun/uv, SQLite/worker, native hooks, 제공자 또는 로그인 상태가 필요하다.
  설치는 사용자 .codex config/plugins, .claude/.claude-mem 계열 파일을 변경하며
  worker를 시작할 수 있다. 현재 전역 설정은 읽기 전용이다.
- README는 hosted observer trial/account와 key 기반 provider 선택을 설명한다.
  기존 Codex subscription provider도 있으며 별도 OpenAI API key는 필수가 아니다.
  그러나 모델 관찰/요약 요청은 외부 전송이고 인증·사용량 의존성이 남는다.
- telemetry consent 구현은 default-on opt-out을 포함한다.
  DO_NOT_TRACK, CLAUDE_MEM_TELEMETRY=0, CLAUDE_MEM_TELEMETRY_ERRORS=0 등
  opt-out을 공식 문서에서 확인했다. opt-out은 observer 외부 전송 자체를 막지 않는다.
- 승인 없는 외부 전송을 피하기 위해 installer/worker/observer를 실행하지 않았다.
- SECURITY_HOLD. 설치·실제 Cloud 통합·새 Cloud 세션 지속성 모두 미검증.

### OPT-07 Superpowers

- 검토 버전 7.0.0; MIT. 공식 Codex marketplace plugin 지원 확인.
- 전체 plugin 대신 verification-before-completion Skill 1개와 LICENSE만 보존.
- session-start bootstrap은 using-superpowers를 주입하며 이 Skill은
  1% 관련성에도 Skill 호출, plan 전 brainstorming 등을 요구한다.
  이번 효율 목표와 겹치는 호출 비용이 있어 bootstrap을 활성화하지 않았다.
- visual companion에는 선택적 외부 logo request가 있다. 실행하지 않았다.
- 반복 fresh verification 지침과 기존 유효 검증 재사용 규칙이 충돌하면
  사용자/프로젝트 지침이 우선한다. 매 보고마다 전체 테스트를 반복하지 않는다.
- PARTIAL. brainstorm/subagent 실행 시간 효과는 미검증, 기본 비활성.

## 설치 파일과 지속성

tools/codex-optimization/available-skills/에 3개 reviewed Skill을 보존했고,
.agents/skills/에는 opt-in 자체 portable Skill만 있다.
SHA-256 무결성 확인, metadata 파싱, 중복 이름 검사, tampered Skill 거부 테스트가 통과했다.
이 검증은 Codex Cloud host의 discovery/자동 호출을 증명하지 않는다.
저장소 재사용은 PR 병합 후 가능하며 새 task에서 discovery를 확인해야 한다.
전역 Cloud 환경을 재게시하거나 실제 Setup Script 설정을 변경하지 않았다.

## 검증 및 제한

- 기존 테스트: 94 passed, 6 skipped (실제 Binance 호출 비활성).
- 신규 integrity tamper 검사: 1 passed.
- 최종 전체 pytest/ruff 결과는 benchmark-report.md에 기록.
- 프로덕션 데이터/키 미사용, 프로젝트 내용의 외부 모델 서비스 전송 없음.
- GitHub 쓰기는 사용자가 요청한 설정·문서·테스트 브랜치/PR에 한정.
- 서드파티 보안 전반에 PASS를 부여하지 않았다. 검토한 실행 경로만 확인했다.
- 설치 실패 명령을 같은 원인으로 반복하지 않았다.
