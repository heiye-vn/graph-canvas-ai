/**
 * 左侧对话与 Agent 多步执行面板。
 *
 * 1. 一轮对话 = 一条 AgentRun：用户指令气泡 + 计划卡片成对出现
 * 2. 气泡对比：用户实心品牌蓝（右）vs 系统白底卡片（左），扫一眼就能分清谁说的
 * 3. 长内容不截断：回复正文展开/收起，步骤说明完整换行显示
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Popover, Tag } from "antd";
import {
  CheckCircleFilled,
  CheckOutlined,
  ClockCircleOutlined,
  CloseCircleFilled,
  CloseOutlined,
  FileSearchOutlined,
  HistoryOutlined,
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

const RUN_STATUS_META: Record<
  AgentRun["status"],
  { text: string; color: string }
> = {
  planning: { text: "规划中", color: "processing" },
  awaiting_confirm: { text: "待确认", color: "gold" },
  running: { text: "执行中", color: "processing" },
  succeeded: { text: "已完成", color: "success" },
  failed: { text: "失败", color: "error" },
  cancelled: { text: "已取消", color: "default" },
};

/** 回复超过这个长度就折成三行，给「展开全文」 */
const REPLY_COLLAPSE_CHARS = 120;

/**
 * 一轮对话 = 一条 AgentRun（含 instruction 与 plan）。
 * 恢复现场时必须把用户指令一起还原：只贴计划卡片，用户就看不到自己说过什么。
 */
function runsToMessages(runs: AgentRun[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const run of runs) {
    const instruction = run.instruction?.trim();
    if (instruction) out.push({ role: "user", text: instruction });
    out.push({ role: "agent", runId: run.id });
  }
  return out;
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  const hhmm = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay
    ? hhmm
    : `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${hhmm}`;
}

/**
 * 长文本展开/收起：短文本原样渲染（零开销），
 * 长文本默认折成三行，点「展开全文」看完整内容。
 */
function ExpandableText({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  if (text.length <= REPLY_COLLAPSE_CHARS) {
    return (
      <p
        className={`m-0 whitespace-pre-wrap wrap-break-word ${className ?? ""}`}
      >
        {text}
      </p>
    );
  }
  return (
    <div>
      <p
        className={`m-0 whitespace-pre-wrap wrap-break-word ${expanded ? "" : "line-clamp-3"} ${className ?? ""}`}
      >
        {text}
      </p>
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="mt-1 cursor-pointer text-[11px] font-medium text-blue-600 transition-colors hover:text-blue-700"
      >
        {expanded ? "收起" : "展开全文"}
      </button>
    </div>
  );
}

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
  /** 历史是否已灌入过：点过「新对话」或已恢复过就不再回灌，否则清空后又被填满 */
  const restoredRef = useRef(false);
  const messagesRef = useRef<ChatMessage[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  /** 从「历史」跳转过来的那一轮，滚动定位并高亮 */
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  // 恢复现场：这个会话的历史对话轮
  const history = useQuery({
    queryKey: ["agentRuns", sessionId],
    queryFn: () => listSessionRuns(sessionId),
    enabled: Boolean(sessionId),
  });

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    if (restoredRef.current) return;
    const runs = history.data ?? [];
    if (runs.length === 0) return;
    // 用户抢在历史返回前已经开口了：本地对话优先，历史通过「历史」面板回看
    if (messagesRef.current.length > 0) {
      restoredRef.current = true;
      return;
    }
    restoredRef.current = true;
    setMessages(runsToMessages(runs));
  }, [history.data]);

  // 从「历史」选中某一轮后滚动定位（卡片内容是异步载入的，落定后再校正一次）
  useEffect(() => {
    if (!activeRunId) return;
    const scrollToTarget = (smooth: boolean) => {
      const el = listRef.current?.querySelector(
        `[data-run-id="${activeRunId}"]`,
      );
      if (!el) return;
      el.scrollIntoView(
        smooth ? { block: "center", behavior: "smooth" } : { block: "center" },
      );
    };
    const first = window.setTimeout(() => scrollToTarget(true), 80);
    const settle = window.setTimeout(() => scrollToTarget(false), 400);
    return () => {
      window.clearTimeout(first);
      window.clearTimeout(settle);
    };
  }, [activeRunId, messages]);

  useEffect(() => {
    // 刚从历史定位过来时不要抢滚动，否则会被拽回底部
    if (activeRunId) return;
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, activeRunId]);

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
    restoredRef.current = true;
    setActiveRunId(null);
    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setInput("");
    plan.mutate(trimmed);
  }

  /** 新对话：只清空当前视图，历史仍留在服务端，「历史」里可以回看 */
  function startNewChat() {
    restoredRef.current = true;
    setMessages([]);
    setInput("");
    setActiveRunId(null);
    setHistoryOpen(false);
  }

  /** 从历史里挑一轮：恢复完整对话流并定位到那一轮 */
  function jumpToRun(runId: string) {
    const runs = history.data ?? [];
    restoredRef.current = true;
    setMessages(runsToMessages(runs));
    setActiveRunId(runId);
    setHistoryOpen(false);
  }

  const busy = plan.isPending;

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50/60">
      {/* 顶栏：标题 + 两个动作。不做胶囊分段控件 —— 那是模板，不是产品 */}
      <div className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 py-2.5">
        <span className="text-[13px] font-semibold text-slate-700">对话</span>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={startNewChat}
            disabled={busy}
            title="新对话"
            className="flex cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <PlusOutlined className="text-[10px]" />
            <span>新对话</span>
          </button>
          <Popover
            trigger="click"
            placement="bottomRight"
            arrow={false}
            open={historyOpen}
            onOpenChange={setHistoryOpen}
            content={
              history.isError ? (
                <Alert
                  type="error"
                  showIcon
                  message="对话历史加载失败"
                  description={history.error.message}
                  action={
                    <Button size="small" onClick={() => void history.refetch()}>
                      重试
                    </Button>
                  }
                />
              ) : (
                <HistoryList
                  runs={history.data ?? []}
                  loading={history.isLoading}
                  activeRunId={activeRunId}
                  onPick={jumpToRun}
                />
              )
            }
          >
            <button
              type="button"
              disabled={busy}
              title="历史对话"
              className="flex cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <HistoryOutlined className="text-[11px]" />
              <span>历史</span>
            </button>
          </Popover>
        </div>
      </div>

      {/* 消息与执行卡片流 */}
      <div
        ref={listRef}
        className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4"
      >
        {history.isError && (
          <Alert
            type="error"
            showIcon
            message="对话历史加载失败"
            description={history.error.message}
            action={
              <Button size="small" onClick={() => void history.refetch()}>
                重试
              </Button>
            }
          />
        )}
        {messages.length === 0 &&
          !history.isError &&
          (history.isLoading ? (
            <div className="flex items-center gap-2 p-3 text-[13px] text-slate-400">
              <LoadingOutlined />
              <span>对话载入中…</span>
            </div>
          ) : (
            <div className="pt-2">
              <p className="m-0 text-[15px] font-semibold text-slate-800">
                想怎么改这张图？
              </p>
              <p className="m-0 mt-1 text-xs leading-relaxed text-slate-400">
                用大白话说就行，支持多步指令，AI 会先列出执行计划等你确认。
              </p>
              <div className="mt-4 flex flex-col gap-1">
                {SUGGESTIONS.map((text) => (
                  <button
                    key={text}
                    type="button"
                    onClick={() => send(text)}
                    className="group flex cursor-pointer items-center justify-between rounded-lg px-3 py-2.5 text-left text-[13px] text-slate-600 transition-colors hover:bg-white hover:text-blue-600 hover:shadow-xs"
                  >
                    <span>{text}</span>
                    <span className="text-slate-300 transition-all group-hover:translate-x-0.5 group-hover:text-blue-500">
                      →
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}

        {messages.map((message, index) =>
          message.role === "user" ? (
            <div key={index} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-md bg-blue-600 px-3.5 py-2.5 text-[13px] leading-relaxed text-white shadow-sm">
                {message.text}
              </div>
            </div>
          ) : message.runId ? (
            <div
              key={index}
              data-run-id={message.runId}
              className={
                activeRunId === message.runId
                  ? "rounded-xl ring-1 ring-blue-300/80 transition-shadow"
                  : "rounded-xl"
              }
            >
              <PlanCard
                runId={message.runId}
                onQueuedRun={onQueuedRun}
                onChanged={onChanged}
              />
            </div>
          ) : (
            <div className="rounded-xl border border-red-200 bg-red-50 px-3.5 py-2.5 text-[13px] leading-relaxed text-red-600">
              {message.text}
            </div>
          ),
        )}
      </div>

      {/* 底部输入区 */}
      <div className="shrink-0 border-t border-slate-200 bg-white p-3.5">
        <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-2.5 transition-all focus-within:border-blue-400 focus-within:bg-white focus-within:shadow-xs">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229)
                return;
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            placeholder="说明要怎么改，例如：去背景再水平翻转"
            disabled={busy}
            rows={2}
            className="w-full resize-none border-none bg-transparent p-0 text-[13px] leading-relaxed text-slate-800 placeholder-slate-400 outline-none"
          />
          <div className="mt-1.5 flex items-center justify-between border-t border-slate-100 pt-2">
            <span className="text-[11px] text-slate-400">
              回车发送 · Shift + 回车换行
            </span>
            <Button
              type="primary"
              size="small"
              icon={<SendOutlined />}
              loading={busy}
              disabled={input.trim().length === 0}
              onClick={() => send(input)}
              className="h-7! px-3! text-[13px]! rounded-lg!"
            >
              发送
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 单条计划卡片：状态头 + CoT + 回复正文 + 步骤列表 + 动作栏 */
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
    return <p className="text-[13px] text-red-500">{error}</p>;
  }
  if (!run) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-3.5 text-[13px] text-slate-400">
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
    <div className="space-y-2.5 rounded-xl border border-slate-200 bg-white p-3.5 text-[13px] shadow-xs">
      {/* 头部状态 */}
      <div className="flex items-center justify-between border-b border-slate-100 pb-2">
        <div className="flex items-center gap-1.5">
          <StatusBadge status={run.status} />
          {run.error && (
            <span className="font-medium text-red-500">{run.error}</span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setTraceOpen(true)}
          className="flex cursor-pointer items-center gap-1 text-xs text-slate-400 transition-colors hover:text-slate-600"
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
        <ExpandableText
          text={run.reply}
          className="text-[13px] leading-relaxed text-slate-600"
        />
      )}

      {/* 步骤列表：说明文字完整换行，不截断 */}
      {run.plan.length > 0 && (
        <div className="space-y-1.5 pt-0.5">
          {run.plan.map((step, idx) => (
            <div
              key={step.id}
              className="rounded-lg border border-slate-100 bg-slate-50/80 px-3 py-2 transition-colors hover:bg-slate-50"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="font-mono text-xs font-semibold text-slate-400">
                    {idx + 1}.
                  </span>
                  <span className="truncate font-medium text-slate-700">
                    {step.tool}
                  </span>
                </div>
                <StepStatusBadge status={step.status} />
              </div>
              {step.message && (
                <p className="m-0 mt-1 wrap-break-word pl-5 text-xs leading-relaxed text-slate-400">
                  {step.message}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 动作按钮栏 */}
      {(run.status === "awaiting_confirm" ||
        (run.status === "failed" && hasFailed)) && (
        <div className="mt-2.5 flex items-center gap-2 border-t border-slate-100 pt-2.5">
          {run.status === "awaiting_confirm" && (
            <>
              <Button
                size="small"
                type="primary"
                icon={<CheckOutlined />}
                loading={busy}
                onClick={() => act(() => confirmPlan(run.id))}
                className="h-7! px-3! text-[13px]! rounded-lg!"
              >
                开始执行
              </Button>
              <Button
                size="small"
                icon={<CloseOutlined />}
                disabled={busy}
                onClick={() => act(() => cancelPlan(run.id))}
                className="h-7! px-3! text-[13px]! rounded-lg!"
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
              className="h-7! px-3! text-[13px]! rounded-lg!"
            >
              重试失败步骤
            </Button>
          )}
        </div>
      )}

      {error && <p className="m-0 text-[13px] text-red-500">{error}</p>}
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
      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
        <CheckCircleFilled className="text-[10px]" />
        <span>已完成</span>
      </span>
    );
  }
  if (status === "running" || status === "queued") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
        <SyncOutlined spin className="text-[10px]" />
        <span>执行中</span>
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700">
        <CloseCircleFilled className="text-[10px]" />
        <span>失败</span>
      </span>
    );
  }
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-400">
      <ClockCircleOutlined className="text-[10px]" />
      <span>等待</span>
    </span>
  );
}

function StatusBadge({ status }: { status: AgentRun["status"] }) {
  const item = RUN_STATUS_META[status] ?? { text: status, color: "default" };
  return (
    <Tag
      bordered={false}
      color={item.color}
      className="m-0 px-2 py-0.5 text-[11px] leading-tight"
    >
      {item.text}
    </Tag>
  );
}

/** 历史对话轮列表（「历史」按钮的下拉面板） */
function HistoryList({
  runs,
  loading,
  activeRunId,
  onPick,
}: {
  runs: AgentRun[];
  loading: boolean;
  activeRunId: string | null;
  onPick: (runId: string) => void;
}) {
  if (loading) {
    return (
      <div className="flex w-72 items-center gap-2 px-1 py-3 text-[13px] text-slate-400">
        <LoadingOutlined />
        <span>历史加载中…</span>
      </div>
    );
  }
  if (runs.length === 0) {
    return (
      <div className="w-72 px-1 py-3 text-[13px] text-slate-400">
        这个会话还没有对话记录。
      </div>
    );
  }
  return (
    <div className="w-72">
      <div className="max-h-80 overflow-y-auto pr-0.5">
        <p className="m-0 mb-1 px-1.5 text-xs font-medium text-slate-400">
          本会话共 {runs.length} 轮，点击回看
        </p>
        <div className="flex flex-col gap-0.5">
          {runs.map((run, index) => (
            <button
              key={run.id}
              type="button"
              onClick={() => onPick(run.id)}
              className={`w-full cursor-pointer rounded-md px-2 py-1.5 text-left transition-colors ${
                activeRunId === run.id ? "bg-blue-50" : "hover:bg-slate-50"
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span className="shrink-0 font-mono text-[11px] text-slate-400">
                  #{index + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px] text-slate-700">
                  {run.instruction?.trim() || "（未记录指令）"}
                </span>
              </div>
              <div className="mt-0.5 flex items-center gap-1 pl-5 text-[11px] text-slate-400">
                <span>{formatWhen(run.created_at)}</span>
                <span>·</span>
                <span>{RUN_STATUS_META[run.status]?.text ?? run.status}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
