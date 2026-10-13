# 기본 활성화 구성

## 현재 상태

**7개 중 현재 Codex Cloud host에 새로 활성화한 제3자 도구는 0개다.**

기존 Universal Codex Efficiency Rules를 보존한 root AGENTS.md와
portable appendix만 기본 프로젝트 지침으로 제안했다.
현재 세션의 이미 로드된 system Skill 카탈로그를 변경했다고 주장하지 않는다.

| 구성 | 기본 상태 | 확인한 범위 |
|---|---|---|
| AGENTS 기존 효율·안전 규칙 | 유지 | 삭제/완화 없이 원문 보존 |
| portable appendix | PR에 제안 | scope/검증/log/hand-off 안전성 검토 |
| .agents/skills/codex-efficient-workflow | 명시 요청 시 사용 제안 | 파일·opt-in metadata 확인, host discovery 미검증 |
| Ponytail 핵심 Skill | 보존, 비활성 | metadata/내용/무결성 |
| Kit 핵심 Skill | 보존, 비활성 | metadata/내용/무결성; PowerShell 미실행 |
| Superpowers 검증 Skill | 보존, 비활성 | metadata/내용/무결성 |
| Serena / Headroom | 설치 실패, 비활성 | 네트워크 오류 |
| Codex Token Optimizer | 재배포 보류 | 라이선스 미관찰 |
| Claude-Mem | 설치·활성화 보류 | 외부 전송/worker/권한/지속성 |

## 기능 중복과 선택

- scope/minimal diff: 기존 AGENTS가 기본. Ponytail 전체 prompt 자동 주입 불필요.
- output limits: 기존 AGENTS 및 portable Skill. Kit 원본은 필요할 때만 수동 검토.
- checkpoint: 자체 template, 사실과 revision 검증 후 사용.
- completion evidence: 기존 필수 검사 + 선택적 Superpowers 검증 Skill.
  동일한 passing check를 정당한 이유 없이 반복하지 않는다.
- semantic search: 현재 native rg. Serena 검증 후에만 선택.
- semantic compression: Headroom 검증 후에만 선택; 로컬 요약과 혼동 금지.
- durable memory: committed non-sensitive handoff는 Git 기반 재사용에 사용.
  Claude-Mem 및 실제 새 task 복원은 별도 검증 필요.

3개 staged Skill은 자동 검색 경로 밖에 있어 초기 prompt 주입/Hook 비용이 없다.
자체 opt-in Skill은 일반 coding task가 아니라 명시적 CODEX-OPT-01 요청에만
적용하도록 description을 제한했다. 실제 host의 implicit matching은 미검증이다.
새 task에서 확인할 때까지 자동 invocation 성공을 보고하지 않는다.
