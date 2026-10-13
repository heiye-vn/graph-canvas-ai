/**
 * 编辑页占位。
 * M3 会在这里接入 Konva 画布与 LayerDocument；
 * M8 会补上计划卡片与 SSE 进度；M9.1 补上 CoT 思维链面板。
 *
 * 占位也照实说清楚「还没做」：写个「敬请期待」式的空头承诺，
 * 演示时被人点开会很尴尬。
 */

import { Link } from 'react-router-dom'
import { Button, Result } from 'antd'

export default function EditorPage() {
  return (
    <Result
      className="py-24"
      title="编辑工作台"
      subTitle="画布将在 M3 接入。先在创作页生成候选，或直接上传一张图。"
      extra={
        <Link to="/create">
          <Button type="primary">去创作</Button>
        </Link>
      }
    />
  )
}
