/**
 * 编辑页占位。
 * M3 会在这里接入 Konva 画布与 LayerDocument；
 * M8 会补上计划卡片与 SSE 进度；M9.1 补上 CoT 思维链面板。
 */
export default function EditorPage() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <h1 className="text-xl font-medium">编辑工作台</h1>
        <p className="mt-2 text-sm text-neutral-400">画布将在 M3 接入</p>
      </div>
    </div>
  )
}
