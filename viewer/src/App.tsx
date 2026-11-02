import { useEffect, useState } from "react";
import { fetchGraph } from "./api";
import { ClassView } from "./components/ClassView";
import { GraphCanvas } from "./components/GraphCanvas";
import { Header } from "./components/Header";
import { IssuesView } from "./components/IssuesView";
import { Overview } from "./components/Overview";
import { SidePanel } from "./components/SidePanel";
import { SourceDrawer } from "./components/SourceDrawer";
import { urlHash, useStore } from "./store";
import { decode } from "./urlState";

export function App() {
  const index = useStore((s) => s.index);
  const tab = useStore((s) => s.tab);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchGraph().then(
      (graph) => useStore.getState().load(graph, decode(location.hash)),
      (err: Error) => setError(err.message),
    );
  }, []);

  // Mirror the view into the URL hash (without growing the history).
  useEffect(() => {
    if (!index) return;
    let timer = 0;
    const unsubscribe = useStore.subscribe((state) => {
      clearTimeout(timer);
      timer = window.setTimeout(() => {
        const hash = urlHash(state);
        if (location.hash.slice(1) !== hash) history.replaceState(null, "", hash ? `#${hash}` : location.pathname);
      }, 200);
    });
    const onHashChange = () => {
      const state = useStore.getState();
      if (location.hash.slice(1) !== urlHash(state)) state.applyUrl(decode(location.hash));
    };
    window.addEventListener("hashchange", onHashChange);
    return () => {
      clearTimeout(timer);
      unsubscribe();
      window.removeEventListener("hashchange", onHashChange);
    };
  }, [index]);

  if (!index) {
    return <div className="loading">{error ? `불러오기 실패: ${error}` : "불러오는 중…"}</div>;
  }
  return (
    <div id="app">
      <Header />
      <div id="stage">
        {tab === "deps" && (
          <>
            <GraphCanvas />
            <Legend />
          </>
        )}
        {tab === "overview" && <Overview />}
        {tab === "classes" && <ClassView />}
        {tab === "issues" && <IssuesView />}
        <SourceDrawer />
      </div>
      <SidePanel />
    </div>
  );
}

function Legend() {
  const hasLayers = useStore((s) => (s.index?.graph.meta.layers?.length ?? 0) > 0);
  const path = useStore((s) => s.path);
  const clearPath = useStore((s) => s.clearPath);
  return (
    <>
      {path && (
        <div className="path-banner">
          순환 경로 강조 중 ({path.length}개 모듈)
          <button onClick={clearPath}>해제</button>
        </div>
      )}
      <div id="legend">
        <div>
          <i />
          import
        </div>
        <div>
          <i className="weak" />
          TYPE_CHECKING / 함수 안 import
        </div>
        <div>
          <i className="cycle" />
          순환 의존
        </div>
        {hasLayers && (
          <div>
            <i className="violation" />
            레이어 위반
          </div>
        )}
      </div>
      <div id="hint">더블클릭: 패키지 펼치기/접기 · 드래그: 이동 · 휠: 확대</div>
    </>
  );
}
