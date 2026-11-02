import { useEffect, useMemo, useRef, useState } from "react";
import { buildTree, colorScale, issueCounts, layoutTree, PACKAGE_HEADER, ramp, type ColorMetric } from "../model/treemap";
import { useStore } from "../store";

const METRICS: Array<[ColorMetric, string]> = [
  ["complexity", "최대 함수 복잡도"],
  ["instability", "불안정성"],
  ["issues", "이슈 수"],
  ["group", "패키지별 색"],
];

export function Overview() {
  const index = useStore((s) => s.index)!;
  const hideTests = useStore((s) => s.hideTests);
  const selected = useStore((s) => s.selected);
  const select = useStore((s) => s.select);
  const reveal = useStore((s) => s.reveal);
  const [metric, setMetric] = useState<ColorMetric>("complexity");
  const box = useRef<HTMLDivElement>(null);
  const size = useSize(box);

  const tree = useMemo(() => buildTree(index, hideTests), [index, hideTests]);
  const root = useMemo(() => (size ? layoutTree(tree, size.width, size.height) : null), [tree, size]);
  const issues = useMemo(() => issueCounts(index), [index]);
  const scale = useMemo(() => colorScale(index, metric, issues), [index, metric, issues]);

  return (
    <div className="overview">
      <div className="overview-bar">
        <span className="muted">크기 = 코드 줄 수 · 색 =</span>
        <select value={metric} onChange={(e) => setMetric(e.target.value as ColorMetric)}>
          {METRICS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        {metric !== "group" && (
          <span className="ramp">
            0<i style={{ background: `linear-gradient(90deg, ${ramp(0)}, ${ramp(0.5)}, ${ramp(1)})` }} />
            {metric === "instability" ? "1" : `${scale.max}+`}
          </span>
        )}
        <span className="spacer" />
        <span className="muted">클릭: 선택 · 더블클릭: 의존성 그래프에서 보기</span>
      </div>
      <div className="treemap" ref={box} onClick={() => select(null)}>
        {root?.descendants().slice(1).map((d) => {
          const node = index.nodes.get(d.data.id)!;
          const width = d.x1 - d.x0;
          const height = d.y1 - d.y0;
          const isPackage = Boolean(d.children);
          const value = scale.value(node);
          const title = [
            node.qualname,
            `${(node.metrics?.loc ?? 0).toLocaleString()} 줄`,
            value !== null && metric !== "group" ? `${scale.label}: ${value}` : null,
          ]
            .filter(Boolean)
            .join("\n");
          return (
            <div
              key={node.id}
              className={`tile${isPackage ? " package" : ""}${node.id === selected ? " selected" : ""}`}
              style={{
                left: d.x0,
                top: d.y0,
                width,
                height,
                background: isPackage ? undefined : scale.color(node),
                borderColor: isPackage ? index.color(node) : undefined,
              }}
              title={title}
              onClick={(e) => {
                e.stopPropagation();
                select(node.id);
              }}
              onDoubleClick={(e) => {
                e.stopPropagation();
                reveal(node.id);
              }}
            >
              {isPackage
                ? width > 40 && <div className="tile-head" style={{ height: PACKAGE_HEADER }}>{node.name}</div>
                : width > 44 && height > 18 && <div className="tile-label">{node.name}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function useSize(ref: React.RefObject<HTMLElement | null>) {
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((prev) => (prev?.width === width && prev?.height === height ? prev : { width, height }));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}
