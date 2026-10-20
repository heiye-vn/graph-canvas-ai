/**
 * 导出物料页。
 *
 * 与顶栏的「下载 PNG」分工：
 *   - 顶栏 PNG：当前画布 1:1 原画，前端直出，零等待
 *   - 这里：把画布完整放进 1:1 / 4:5 / 9:16 三档投放位（补边不裁切），
 *     勾选后打包 ZIP（含 manifest.json）
 *
 * 尺寸图由服务端拍平生成（含调色/裁剪/旋转），所以生成后是「一批资产」，
 * 刷新页面不会保留 —— 重新生成即可，结果也挂在会话素材里。
 */

import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Button,
  Checkbox,
  Empty,
  Result,
  Select,
  Skeleton,
  message,
} from "antd";
import {
  ArrowLeftOutlined,
  CheckOutlined,
  DownloadOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";

import type { AssetOut } from "@/api/assets";
import {
  DELIVERY_RATIOS,
  RATIO_SIZES,
  createExportSizes,
  downloadExportZip,
} from "@/api/exports";
import type { DeliveryRatio } from "@/api/exports";
import { getSession, listSessions } from "@/api/sessions";
import type { SessionOut } from "@/api/sessions";
import { topmostVisibleImageLayer } from "@/domain/layerDoc";

export default function ExportPage() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();

  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => getSession(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
  });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: listSessions });

  const [ratios, setRatios] = useState<DeliveryRatio[]>([...DELIVERY_RATIOS]);
  const [items, setItems] = useState<AssetOut[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [packing, setPacking] = useState(false);

  const generate = useMutation({
    mutationFn: () => createExportSizes(sessionId, ratios),
    onSuccess: (result) => {
      setItems(result.items);
      setSelected(result.items.map((item) => item.id));
      message.success(`已生成 ${result.items.length} 张投放尺寸`);
    },
    onError: (error) => message.error((error as Error).message),
  });

  const data = session.data as SessionOut | undefined;
  const coverUrl = useMemo(() => {
    if (!data) return null;
    const layer = topmostVisibleImageLayer(data.doc);
    const assetId = layer?.source?.asset_id;
    return data.assets.find((asset) => asset.id === assetId)?.url ?? null;
  }, [data]);

  if (session.isLoading) {
    return (
      <div className="mx-auto max-w-4xl px-8 py-10">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    );
  }

  if (session.isError || !data) {
    return (
      <Result
        status="404"
        title="找不到这个编辑会话"
        extra={
          <Link to="/assets">
            <Button type="primary">去素材库</Button>
          </Link>
        }
      />
    );
  }

  const allSelected = items.length > 0 && selected.length === items.length;

  function toggleRatio(ratio: DeliveryRatio) {
    setRatios((prev) =>
      prev.includes(ratio) ? prev.filter((item) => item !== ratio) : [...prev, ratio],
    );
  }

  function toggleItem(assetId: string) {
    setSelected((prev) =>
      prev.includes(assetId)
        ? prev.filter((id) => id !== assetId)
        : [...prev, assetId],
    );
  }

  async function pack() {
    if (selected.length === 0) return;
    setPacking(true);
    try {
      await downloadExportZip(
        sessionId,
        selected,
        `${data?.title || "export"}-物料.zip`,
      );
      message.success(`已打包 ${selected.length} 张`);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setPacking(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-slate-50">
      <div className="mx-auto max-w-4xl px-8 py-8">
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="m-0 text-xl font-semibold text-slate-900">导出物料</h1>
            <p className="mb-0 mt-1 text-sm text-slate-500">
              把当前画布完整放进投放比例（补边不裁切），勾选后打包下载。
            </p>
          </div>
          <Link
            to={`/editor/${sessionId}`}
            className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 no-underline transition-colors hover:bg-slate-50 hover:text-slate-900"
          >
            <ArrowLeftOutlined className="text-[11px]" />
            返回编辑器
          </Link>
        </div>

        {/* 当前会话 */}
        <section className="mb-5 rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-4">
            {coverUrl ? (
              <img
                src={coverUrl}
                alt={data.title}
                className="h-16 w-16 shrink-0 rounded-md object-cover ring-1 ring-slate-200"
              />
            ) : (
              <div className="h-16 w-16 shrink-0 rounded-md bg-slate-100" />
            )}
            <div className="min-w-0 flex-1">
              <p className="m-0 truncate text-sm font-medium text-slate-900">
                {data.title || "未命名会话"}
              </p>
              <p className="m-0 mt-1 text-xs text-slate-500">
                画布 {data.doc.canvas.width} × {data.doc.canvas.height}
              </p>
            </div>
            <Select
              value={sessionId}
              className="w-56"
              placeholder="切换会话"
              options={(sessions.data ?? []).map((item) => ({
                value: item.id,
                label: item.title,
              }))}
              onChange={(id: string) => navigate(`/editor/${id}/export`)}
            />
          </div>
        </section>

        {/* 投放尺寸 */}
        <section className="mb-5 rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="m-0 text-sm font-semibold text-slate-900">投放尺寸</h2>
          <p className="mb-3 mt-1 text-[11px] text-slate-500">
            完整放入目标画幅，不裁切；多出来的部分用画布背景色补齐。
          </p>

          <div className="grid grid-cols-3 gap-2.5">
            {DELIVERY_RATIOS.map((ratio) => {
              const active = ratios.includes(ratio);
              return (
                <button
                  key={ratio}
                  type="button"
                  onClick={() => toggleRatio(ratio)}
                  className={`flex cursor-pointer flex-col items-start gap-1 rounded-md border px-3 py-2.5 text-left transition-colors ${
                    active
                      ? "border-blue-400 bg-blue-50/60"
                      : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                  }`}
                >
                  <span className="flex items-center gap-1.5 text-sm font-medium text-slate-800">
                    {active && <CheckOutlined className="text-[11px] text-blue-600" />}
                    {ratio}
                  </span>
                  <span className="font-mono text-[11px] text-slate-500 tabular-nums">
                    {RATIO_SIZES[ratio]}
                  </span>
                </button>
              );
            })}
          </div>

          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={generate.isPending}
            disabled={ratios.length === 0}
            onClick={() => generate.mutate()}
            className="mt-4 text-xs"
          >
            生成投放尺寸
          </Button>
        </section>

        {/* 导出清单 */}
        <section className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-3 flex items-start justify-between gap-4">
            <div>
              <h2 className="m-0 text-sm font-semibold text-slate-900">导出清单</h2>
              <p className="mb-0 mt-1 text-[11px] text-slate-500">
                勾选要进 ZIP 的图片，包内含 manifest.json（标题、张数、每张尺寸）。
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Checkbox
                checked={allSelected}
                indeterminate={selected.length > 0 && !allSelected}
                disabled={items.length === 0}
                onChange={() =>
                  setSelected(allSelected ? [] : items.map((item) => item.id))
                }
                className="text-xs"
              >
                全选
              </Checkbox>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                loading={packing}
                disabled={selected.length === 0}
                onClick={pack}
                className="text-xs"
              >
                打包 {selected.length} 张
              </Button>
            </div>
          </div>

          {items.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <span className="text-xs text-slate-400">
                  还没有生成投放尺寸
                </span>
              }
            />
          ) : (
            <div className="grid grid-cols-4 gap-3">
              {items.map((item) => {
                const checked = selected.includes(item.id);
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => toggleItem(item.id)}
                    className={`group relative cursor-pointer overflow-hidden rounded-md border bg-slate-50 transition-all ${
                      checked
                        ? "border-blue-500 ring-2 ring-blue-500/20"
                        : "border-slate-200 hover:border-slate-300"
                    }`}
                  >
                    <img
                      src={item.url}
                      alt={`${item.width}×${item.height}`}
                      className="aspect-square w-full object-contain"
                    />
                    <span
                      className={`absolute left-2 top-2 flex h-4 w-4 items-center justify-center rounded-full border text-[9px] ${
                        checked
                          ? "border-blue-500 bg-blue-500 text-white"
                          : "border-white/80 bg-black/20 text-transparent"
                      }`}
                    >
                      <CheckOutlined />
                    </span>
                    <span className="absolute inset-x-0 bottom-0 bg-black/55 px-2 py-1 text-center font-mono text-[10px] text-white tabular-nums">
                      {item.width} × {item.height}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
