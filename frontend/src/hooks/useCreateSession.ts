/**
 * 「用这批素材开一个编辑会话」的统一入口。
 *
 * 候选页和素材库都要做这件事，各写一遍的结果是跳转目标、乐观提示都不一样。
 * 收在这里之后，两处的行为天然一致。
 */

import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { createSession } from '@/api/sessions'
import type { SessionOut } from '@/api/sessions'

export function useCreateSessionAndEdit() {
  const navigate = useNavigate()

  return useMutation<SessionOut, Error, { asset_ids: string[]; title?: string }>({
    mutationFn: (payload) => createSession(payload),
    onSuccess: (session) => {
      // 跳到带 session id 的编辑页：可刷新、可分享
      navigate(`/editor/${session.id}`)
    },
  })
}
