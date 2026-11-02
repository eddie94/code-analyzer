import { useEffect, useState } from "react";
import { fetchGraph } from "./api";
import { GraphCanvas } from "./components/GraphCanvas";
import { Header } from "./components/Header";
import { SidePanel } from "./components/SidePanel";
import { SourceDrawer } from "./components/SourceDrawer";
import { useStore } from "./store";

export function App() {
  const index = useStore((s) => s.index);
  const load = useStore((s) => s.load);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchGraph().then(load, (err: Error) => setError(err.message));
  }, [load]);

  if (!index) {
    return <div className="loading">{error ? `불러오기 실패: ${error}` : "불러오는 중…"}</div>;
  }
  return (
    <div id="app">
      <Header />
      <div id="stage">
        <GraphCanvas />
        <Legend />
        <SourceDrawer />
      </div>
      <SidePanel />
    </div>
  );
}

function Legend() {
  return (
    <>
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
      </div>
      <div id="hint">더블클릭: 패키지 펼치기/접기 · 드래그: 이동 · 휠: 확대</div>
    </>
  );
}
