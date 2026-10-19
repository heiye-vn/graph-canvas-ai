/**
 * 左侧对话与 Agent 多步执行面板（对齐参考项目图1标准）。
 *
 * 1. 结构化流程卡片：步骤清晰、状态胶囊对齐、CoT 展开流优雅折叠
 * 2. 视觉层级明确：用户浅蓝气泡 vs 系统白底专业卡片
 * 3. 一体化多行输入盒与快捷 Prompt 药丸
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Tag } from "antd";
import {
  CheckCircleFilled,
  CheckOutlined,
  ClockCircleOutlined,
  CloseCircleFilled,
  CloseOutlined,
  FileSearchOutlined,
  LoadingOutlined,
  PlusOutlined,
  RedoOutlined,
  SendOutlined,
  SyncOutlined,
} from "@ant-design/icons";

import {
  cancelPlan,
  confirmPlan,
  continuePlan,
  createPlan,
  getAgentRun,
  listSessionRuns,
  retryPlan,
} from "@/api/agent";
import type { AgentRun, PlanStep } from "@/api/agent";
import { useRunStream } from "@/hooks/useRunStream";
import { useCotStream } from "@/hooks/useCotStream";
import CoTStream from "@/components/agent/CoTStream";
import TraceModal from "@/components/agent/TraceModal";

interface ChatMessage {
  role: "user" | "agent";
  text?: string;
  runId?: string;
}

const SUGGESTIONS = [
  "把耳机拆成单独的图层",
  "去背景，然后垂直翻转一下",
  "局部替换成亮橙色，然后旋转30度",
  "把图调亮一点并水平翻转",
];

export default function ChatPanel({
  sessionId,
  onChanged,
  onQueuedRun,
}: {
  sessionId: string;
  /** 任何步骤落地后通知外层（画布文档变了） */
  onChanged?: () => void;
  /** Agent 触发了排队型任务（局部编辑/拆层等）：外层凭 run_id 挂进度条 */
  onQueuedRun?: (runId: string, tool: string) => void;
}) {
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  // 恢复现场：这个会话的历史对话轮
  const history = useQuery({
    queryKey: ["agentRuns", sessionId],
    queryFn: () => listSessionRuns(sessionId),
    enabled: Boolean(sessionId),
  });

  useEffect(() => {
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, history.data]);

  useEffect(() => {
    const runs = history.data ?? [];
    if (runs.length > 0 && messages.length === 0) {
      setMessages(
        runs.map((run) => ({
          role: "agent" as const,
          runId: run.id,
          text: run.instruction ? undefined : undefined,
        })),
      );
    }
  }, [history.data, messages.length]);

  const plan = useMutation({
    mutationFn: (instruction: string) => createPlan(sessionId, instruction),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({
        queryKey: ["agentRuns", sessionId],
      });
      setMessages((prev) => [...prev, { role: "agent", runId: run.id }]);
    },
    onError: (error) => {
      setMessages((prev) => [
        ...prev,
        { role: "agent", text: (error as Error).message },
      ]);
    },
  });

  function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || plan.isPending) return;
    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setInput("");
    plan.mutate(trimmed);
  }

  const busy = plan.isPending;

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50/60 select-none">
      {/* 对话顶栏控制 */}
      <div className="border-b border-slate-200 px-3 py-2 flex items-center justify-between shrink-0 bg-white">
        <div className="flex items-center gap-1.5 bg-slate-100 p-0.5 rounded-md">
          <button
            type="button"
            className="flex items-center gap-1 px-3 py-1 text-xs font-medium text-slate-800 bg-white rounded shadow-2xs"
          >
            <PlusOutlined className="text-[10px]" />
            <span>新对话</span>
          </button>
          <button
            type="button"
            className="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-800 rounded transition-colors"
          >
            历史
          </button>
        </div>
        <span className="text-[11px] text-slate-400 font-mono">AI Agent</span>
      </div>

      {/* 消息与执行卡片流 */}
      <div
        ref={listRef}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3.5"
      >
        {messages.length === 0 && (
          <div className="rounded-lg border border-dashed border-slate-200 bg-white/80 p-3.5 text-xs text-slate-500 leading-relaxed shadow-xs">
            <p className="font-medium text-slate-700 m-0 mb-1">
              自然语言指令编排
            </p>
            <p className="text-[11px] text-slate-400 m-0 mb-3">
              支持复合修改指令，AI 将自动分析并分解为可单步确认的执行计划。
            </p>
            <div className="flex flex-col gap-1.5">
              {SUGGESTIONS.map((text) => (
                <button
                  key={text}
                  type="button"
                  onClick={() => send(text)}
                  className="text-left text-xs text-blue-600 bg-blue-50/60 hover:bg-blue-50 hover:text-blue-700 border border-blue-100/80 px-2.5 py-1.5 rounded transition-all cursor-pointer truncate"
                >
                  {text}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message, index) =>
          message.role === "user" ? (
            <div key={index} className="flex justify-end">
              <div className="bg-blue-50/90 border border-blue-200/80 text-blue-900 rounded-lg px-3 py-2 text-xs max-w-[90%] shadow-2xs">
                {message.text}
              </div>
            </div>
          ) : message.runId ? (
            <PlanCard
              key={index}
              runId={message.runId}
              onQueuedRun={onQueuedRun}
              onChanged={onChanged}
            />
          ) : (
            <div
              key={index}
              className="rounded-md bg-red-50 border border-red-200 p-2 text-red-600 text-xs"
            >
              {message.text}
            </div>
          ),
        )}
      </div>

      {/* 底部一体化输入区 */}
      <div className="border-t border-slate-200 bg-white p-3 shrink-0">
        <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-2 transition-all focus-within:border-blue-400 focus-within:bg-white focus-within:shadow-xs">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            placeholder="说明要怎么改，例如：去背景再水平翻转。回车发送"
            disabled={busy}
            rows={2}
            className="w-full resize-none border-none bg-transparent p-0 text-xs text-slate-800 placeholder-slate-400 outline-none leading-relaxed"
          />
          <div className="mt-1.5 flex items-center justify-between pt-1 border-t border-slate-100">
            <span className="text-[10px] text-slate-400">
              Shift + Enter 换行
            </span>
            <Button
              type="primary"
              size="small"
              icon={<SendOutlined />}
              loading={busy}
              disabled={input.trim().length === 0}
              onClick={() => send(input)}
              className="h-6! px-2.5! text-xs! rounded!"
            >
              发送
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 单条计划卡片：对齐参考图1步骤流卡片设计 */
function PlanCard({
  runId,
  onQueuedRun,
  onChanged,
}: {
  runId: string;
  onQueuedRun?: (runId: string, tool: string) => void;
  onChanged?: () => void;
}) {
  const [run, setRun] = useState<AgentRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const reportedRef = useRef<string | null>(null);
  const [cotEpoch, setCotEpoch] = useState(0);
  const cot = useCotStream(runId, true, cotEpoch);

  const load = useCallback(async () => {
    try {
      setRun(await getAgentRun(runId));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const refreshOnClose = useRef(false);
  useEffect(() => {
    if (cot.closed && !refreshOnClose.current) {
      refreshOnClose.current = true;
      void load();
    }
    if (!cot.closed) refreshOnClose.current = false;
  }, [cot.closed, load]);

  const watching = run?.plan.find(
    (step) =>
      step.status === "queued" && step.run_id && step.tool !== "text_to_image",
  );
  const stream = useRunStream(watching?.run_id ?? null);

  useEffect(() => {
    if (watching?.run_id && reportedRef.current !== watching.run_id) {
      reportedRef.current = watching.run_id;
      onQueuedRun?.(watching.run_id, watching.tool);
    }
  }, [watching, onQueuedRun]);

  useEffect(() => {
    if (!watching?.run_id || !stream.closed || busy) return;
    if (stream.status === null) return;
    setBusy(true);
    continuePlan(runId, watching.run_id)
      .then((next) => {
        setRun(next);
        onChanged?.();
        setCotEpoch((prev) => prev + 1);
      })
      .catch((err) => setError((err as Error).message))
      .finally(() => setBusy(false));
  }, [stream.closed, watching?.run_id]);

  if (error && !run) {
    return <p className="text-red-500 text-xs">{error}</p>;
  }
  if (!run) {
    return (
      <div className="flex items-center gap-2 p-3 bg-white rounded-lg border border-slate-200 text-xs text-slate-400">
        <LoadingOutlined />
        <span>计划载入中…</span>
      </div>
    );
  }

  const act = async (action: () => Promise<AgentRun>) => {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      setRun(next);
      onChanged?.();
      setCotEpoch((prev) => prev + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const hasFailed = run.plan.some((step) => step.status === "failed");

  return (
    <div className="bg-white rounded-lg border border-slate-200 p-3 shadow-xs space-y-2 text-xs">
      {/* 头部状态 */}
      <div className="flex items-center justify-between pb-1.5 border-b border-slate-100">
        <div className="flex items-center gap-1.5">
          <StatusBadge status={run.status} />
          {run.error && (
            <span className="text-red-500 font-medium">{run.error}</span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setTraceOpen(true)}
          className="text-[11px] text-slate-400 hover:text-slate-600 flex items-center gap-1 cursor-pointer"
        >
          <FileSearchOutlined />
          <span>审计</span>
        </button>
      </div>

      <CoTStream
        items={cot.items}
        closed={cot.closed}
        defaultOpen={run.status === "planning"}
      />

      {run.reply && (
        <p className="text-slate-600 m-0 text-xs leading-relaxed font-normal">
          {run.reply}
        </p>
      )}

      {/* 结构化步骤列表（对齐参考图1） */}
      {run.plan.length > 0 && (
        <div className="space-y-1.5 pt-0.5">
          {run.plan.map((step, idx) => (
            <div
              key={step.id}
              className="flex items-center justify-between bg-slate-50/80 hover:bg-slate-50 border border-slate-100 rounded-md px-2.5 py-1.5 transition-colors"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-mono text-[11px] text-slate-400 font-semibold">
                  {idx + 1}.
                </span>
                <span className="font-medium text-slate-700 truncate">
                  {step.tool}
                </span>
                {step.message && (
                  <span className="text-[10px] text-slate-400 truncate max-w-30">
                    {step.message}
                  </span>
                )}
              </div>
              <StepStatusBadge status={step.status} />
            </div>
          ))}
        </div>
      )}

      {/* 动作按钮栏 */}
      {(run.status === "awaiting_confirm" ||
        (run.status === "failed" && hasFailed)) && (
        <div className="mt-2.5 flex items-center gap-2 pt-1 border-t border-slate-100">
          {run.status === "awaiting_confirm" && (
            <>
              <Button
                size="small"
                type="primary"
                icon={<CheckOutlined />}
                loading={busy}
                onClick={() => act(() => confirmPlan(run.id))}
                className="h-6! px-2.5! text-xs!"
              >
                开始执行
              </Button>
              <Button
                size="small"
                icon={<CloseOutlined />}
                disabled={busy}
                onClick={() => act(() => cancelPlan(run.id))}
                className="h-6! px-2.5! text-xs!"
              >
                取消
              </Button>
            </>
          )}
          {run.status === "failed" && hasFailed && (
            <Button
              size="small"
              icon={<RedoOutlined />}
              loading={busy}
              onClick={() => act(() => retryPlan(run.id))}
              className="h-6! px-2.5! text-xs!"
            >
              重试失败步骤
            </Button>
          )}
        </div>
      )}

      {error && <p className="text-red-500 m-0 text-xs">{error}</p>}
      <TraceModal
        runId={run.id}
        open={traceOpen}
        onClose={() => setTraceOpen(false)}
      />
    </div>
  );
}

function StepStatusBadge({ status }: { status: PlanStep["status"] }) {
  if (status === "succeeded") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full font-medium shrink-0">
        <CheckCircleFilled className="text-[9px]" />
        <span>已完成</span>
      </span>
    );
  }
  if (status === "running" || status === "queued") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-blue-700 bg-blue-50 px-2 py-0.5 rounded-full font-medium shrink-0">
        <SyncOutlined spin className="text-[9px]" />
        <span>执行中</span>
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-red-700 bg-red-50 px-2 py-0.5 rounded-full font-medium shrink-0">
        <CloseCircleFilled className="text-[9px]" />
        <span>失败</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[10px] text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full font-medium shrink-0">
      <ClockCircleOutlined className="text-[9px]" />
      <span>等待</span>
    </span>
  );
}

function StatusBadge({ status }: { status: AgentRun["status"] }) {
  const map: Record<AgentRun["status"], { text: string; color: string }> = {
    planning: { text: "规划中", color: "processing" },
    awaiting_confirm: { text: "待确认", color: "gold" },
    running: { text: "执行中", color: "processing" },
    succeeded: { text: "已完成", color: "success" },
    failed: { text: "失败", color: "error" },
    cancelled: { text: "已取消", color: "default" },
  };
  const item = map[status] || { text: status, color: "default" };
  return (
    <Tag
      bordered={false}
      color={item.color}
      className="m-0 text-[10px] leading-tight px-1.5 py-0.5"
    >
      {item.text}
    </Tag>
  );
}
