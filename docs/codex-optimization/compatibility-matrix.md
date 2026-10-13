# Codex Cloud 호환성 매트릭스

상태는 **이번 환경에서 관찰한 결과**다. CLI 문서의 지원을 Cloud host 지원으로 확대하지 않는다.
FAILED는 설치 시도 실패, PARTIAL은 제한된 파일/수동 Skill 경로,
SECURITY_HOLD는 승인/라이선스/데이터 전송 문제로 실행하지 않은 상태다.

| 도구 | 상태 | 설치 | Cloud 실행 | 테스트 | 활성화 | 제한 사항 |
|---|---|---|---|---|---|---|
| Serena | FAILED | uv tool 설치 실패 | MCP 연결 미검증 | TEST-A Serena BLOCKED | 아니오 | PyPI/proxy 실패, LSP 및 host 등록 미확인 |
| Headroom | FAILED | pinned core 설치 실패 | proxy/MCP 미검증 | TEST-B BLOCKED | 아니오 | 네트워크, native deps, provider/config 변경 |
| Ponytail | PARTIAL | 핵심 Skill 파일만 보존 | 수동 읽기 가능, host discovery 미검증 | metadata/무결성 PASS, 모델 효과 UNKNOWN | 기본 비활성 | plugin/Hook 없음, 원래 description은 범용 자동 trigger |
| Token Optimizer Kit | PARTIAL | 원본 Skill 파일만 보존 | Linux rg 지침 자체 Skill 마련 | 격리 workflow/무결성 PASS | 원본 기본 비활성 | PowerShell 미실행, 프로파일 미적용 |
| Codex Token Optimizer | SECURITY_HOLD | 검토용 로컬 파일만, 설치 아님 | host loading 미검증 | scope/log 규칙 검토, vendor 실행 없음 | 아니오 | 라이선스 grant 미관찰, 재배포 보류 |
| Claude-Mem | SECURITY_HOLD | installer 미실행 | worker/hook/MCP 미검증 | TEST-D vendor 미검증 | 아니오 | 외부 observer 전송, auth/quota, 전역 쓰기, 지속성 |
| Superpowers | PARTIAL | 검증 Skill 1개만 보존 | 수동 읽기 가능, host discovery 미검증 | metadata/무결성 PASS, 시간 효과 UNKNOWN | 기본 비활성 | 전체 workflow/bootstrap/brainstorm/subagent 없음 |

현재 SUPPORTED로 판정한 제3자 통합은 없다.
파일 보존 성공과 완전한 plugin 설치를 구분했다.
UNSUPPORTED는 현재 문서에 영구 불가 판정할 근거가 없어서 사용하지 않았다.
SETUP_REQUIRED 사항은 아래 도구별 최종 상태와 함께 setup guide에 정리했다.
