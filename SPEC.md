# codemap: Python 리포지토리 구조 시각화 도구 사양

## 1. 목표
로컬 Python 리포지토리를 정적 분석해서 구조 그래프를 만들고, 브라우저에서 인터랙티브하게 탐색한다.

- 처음 보는 리포의 패키지/모듈 구조와 의존 관계를 빠르게 파악한다.
- 순환 import, 결합도 높은 모듈, 레이어 규칙 위반을 찾는다.
- 분석 결과(`graph.json`)를 Mermaid/DOT/단일 HTML로도 내보내 위키·PR·CI에 재사용한다.

**범위 밖:** Python 이외 언어, 런타임 분석, 분석 대상 코드 실행, 원격 리포 클론.

## 2. 기술 스택
| 영역 | 선택 | 이유 |
|---|---|---|
| 분석기 | Python 3.12+, 표준 라이브러리 `ast` | 분석 대상이 Python뿐이므로 tree-sitter 불필요. 파싱은 C로 구현돼 충분히 빠르고 문법 정확도가 가장 높음 |
| 데이터 모델 | pydantic v2 | 검증 + JSON Schema 생성 → 프론트 TS 타입 자동 생성 |
| 그래프 연산 | networkx | SCC(순환), 중심성 |
| CLI | typer | |
| 로컬 서버 | FastAPI + uvicorn | 그래프·소스 코드 API, 빌드된 viewer 정적 서빙 |
| 화면 | React + TypeScript + Vite | |
| 그래프 렌더링 | Cytoscape.js + ELK 레이아웃 | 디렉터리 접기/펼치기(compound node), 계층형 배치 |
| treemap/차트 | D3 | |
| 코드 미리보기 | Shiki | |
| 상태 관리 | Zustand | |
| 개발 도구 | uv, ruff, pytest / npm, vitest | |

배포: viewer 빌드 결과를 Python 패키지 안(`codemap/server/static`)에 포함한다. 사용자는 `uv tool install` 또는 `pipx install` 만으로 쓰고, Node.js는 개발할 때만 필요하다. 빌드 결과는 git에 넣지 않고 wheel에만 포함한다(`artifacts`).

개발 흐름:
- `cd viewer && npm run build` → `src/codemap/server/static`에 빌드. 이후 `uv run codemap serve <repo>`.
- 화면만 고칠 때: `uv run codemap serve <repo> --no-open` 을 띄워 두고 `cd viewer && npm run dev` (Vite가 `/api`를 8700으로 프록시).
- `codemap.model`을 바꾸면 `cd viewer && npm run gen:types`로 `src/types/graph.ts`를 다시 만든다. 잊으면 `tests/test_schema.py`가 실패한다.

**성능 목표:** 파일 5,000개 첫 분석 15초 이내(멀티프로세스), 캐시 적중 시 3초 이내.

**캐시:** 파일 내용 해시를 키로 파일별 추출 결과를 저장한다. 위치는 분석 대상 리포가 아니라 사용자 캐시 디렉터리(`$CODEMAP_CACHE_DIR`, 없으면 `$XDG_CACHE_HOME/codemap` 또는 `~/.cache/codemap`)이고 형식은 JSON이다. 리포 안에 심어 둔 캐시 파일이 읽히거나 코드를 실행할 수 없게 하기 위해서다. 추출 로직이 바뀌면 `EXTRACT_VERSION`을 올린다.

## 3. Python 분석 항목

### 3.1 모듈 탐색
- `.gitignore` 준수, include/exclude glob 적용.
- 소스 루트 자동 감지: `pyproject.toml`의 패키지 설정, `src/` 레이아웃, 최상위 패키지. 설정으로 덮어쓸 수 있다.
- `__init__.py`가 있는 일반 패키지와 namespace 패키지 모두 지원.
- 파싱에 실패한 파일(Python 2 문법 등)은 건너뛰고 `parse_errors`에 기록한다.

### 3.2 import 해석
| 형태 | 처리 |
|---|---|
| `import a.b.c` | 리포 내부 모듈이면 `a/b/c.py` 또는 `a/b/c/__init__.py`로 연결 |
| `from . import x`, `from ..m import y` | 상대 경로 해석. `x`가 서브모듈인지 심볼인지 구분 |
| `from pkg import Name` | `pkg/__init__.py`가 다시 내보내는(re-export) 경우 실제 정의 모듈까지 추적 |
| 표준 라이브러리 | `sys.stdlib_module_names`로 판별, `stdlib:<name>` 노드 |
| 서드파티 | `external:<top-level name>` 노드. 기본은 화면에서 숨김 |

import 엣지마다 다음 속성을 붙인다.
- `type_only`: `if TYPE_CHECKING:` 블록 안. 런타임 순환이 아니므로 순환 판정에서 분리한다.
- `lazy`: 함수/메서드 안에서 import.
- `conditional`: `try/except ImportError`, `if` 블록 안.
- `names`: 가져온 이름 목록, `line`: 위치.

### 3.3 심볼
- 클래스: 이름, 위치, 베이스 클래스(import 표를 이용해 리포 내부 클래스로 해석), 데코레이터.
- 함수/메서드: 이름, 위치, `async` 여부, 데코레이터, 인자 수.
- 모듈: docstring 첫 줄, `__all__`.

### 3.4 메트릭과 진단
| 항목 | 단위 | 설명 |
|---|---|---|
| LOC, 심볼 수 | 모듈, 패키지 | 빈 줄·주석·docstring 제외 |
| fan-in / fan-out | 모듈, 패키지 | 런타임 import 기준 |
| Instability `Ce/(Ca+Ce)` | 모듈, 패키지 | 패키지는 경계를 넘는 모듈 수로 계산 |
| 최대 함수 복잡도 | 모듈, 패키지 | 안에 든 함수·메서드 중 최댓값 |
| 순환 복잡도 | 함수 | 분기 노드 수 + 1 (`ast` 직접 계산) |
| 순환 import | 모듈 | Tarjan SCC. 세 종류로 나눔: 직접 순환(warning), 패키지 `__init__`를 거쳐야만 닫히는 순환(info), TYPE_CHECKING·함수 안 import로만 닫히는 순환(info). 각 이슈에 가장 짧은 순환 예시(`examples`)를 최대 3개 담는다 |
| 핫스팟 (선택) | 모듈 | 최근 N일 git 커밋 수 × 복잡도 |
| 레이어 위반 | import 엣지 | 설정한 레이어 순서 역방향 import |

## 4. 데이터 모델 (`graph.json`)
```json
{
  "meta": { "root": "/path/repo", "generated_at": "...", "schema_version": 1,
            "source_roots": ["src"] },
  "nodes": [
    { "id": "pkg:app.service", "kind": "package", "name": "service", "parent": "pkg:app",
      "path": "src/app/service" },
    { "id": "mod:app.service.user", "kind": "module", "name": "user", "parent": "pkg:app.service",
      "path": "src/app/service/user.py", "range": [1, 240],
      "metrics": { "loc": 210, "fan_in": 4, "fan_out": 7 } },
    { "id": "cls:app.service.user.UserService", "kind": "class", "parent": "mod:app.service.user",
      "range": [12, 180], "decorators": [] }
  ],
  "edges": [
    { "source": "mod:app.api.users", "target": "mod:app.service.user", "kind": "imports",
      "names": ["UserService"], "line": 3, "type_only": false, "lazy": false, "conditional": false }
  ],
  "issues": [
    { "kind": "cycle", "severity": "warning", "nodes": ["mod:a", "mod:b"], "runtime": true }
  ]
}
```
- node kind: `package | module | class | function | method | stdlib | external`
- edge kind: `imports | extends` (v2: `calls`). 포함 관계는 별도 엣지 없이 node의 `parent`로 표현한다.
- issue kind: `cycle | unresolved_import | parse_error`. 파싱 실패도 issue로 기록한다. 순환 이슈에는 `runtime`, `through_init`, `examples`가 붙는다.
- id 접두사: `pkg: mod: cls: fn: meth: stdlib: external:` + 점 표기 qualified name. `__init__.py`는 `mod:<패키지명>`이고 부모는 `pkg:<패키지명>`이다.
- import 엣지는 (source, target) 단위로 합친다. `type_only`/`lazy`/`conditional`은 합쳐진 import가 모두 해당할 때만 true다.
- 기본값과 같은 필드는 출력에서 생략한다. 출력은 정렬해서 같은 입력이면 항상 같은 파일이 나온다.
- pydantic 모델이 단일 원본이다. JSON Schema를 생성해 `viewer/src/types/graph.ts`로 변환한다.

## 5. 화면 (viewer)
| 탭 | 내용 |
|---|---|
| Overview | 패키지 treemap. 크기 = LOC, 색 = 복잡도 또는 핫스팟. 클릭 시 Dependency 탭에서 해당 패키지로 포커스 |
| Dependency | 모듈/패키지 import 그래프. 패키지 접기·펼치기, 깊이 슬라이더, 런타임 순환 빨간색, type-only/lazy import 점선, 레이어 위반 강조. 노드 선택 시 들어오는/나가는 의존만 하이라이트 |
| Classes | 선택한 패키지의 클래스 상속 관계 (UML 형태) |
| Issues | 순환, 레이어 위반, 핫스팟 목록. 행 클릭 시 그래프로 이동 |

공통:
- 사이드 패널: 메트릭, 경로, import 목록, 소스 코드 미리보기(해당 줄 하이라이트), `vscode://` 에디터 열기 링크.
- 검색(모듈·클래스·함수), 필터(stdlib/external 숨김, type-only 제외, 테스트 제외).
- 현재 포커스·필터 상태를 URL에 저장해 링크로 공유.
- 라이트/다크 모드.
- 노드가 3,000개를 넘으면 패키지 단위로 자동 축약한다.

## 6. CLI
```bash
codemap analyze <repo> [-o out/]            # graph.json 생성
codemap serve <repo> [--port 8700]          # 분석 후 로컬 서버 + 브라우저 열기
codemap export <repo> -o report.html        # 데이터 내장 단일 HTML (소스 미리보기 제외)
codemap render out/graph.json --format mermaid|dot [--level package|module] [--focus app.service]
codemap check <repo> [--fail-on KIND] [--format text|github]   # 위반 시 exit 1 (CI용)
```

- `analyze`, `serve`, `export`, `check`는 기본으로 캐시를 쓰고(`--no-cache`로 끔), git 기록에서 churn·핫스팟을 계산한다.
- `check`가 실패로 보는 이슈는 `fail_on`(기본 `layer_violation`, `cycle`)으로 정한다. `cycle`은 직접 순환만 뜻하고, `__init__` 경유·타입/지연 import 순환은 제외한다. `--format github`은 GitHub Actions 주석(`::error file=...`)을 출력한다.
- `export`는 빌드된 viewer의 JS·CSS와 그래프 데이터를 HTML 한 파일에 넣는다. 서버가 없으므로 소스 미리보기는 숨긴다.

서버 API:
- `GET /api/graph`: 분석 결과
- `GET /api/source?path=...`: 소스 원문. 리포 루트 밖 경로는 거부한다.

## 7. 설정 (`pyproject.toml`의 `[tool.codemap]`, 없으면 `.codemap.toml`)
```toml
[tool.codemap]
source_roots = ["src"]
exclude = ["**/migrations/**", "tests/**"]
hide_external = true
fail_on = ["layer_violation", "cycle"]   # codemap check가 실패로 볼 이슈
churn_days = 90                          # churn을 셀 git 기록 기간, 0이면 끔

[[tool.codemap.layers]]   # 위에서 아래 방향 import만 허용
name = "api"
modules = ["app.api.*"]

[[tool.codemap.layers]]
name = "service"
modules = ["app.service.*"]

[[tool.codemap.layers]]
name = "repository"
modules = ["app.repo.*"]
```

## 8. 디렉터리 구조
```
code-analyzer/
  pyproject.toml
  src/codemap/
    cli.py
    config.py
    model.py            # pydantic 모델 (graph.json 단일 원본)
    scan.py             # 파일 수집, 소스 루트 감지
    extract.py          # ast 순회: import, 심볼, 복잡도
    resolve.py          # import → 모듈/심볼 해석, re-export 추적
    cache.py
    analyze/            # metrics.py, cycles.py, layers.py, churn.py
    render/             # mermaid.py, dot.py, export_html.py
    server/             # app.py, static/ (viewer 빌드 결과)
  viewer/               # React + TS + Vite
    src/types/graph.ts  # JSON Schema에서 생성
  tests/
    fixtures/           # 미니 리포: 상대 import, re-export, 순환, TYPE_CHECKING, 레이어 위반
    test_*.py           # graph.json 스냅샷 테스트
```

## 9. 마일스톤
| 단계 | 내용 | 완료 기준 |
|---|---|---|
| M1 | scan, extract, resolve, 순환 검출, `graph.json`, Mermaid 출력 | fixture 스냅샷 테스트 통과, 실제 리포 하나를 Mermaid로 렌더 |
| M2 | FastAPI 서버, React viewer 뼈대, Dependency 탭, 사이드 패널, 소스 미리보기 | `codemap serve`로 실제 리포 탐색 가능 |
| M3 | Classes·Overview·Issues 탭, 메트릭 전체, 검색·필터, URL 상태 | 4개 탭 모두 동작 |
| M4 | 레이어 규칙과 `check`, `export` 단일 HTML, 캐시, git 핫스팟 | CI에서 위반 시 실패 |
| M5a | 진입점 수집, 호출 그래프, 흐름 탭 | LLM을 쓰는 FastAPI 서비스에서 라우트부터 LLM 호출 지점까지 끊기지 않고 이어짐 |
| M5b | 부수효과·LLM 호출 인식, LLM 탭 | LLM 호출 지점이 모두 잡히고 모델·프롬프트가 표시됨 |
| M5c | 조건·반복·병렬·백그라운드·단계 주석 표시, 데이터 흐름 화면 | 요청 처리 함수의 흐름이 단계 주석 순서대로 읽히고, 값이 어느 호출로 들어가 무엇이 되는지 보임 |
| 이후 | 서비스 간 HTTP 호출 연결, 두 커밋 간 구조 비교 | |

M1~M4, M5a, M5c 완료. 레이어 규칙은 모듈마다 처음 일치하는 레이어에 배정하고, TYPE_CHECKING import는 위반으로 보지 않는다.

## 10. M5: 실행 흐름 (설계안)

목표: 코드를 실행하지 않고, "요청 하나가 들어오면 무엇이 어떤 순서로 일어나는가"를 보여준다. 분석 대상은 LLM 호출이 들어 있는 AI 서비스 엔진이다. codemap 자체는 LLM을 호출하지 않는다(요약 생성은 보류).

### 10.1 다뤄야 할 코드 패턴
일반적인 LLM 서비스 코드에서 볼 수 있는 구조들이다. 예시는 설명을 위해 지어낸 것이다.

| 패턴 | 예 | 필요한 분석 |
|---|---|---|
| FastAPI 서비스 여러 개 | `api/app.py`(`POST /ask`), `worker/app.py` | 라우트 데코레이터로 진입점 수집 |
| 모듈 전역에 나중에 대입되는 객체 | `engine = None` 후 시작 시 `Engine(...)` 대입 | 모듈 전역 변수의 타입을 모든 대입에서 추론 |
| LLM 팩토리 | `make_llm(name)`가 이름에 따라 `ChatOpenAI`나 `ChatAnthropic`을 골라 반환 | "LLM을 만드는 함수" 인식, 반환값 추적 |
| LangChain LCEL | `chain = prompt \| llm \| StrOutputParser()`, `llm.with_fallbacks([backup])`, `await chain.ainvoke(...)` | `\|` 연산자, `with_fallbacks` 등을 거쳐도 LLM 값으로 유지 |
| 설정 클래스 기본값 + 환경 변수 | `model: str = os.environ.get("CHAT_MODEL", "gpt-4o-mini")` | 모델 이름을 "gpt-4o-mini (env CHAT_MODEL)"로 표시 |
| 프롬프트 상수 | `PromptTemplate(template=ANSWER_PROMPT, ...)` | 어느 상수·파일이 어느 LLM 호출에 쓰이는지 연결 |
| 규칙 우선 처리 | 규칙 함수가 답을 주면 LLM 없이 `return` | 호출 앞의 조기 반환과 조건 표시 |
| 병렬·재시도·백그라운드 | `asyncio.gather(answer(), tag())`, `for attempt in range(retries)`, `asyncio.create_task` | 병렬 묶음, 반복, 백그라운드 표시 |
| 단계 주석 | `# Step 2. Retrieve documents` | 흐름의 소제목으로 사용 |
| 서비스 간 HTTP | 한 서비스가 다른 서비스를 `aiohttp`로 호출, URL은 설정에서 | (이후) URL 경로를 상대 서비스 라우트와 연결 |

### 10.2 진입점
- 웹 라우트: FastAPI/Flask/Starlette 데코레이터(`@app.post("/x")`, `@router.get`), `app.add_api_route`. 라벨은 `POST /ask`.
- 시작·종료 훅: `@app.on_event("startup")`, `lifespan`.
- 스크립트: `if __name__ == "__main__":` 블록, `[project.scripts]`.
- CLI: typer/click 명령, argparse 하위 명령.
- 워커: Celery 태스크 등은 이후.

### 10.3 호출 그래프 (best-effort)
- 해석하는 호출: import로 가져온 함수, `self.method()`(상속 포함), `Cls()` → `Cls.__init__`, `super().m()`.
- 객체 타입 추론: `self.x = Cls(...)`, 타입 힌트(속성·매개변수·반환), 기본값 `config: X = X()`, 모듈 전역 변수의 모든 대입(`global` 포함), 타입 힌트가 있는 함수의 반환값.
- 베이스 클래스 메서드 호출은 오버라이드한 하위 클래스를 후보로 둔다.
- 해석 결과마다 확신도를 둔다: `exact`(직접 확인), `inferred`(타입 추론), `candidates`(후보 여러 개). 해석 못 한 호출은 버리지 않고 "알 수 없음"으로 남긴다.
- 표준 라이브러리·외부 라이브러리 호출은 라이브러리 노드로 묶고, 부수효과 판정에만 쓴다.

### 10.4 부수효과와 LLM 호출
- 종류: `llm`, `http`, `db`(벡터 DB 포함), `cache`, `file`, `subprocess`, `env`.
- LLM 값의 출처: LangChain 채팅 모델 클래스(`ChatOpenAI`, `ChatAnthropic`, `ChatVertexAI` 등), OpenAI·Anthropic·google-genai SDK 클라이언트, 그리고 이런 값을 반환하는 사용자 함수(팩토리). `|`, `with_fallbacks`, `with_retry`, `with_listeners`, `bind`, `with_structured_output`을 거쳐도 LLM 값으로 본다.
- LLM 호출: LLM 값에 대한 `invoke`/`ainvoke`/`stream`/`astream`/`batch`/`abatch`, SDK의 `chat.completions.create`, `messages.create`, `generate_content`.
- 호출 지점마다 뽑는 정보: 모델 이름 후보(리터럴, 설정 기본값과 환경 변수 이름), 폴백 모델, 프롬프트 출처(상수 이름·파일), 출력 파서, 반복문·병렬 안인지.
- 사내 SDK나 HTTP로 부르는 모델 서버는 설정으로 추가한다:
  ```toml
  [tool.codemap.effects]
  llm = ["mycorp_llm.Client.generate", "url:*/v1/chat/completions"]
  db = ["myapp.storage.*"]
  ```
- 부수효과는 호출 그래프를 따라 위로 전파한다. 흐름 화면에서 "이 단계 아래 어딘가에서 LLM 2번, HTTP 1번"처럼 보인다.

### 10.5 제어 흐름 표시
호출 지점마다 다음을 기록한다.
- 감싸는 조건문(`if` 조건식 원문과 분기), 그 앞의 조기 반환
- 반복문(`for`/`while`, 재시도 패턴 `for attempt in range(...)`)
- `try`/`except`(폴백 경로)
- `await` 여부, 병렬 묶음(`asyncio.gather`, `TaskGroup`), 백그라운드(`create_task`, FastAPI `BackgroundTasks`)
- 바로 앞의 단계 주석(`# Step N ...` 같은 배너 주석)

### 10.6 데이터 모델 추가
- edge kind `calls`: `line`, `awaited`, `conditions`(조건식 목록), `loop`, `parallel_group`, `background`, `confidence`, `candidates`
- `Graph.entrypoints`: `{id, kind: route|startup|script|command, label, target}`
- 함수 노드 `effects`: `{kind, detail, line}` 목록, LLM 호출은 `detail`에 모델·프롬프트·폴백
- 함수 노드 `sections`: 단계 주석 `{line, title}` 목록

### 10.7 화면
- 흐름 탭: 진입점 목록 → 고르면 호출 트리를 단계별로 펼친다. 단계 주석을 소제목으로, 조건·반복·병렬·백그라운드를 배지로 표시하고, LLM 단계는 강조한다. 단계를 누르면 소스가 열린다. 깊이 제한과 "라이브러리 숨기기"가 있다.
- 데이터 흐름: 함수 한 줄이 호출 하나다. 왼쪽에 읽는 변수와 메서드를 부르는 객체, 오른쪽에 결과를 받는 변수를 그리고, 조건에 쓰인 변수에서 반환·예외 지점으로 점선을 잇는다. 같은 값은 마우스를 올리면 모두 강조된다.
- LLM 탭: LLM 호출 지점 전체. 모델, 폴백, 프롬프트, 이 지점에 도달하는 진입점.
- 오른쪽 패널: 함수를 고르면 "이 함수에 도달하는 진입점"과 이 함수 아래에서 일어나는 부수효과 요약.

### 10.8 범위 밖
코드 실행·런타임 추적, LLM으로 설명 생성(보류), 프롬프트 내용 평가.
