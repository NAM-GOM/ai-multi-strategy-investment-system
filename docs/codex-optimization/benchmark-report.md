# CODEX-OPT-01 성능 및 안전 검증

## 측정 범위

benchmark-results.csv는 실행한 **합성 로컬 절차 실험**의 측정값이다.
새 Cloud task, 별도 agent 또는 모델 추론을 실행하지 않았다.
같은 Python/rg, 같은 fixture와 patch, 5회 반복 중앙값을 사용했다.
이는 Codex 기본 설정 대 최적화 모델의 A/B 시험이 아니며 vendor 효과를 증명하지 않는다.
원본 애플리케이션을 읽거나 수정하지 않는 TemporaryDirectory에서 시험했다.
반복은 benchmark 반복 표본이며 기존 프로젝트 전체 CI 중복 실행과는 다르다.
실제 input/output 모델 토큰 및 end-to-end Codex latency는 모두 UNKNOWN이다.
byte 수를 모델 토큰 수로 바꾸거나 추정하지 않았다.

재현 명령:

```bash
python tools/codex-optimization/benchmark.py --output work/codex-opt-benchmark.csv
```

## 측정 결과

| 시험 | 기준 방식 | portable 절차 | 정확도/결과 | 해석 |
|---|---|---|---|---|
| A 검색 | 3.470 ms, 출력 4,162 bytes, 1 call | 3.587 ms, 72 bytes, 1 call | 함수/클래스 정의 2/2, 기준에는 comment hit 50개 | 출력 98.27% 감소; 시간 감소 없음 |
| B 로그/JSON | raw 412,910 bytes, 오류/원인/복구 3/3 포함 | Headroom BLOCKED | vendor 압축 크기/정보 손실 UNKNOWN | Headroom 설치 실패, 압축 PASS 없음 |
| C 수정 | 49.338 ms, 읽기 23,977 bytes | 90.277 ms, 읽기 77 bytes | 동일 patch, 변경 파일 1개, 전체 103/103 | 읽기 99.68% 감소; 테스트 추가로 82.98% 느림 |
| D 기억 | history 66,148 bytes, 0.157 ms | checkpoint 125 bytes, 0.005 ms | fixture facts 5/5 일치 | 로컬 deterministic recall만; Claude-Mem 효과 아님 |

A의 두 검색은 모두 source 전체를 스캔한다. read_bytes는 UNKNOWN이며,
출력 감소를 디스크 스캔 감소로 설명하지 않는다.
C의 기준은 전체 source fixture를 읽고 전체 unittest 1회 실행한다.
portable은 필요한 파일만 읽고 focused 3개 다음 전체 103개를 실행한다.
각 variant의 전체 검증은 반복당 정확히 1회다.
CSV tool_calls는 이 절차의 subprocess/명시적 읽기 단계 수이며 실제 Codex 호출 통계가 아니다.
수정은 미리 정한 한 줄 교체다. 동일 모델·reasoning 비교는 지원되지 않아 미실행이다.
모든 실험은 작은 synthetic fixture여서 production 작업으로 일반화하지 않는다.

## 요청된 vendor 비교의 완료 상태

- TEST-A Serena vs 기본: 미완료. 설치 실패, symbol/LSP/MCP 실행 없음.
- TEST-B Headroom 전후: 미완료. raw fixture 검증만 수행.
  error E042, timeout, retry-exhausted가 원본에 존재함을 검사했다.
- TEST-C 동일 난이도 격리 수정: deterministic 절차 검증 완료.
  실제 모델의 최적화 Skill 행동·입출력 토큰 비교는 미완료.
- TEST-D Claude-Mem vs 기본: 미완료. 별도 승인/영구 저장/새 Cloud 세션 없음.
  로컬 checkpoint 대 history 비교는 후속 절차 설계 참고용이다.
- Superpowers bootstrap/brainstorm/subagent 시간: 미검증.
  정책 비용 위험을 검토했으며 모델 실행 없이 시간 악화를 단정하지 않았다.
- Ponytail/두 Optimizer의 causal effectiveness: UNKNOWN.

## 최적화 판단

실제로 확인한 이점은 제한된 출력을 읽는 양과 checkpoint 크기 감소다.
빠른 작업의 focused+full 테스트는 비용을 늘릴 수 있다.
FAST는 적절한 focused check만 우선 고려하되 모든 project-mandated check를 유지한다.
STRICT에서 검증 절차를 생략하거나 focused 통과를 전체 통과로 바꾸지 않는다.
제3자 도구의 기본 활성화는 효과 검증이 없어 모두 보류했다.

## 기존 프로젝트 영향과 필수 검증

- src/, 기존 tests/, pyproject.toml, uv.lock, 기존 workflow는 수정 없음.
- frozen dev 의존성을 기존 uv cache에서 offline으로 복원했다.
- 기존 테스트 94 passed, 6 skipped. 신규 tamper 테스트 1 passed.
- 최종 전체 검사: 95 passed, 6 skipped; ruff check/format 통과.
- skip 6개는 기존 opt-in 실서비스 공개/계정 조회다. 실행하지 않았고 PASS로 세지 않았다.
- 신규 설정 검사: staged Skill hash/metadata/이름 및 opt-in 설정 통과.
- 신규 보안 회귀 검사: isolated copy에서 Skill 변조를 거부.
- Cloud host loading, 실제 서비스 안전, proxy live connection, 지속성에는 PASS 없음.
