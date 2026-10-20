/**
 * 编辑器侧栏拖拽调宽。
 *
 * 拖分隔条实时改宽度（min/max 夹取），松手才写 localStorage ——
 * 与「滑杆松手才提交」同一套意图采集哲学：拖动过程中的几十帧不该落存储。
 */

import { useCallback, useState } from "react";

const MIN_WIDTH = 264;
const MAX_WIDTH = 440;
const DEFAULT_WIDTH = 304;

export function usePanelWidth(storageKey: string, side: "left" | "right") {
  const [width, setWidth] = useState(() => {
    const saved = Number(localStorage.getItem(storageKey));
    return saved >= MIN_WIDTH && saved <= MAX_WIDTH ? saved : DEFAULT_WIDTH;
  });

  const onHandlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = width;
      const sign = side === "left" ? 1 : -1;
      let latest = startWidth;

      // 拖动期间全局接管光标与选区，路过 iframe/画布都不飘
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      const onMove = (e: PointerEvent) => {
        latest = Math.min(
          MAX_WIDTH,
          Math.max(MIN_WIDTH, startWidth + sign * (e.clientX - startX)),
        );
        setWidth(latest);
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        localStorage.setItem(storageKey, String(latest));
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    [width, side, storageKey],
  );

  return { width, onHandlePointerDown };
}
