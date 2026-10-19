/**
 * 「用这批素材开一个编辑会话」的统一入口。
 *
 * 候选页和素材库都要做这件事，各写一遍的结果是跳转目标、乐观提示都不一样。
 * 收在这里之后，两处的行为天然一致。
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { createSession } from '@/api/sessions'
import type { SessionOut } from '@/api/sessions'

export function useCreateSessionAndEdit() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  return useMutation<SessionOut, Error, { asset_ids: string[]; title?: string }>({
    mutationFn: (payload) => createSession(payload),
    onSuccess: (session) => {
      // 关键：使会话列表缓存失效，确保回退到 /editor 时立即展示新建的会话
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      // 跳到带 session id 的编辑页：可刷新、可分享
      navigate(`/editor/${session.id}`)
    },
  })
}
