// アンカー管理: 登録済みアンカーの表（試聴・外す・削除）と、外したアンカーの表（戻す・削除）をタブで切り替える。
// 外す・戻す・削除をしても、その行はそのページを見ている間は同じ位置に残す（「外しました・戻す」などを出す）。
// 行が詰まって押そうとした場所が動くのを防ぐため。ページ・タブ・絞り込み・並べ替えを変えると詰める。
// 表の数値は「声の設定」のスライダーと同じ尺度（0〜100）。いまのアンカー全体の中での相対位置なので、
// アンカーを足したり外したりすると変わる。絞り込みもこの値で行う。
// 同梱のアンカーは外すだけ（いつでも戻せる）。自分で足したアンカーは完全に削除もできる。
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  Play, Pause, Undo2, ChevronRight, ChevronLeft, ChevronsLeft, ChevronsRight, Trash2, Package, UserPlus,
  ArrowUp, ArrowDown, RotateCcw, Crosshair, AlertTriangle,
} from 'lucide-react';
import { canvaApi } from '@/lib/api/canvaApi';
import { axisMeta } from '@/lib/axisMeta';
import { useCanvaStore } from '@/stores/canvaStore';
import type { AnchorOverview, Axis } from '@/types/canva';

interface Props {
  data: AnchorOverview;
  onUpdate: (d: AnchorOverview) => void;
  onError: (msg: string) => void;
}

type Origin = 'all' | 'bundled' | 'custom';
// 並べ替え: 軸のキー・名前・声の高さ・品質、または「いまの声の設定に近い順」
type SortKey = string;
const NEAR = '__near';
const PAGE_SIZES = [20, 50, 100];

export default function AnchorList({ data, onUpdate, onError }: Props) {
  const [axes, setAxes] = useState<Axis[]>(useCanvaStore.getState().axes);
  const designSliders = useCanvaStore((s) => s.sliders);
  const [playing, setPlaying] = useState<string | null>(null);
  // 確認中の操作（外す／完全に削除）
  const [confirm, setConfirm] = useState<{ name: string; act: 'exclude' | 'delete' } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<'active' | 'excluded'>('active');
  const audio = useRef<HTMLAudioElement | null>(null);

  // 絞り込み: 軸ごとの範囲（0〜100）と出どころ
  const [ranges, setRanges] = useState<Record<string, [number, number]>>({});
  const [origin, setOrigin] = useState<Origin>('all');
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'name', desc: false });
  // ページ送り（表は1ページずつ見せる）
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  // 操作した直後に見えていた行の並び。これがある間は行を詰めない
  const [frozen, setFrozen] = useState<string[] | null>(null);
  // 削除した名前（削除後もその場に「削除しました」と残すため）
  const [deleted, setDeleted] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (axes.length === 0) canvaApi.axes().then(setAxes).catch(() => onError('軸の情報を取れませんでした'));
  }, [axes.length, onError]);
  useEffect(() => () => { audio.current?.pause(); }, []);

  const toggle = (name: string) => {
    if (!audio.current) {
      audio.current = new Audio();
      audio.current.onended = () => setPlaying(null);
    }
    const el = audio.current;
    if (playing === name) { el.pause(); setPlaying(null); return; }
    el.src = canvaApi.anchorAudioUrl(name);
    el.play().then(() => setPlaying(name)).catch(() => onError('試聴音声を再生できませんでした'));
  };

  const hasDesign = axes.length > 0 && axes.some((a) => designSliders[a.key] !== undefined);
  // いまの声の設定との距離（8軸のユークリッド距離）
  const dist = (s: Record<string, number>) =>
    Math.sqrt(axes.reduce((acc, a) => acc + ((s[a.key] ?? 50) - (designSliders[a.key] ?? 50)) ** 2, 0));

  const rows = useMemo(() => {
    const r = data.anchors.filter((a) => {
      if (origin === 'bundled' && !a.bundled) return false;
      if (origin === 'custom' && a.bundled) return false;
      return axes.every((ax) => {
        const [lo, hi] = ranges[ax.key] ?? [0, 100];
        const v = Math.round(a.sliders[ax.key] ?? 50);
        return v >= lo && v <= hi;
      });
    });
    const val = (a: (typeof r)[number]): number | string =>
      sort.key === 'name' ? a.name
        : sort.key === 'f0' ? a.f0
        : sort.key === 'quality' ? a.quality ?? -1
        : sort.key === NEAR ? dist(a.sliders)
        : a.sliders[sort.key] ?? 50;
    return [...r].sort((x, y) => {
      const a = val(x), b = val(y);
      const c = typeof a === 'string' ? a.localeCompare(String(b), 'ja', { numeric: true }) : a - (b as number);
      return sort.desc ? -c : c;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.anchors, origin, ranges, axes, sort, designSliders]);
  const exRows = data.excluded;

  const filtered = origin !== 'all' || Object.values(ranges).some(([lo, hi]) => lo > 0 || hi < 100);
  // 絞り込み・並べ替え・件数・タブを変えたら1ページ目に戻る
  useEffect(() => { setPage(0); }, [origin, ranges, sort, pageSize, tab]);
  // ページ・タブ・絞り込み・並べ替えが変わったら、残しておいた行を詰める
  useEffect(() => { setFrozen(null); setConfirm(null); }, [origin, ranges, sort, pageSize, tab, page]);

  const list = tab === 'active' ? rows.map((a) => a.name) : exRows.map((x) => x.name);
  const pages = Math.max(1, Math.ceil(list.length / pageSize));
  const cur = Math.min(page, pages - 1);
  const shownNames = frozen ?? list.slice(cur * pageSize, (cur + 1) * pageSize);
  const byActive = useMemo(() => new Map(data.anchors.map((a) => [a.name, a])), [data.anchors]);
  const byEx = useMemo(() => new Map(data.excluded.map((x) => [x.name, x])), [data.excluded]);
  const n = data.anchors.length;

  // 操作の前に、いま見えている並びを固定する
  const run = async (name: string, fn: () => Promise<AnchorOverview>, del = false) => {
    setFrozen((f) => f ?? shownNames);
    setBusy(name);
    try {
      onUpdate(await fn());
      if (del) setDeleted((d) => new Set(d).add(name));
    } catch (e) { onError(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(null); setConfirm(null); }
  };

  // 表の高さは、外す・戻す・削除で低くしない（下の操作位置がずれないように）
  const box = useRef<HTMLDivElement | null>(null);
  const [minH, setMinH] = useState(0);
  // 自分で条件を変えたとき（タブ・件数・絞り込み・並べ替え・ページ）は高さを測り直す
  useEffect(() => { setMinH(0); }, [tab, pageSize, origin, ranges, sort, page]);
  useLayoutEffect(() => {
    const h = box.current?.offsetHeight ?? 0;
    if (h > minH) setMinH(h);
  });

  const setSortKey = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key !== 'name' && key !== NEAR }));
  // いまの声の設定に近い順に並べる（作ろうとしている声の材料になりそうなアンカーが上に来る）。
  // 8軸すべてを範囲で絞ると誰も残らないので、絞り込みではなく並べ替えにする
  const nearDesign = () => setSort({ key: NEAR, desc: false });
  const cols = axes.length + (sort.key === NEAR ? 6 : 5);

  const tabBtn = (t: 'active' | 'excluded', label: string, count: number) => (
    <button onClick={() => setTab(t)} role="tab" aria-selected={tab === t}
      className={`px-4 h-10 rounded-xl text-sm inline-flex items-center gap-2 border transition ${
        tab === t ? 'border-accent bg-accent/20 text-white font-bold' : 'border-line text-sub hover:text-white'}`}>
      {label}<span className="tabular-nums text-xs px-1.5 rounded-full bg-black/30">{count}</span>
    </button>
  );

  return (
    <section className="bg-panel border border-line rounded-2xl p-5 space-y-4 min-w-0">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div role="tablist" aria-label="アンカーの一覧" className="flex gap-2">
          {tabBtn('active', '使用中のアンカー', n)}
          {tabBtn('excluded', '外したアンカー', data.excluded.length)}
        </div>
        <p className="text-xs text-sub">数値は「声の設定」のスライダーと同じ0〜100で、いまのアンカー全体の中での位置を表します</p>
      </div>

      {tab === 'active' && (
        <div className="rounded-2xl bg-panel2 border border-line p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-bold mr-1">絞り込み</span>
            {([['all', 'すべて'], ['bundled', '同梱'], ['custom', '自分で追加']] as [Origin, string][]).map(([k, label]) => (
              <button key={k} onClick={() => setOrigin(k)}
                className={`text-xs px-3 py-1 rounded-full border transition ${origin === k ? 'border-accent bg-accent/20 text-white font-bold' : 'border-line text-sub hover:text-white'}`}>
                {label}
              </button>
            ))}
            {filtered && <span className="text-xs text-sub tabular-nums">{rows.length} / {n}人</span>}
            <span className="flex-1" />
            {hasDesign && (
              <button onClick={nearDesign} title="声の設定のスライダーの値に近いアンカーから順に並べます"
                className={`btn text-xs ${sort.key === NEAR ? 'border-accent text-white' : ''}`}>
                <Crosshair size={13} />いまの声の設定に近い順
              </button>
            )}
            <button onClick={() => { setRanges({}); setOrigin('all'); setSort({ key: 'name', desc: false }); }}
              disabled={!filtered && sort.key === 'name'} className="btn text-xs"><RotateCcw size={13} />リセット</button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-3">
            {axes.map((a) => (
              <RangeFilter key={a.key} axis={a} value={ranges[a.key] ?? [0, 100]}
                onChange={(v) => setRanges((r) => ({ ...r, [a.key]: v }))} />
            ))}
          </div>
        </div>
      )}

      <div ref={box} style={{ minHeight: minH || undefined }} className="space-y-4">
        <div className="overflow-x-auto rounded-xl border border-line">
          {tab === 'active' ? (
            <table className="w-full min-w-[1080px] text-sm border-collapse">
              <thead className="bg-panel2 text-xs text-sub">
                <tr>
                  <th className="w-12" />
                  {sort.key === NEAR && <th className="px-2 py-2 font-normal text-right whitespace-nowrap">近さ</th>}
                  <Th label="名前" k="name" sort={sort} onSort={setSortKey} align="left" />
                  {axes.map((a) => {
                    const { color, Icon } = axisMeta(a.key);
                    return <Th key={a.key} k={a.key} sort={sort} onSort={setSortKey}
                      label={<span className="inline-flex items-center gap-1" style={{ color }}><Icon size={12} />{a.label}</span>} />;
                  })}
                  <Th label="高さ（Hz）" k="f0" sort={sort} onSort={setSortKey} />
                  <Th label="品質" k="quality" sort={sort} onSort={setSortKey} />
                  <th className="px-3 py-2 text-right font-normal">操作</th>
                </tr>
              </thead>
              <tbody>
                {shownNames.length === 0 && (
                  <tr><td colSpan={cols} className="text-center text-sub py-10">
                    {n === 0 ? '使用中のアンカーはいません。「外したアンカー」から戻すか、「素材を追加」から録音を追加してください'
                      : '条件に合うアンカーがいません'}
                  </td></tr>
                )}
                {shownNames.map((name) => {
                  const a = byActive.get(name);
                  if (!a) {
                    // 外した・削除した行は、その場に残して状態を出す
                    const gone = deleted.has(name) || !byEx.has(name);
                    return (
                      <tr key={name} className="border-t border-line bg-black/20">
                        <td className="pl-3 py-2"><span className="block w-8 h-8" /></td>
                        {sort.key === NEAR && <td />}
                        <td className="px-3 py-2 text-sub line-through">{name}</td>
                        <td colSpan={axes.length + 2} className="px-3 py-2 text-xs text-sub">{gone ? '削除しました' : '外しました'}</td>
                        <td className="px-3 py-2 text-right">
                          {!gone && (
                            <button disabled={busy === name} onClick={() => run(name, () => canvaApi.restoreAnchor(name))}
                              className="text-xs inline-flex items-center gap-1 text-accent2 hover:brightness-125"><Undo2 size={13} />戻す</button>
                          )}
                        </td>
                      </tr>
                    );
                  }
                  return (
                    <tr key={a.name} className="border-t border-line hover:bg-panel2/60">
                      <td className="pl-3 py-2">
                        <button onClick={() => toggle(a.name)} aria-label={`${a.name}を試聴`}
                          className="w-8 h-8 rounded-full bg-accent grid place-items-center text-white hover:brightness-110">
                          {playing === a.name ? <Pause size={14} /> : <Play size={14} className="ml-0.5" />}
                        </button>
                      </td>
                      {sort.key === NEAR && (
                        <td className="px-2 py-2 text-right font-mono tabular-nums text-xs text-accent2">
                          {Math.max(0, Math.round(100 - dist(a.sliders) / Math.sqrt(axes.length)))}
                        </td>
                      )}
                      <td className="px-3 py-2 min-w-[170px] max-w-[240px]">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold truncate">{a.name}</span>
                          <OriginBadge bundled={a.bundled} />
                          {a.warnings?.length > 0 && (
                            <span title={a.warnings.join('\n')}
                              className="shrink-0 text-[11px] px-1.5 py-0.5 rounded-full inline-flex items-center gap-1 text-amber-300 bg-amber-300/15 cursor-help">
                              <AlertTriangle size={11} />注意
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] text-sub truncate" title={a.source}>{a.source || '素材名なし'}</div>
                      </td>
                      {axes.map((ax) => <ValueCell key={ax.key} v={a.sliders[ax.key] ?? 50} color={axisMeta(ax.key).color} />)}
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-xs">{Math.round(a.f0)}</td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-xs">{a.quality != null ? a.quality.toFixed(2) : '—'}</td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        {confirm?.name === a.name ? (
                          <Confirm
                            message={confirm.act === 'delete'
                              ? '完全に削除します。元に戻せません。'
                              : n - 1 < data.min_anchors ? `${data.min_anchors}人を下回り、声を作れなくなります。` : 'あとで戻せます。'}
                            label={confirm.act === 'delete' ? '削除する' : '外す'}
                            busy={busy === a.name}
                            onYes={() => confirm.act === 'delete'
                              ? run(a.name, () => canvaApi.deleteAnchor(a.name), true)
                              : run(a.name, () => canvaApi.excludeAnchor(a.name))}
                            onNo={() => setConfirm(null)} />
                        ) : (
                          <span className="inline-flex items-center gap-3">
                            <button onClick={() => setConfirm({ name: a.name, act: 'exclude' })} className="text-xs text-sub hover:text-[#ff8aa3]">外す</button>
                            {!a.bundled && (
                              <button onClick={() => setConfirm({ name: a.name, act: 'delete' })}
                                className="text-xs text-sub hover:text-[#ff8aa3] inline-flex items-center gap-1"><Trash2 size={12} />削除</button>
                            )}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <table className="w-full min-w-[640px] text-sm border-collapse">
              <thead className="bg-panel2 text-xs text-sub">
                <tr>
                  <th className="px-3 py-2 text-left font-normal">名前</th>
                  <th className="px-3 py-2 text-left font-normal">素材</th>
                  <th className="px-3 py-2 text-right font-normal">操作</th>
                </tr>
              </thead>
              <tbody>
                {shownNames.length === 0 && (
                  <tr><td colSpan={3} className="text-center text-sub py-10">外したアンカーはありません</td></tr>
                )}
                {shownNames.map((name) => {
                  const x = byEx.get(name);
                  const gone = deleted.has(name) || (!x && !byActive.has(name));
                  return (
                    <tr key={name} className={`border-t border-line ${x ? 'hover:bg-panel2/60' : 'bg-black/20'}`}>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className={x ? 'font-semibold' : 'text-sub line-through'}>{name}</span>
                          {x && <OriginBadge bundled={x.bundled} />}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-xs text-sub truncate max-w-[360px]">
                        {x ? x.source : gone ? '削除しました' : '使用中に戻しました'}
                      </td>
                      <td className="px-3 py-2.5 text-right whitespace-nowrap">
                        {x ? (confirm?.name === name ? (
                          <Confirm message="完全に削除します。元に戻せません。" label="削除する" busy={busy === name}
                            onYes={() => run(name, () => canvaApi.deleteAnchor(name), true)} onNo={() => setConfirm(null)} />
                        ) : (
                          <span className="inline-flex items-center gap-3">
                            <button disabled={busy === name} onClick={() => run(name, () => canvaApi.restoreAnchor(name))}
                              className="text-xs inline-flex items-center gap-1 text-sub hover:text-accent2"><Undo2 size={13} />戻す</button>
                            {!x.bundled && (
                              <button onClick={() => setConfirm({ name, act: 'delete' })}
                                className="text-xs inline-flex items-center gap-1 text-sub hover:text-[#ff8aa3]"><Trash2 size={13} />完全に削除</button>
                            )}
                          </span>
                        )) : !gone && (
                          <button disabled={busy === name} onClick={() => run(name, () => canvaApi.excludeAnchor(name))}
                            className="text-xs text-sub hover:text-[#ff8aa3]">もう一度外す</button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <Pager page={cur} pages={pages} total={list.length} pageSize={pageSize}
          onPage={setPage} onPageSize={setPageSize} />
      </div>
    </section>
  );
}

// ページ送り: 何件目か・前後・ページ番号・1ページの件数
function Pager({ page, pages, total, pageSize, onPage, onPageSize }: {
  page: number; pages: number; total: number; pageSize: number;
  onPage: (p: number) => void; onPageSize: (n: number) => void;
}) {
  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  // ページ番号は今のページの前後2つまで（多いときは … で省く）
  const nums: (number | '…')[] = [];
  for (let i = 0; i < pages; i++) {
    if (i === 0 || i === pages - 1 || Math.abs(i - page) <= 2) nums.push(i);
    else if (nums[nums.length - 1] !== '…') nums.push('…');
  }
  const btn = 'min-w-9 h-9 px-2 rounded-lg border text-sm inline-flex items-center justify-center transition disabled:opacity-40';
  return (
    <nav aria-label="ページ送り" className="flex flex-wrap items-center justify-between gap-3">
      <span className="text-xs text-sub tabular-nums">{total}人中{from}〜{to}人目</span>
      <div className="flex items-center gap-1">
        <button className={`${btn} border-line text-sub hover:text-white`} disabled={page === 0} onClick={() => onPage(0)} aria-label="最初のページ"><ChevronsLeft size={15} /></button>
        <button className={`${btn} border-line text-sub hover:text-white`} disabled={page === 0} onClick={() => onPage(page - 1)} aria-label="前のページ"><ChevronLeft size={15} /></button>
        {nums.map((x, i) => x === '…'
          ? <span key={`e${i}`} className="px-1 text-sub">…</span>
          : <button key={x} onClick={() => onPage(x)} aria-current={x === page ? 'page' : undefined}
              className={`${btn} tabular-nums ${x === page ? 'border-accent bg-accent text-white font-bold' : 'border-line text-sub hover:text-white'}`}>{x + 1}</button>)}
        <button className={`${btn} border-line text-sub hover:text-white`} disabled={page >= pages - 1} onClick={() => onPage(page + 1)} aria-label="次のページ"><ChevronRight size={15} /></button>
        <button className={`${btn} border-line text-sub hover:text-white`} disabled={page >= pages - 1} onClick={() => onPage(pages - 1)} aria-label="最後のページ"><ChevronsRight size={15} /></button>
      </div>
      <label className="text-xs text-sub flex items-center gap-2">1ページに
        <select value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))}
          className="h-9 rounded-lg bg-panel2 border border-line px-2 text-sm text-white">
          {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}人</option>)}
        </select>
      </label>
    </nav>
  );
}

function Th({ label, k, sort, onSort, align = 'right' }: {
  label: React.ReactNode; k: SortKey; sort: { key: SortKey; desc: boolean }; onSort: (k: SortKey) => void; align?: 'left' | 'right';
}) {
  const on = sort.key === k;
  return (
    <th className={`px-3 py-2 font-normal whitespace-nowrap ${align === 'left' ? 'text-left' : 'text-right'}`}
      aria-sort={on ? (sort.desc ? 'descending' : 'ascending') : 'none'}>
      <button onClick={() => onSort(k)} className={`inline-flex items-center gap-0.5 hover:text-white ${on ? 'text-white font-bold' : ''}`}>
        {label}{on && (sort.desc ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
      </button>
    </th>
  );
}

// 値と小さなバー（軸の色）
function ValueCell({ v, color }: { v: number; color: string }) {
  const r = Math.round(v);
  return (
    <td className="px-3 py-2">
      <div className="flex flex-col items-end gap-1">
        <span className="font-mono tabular-nums text-xs">{r}</span>
        <span className="w-14 h-1.5 rounded-full bg-line overflow-hidden">
          <span className="block h-full rounded-full" style={{ width: `${r}%`, background: color }} />
        </span>
      </div>
    </td>
  );
}

// 軸ごとの範囲指定（つまみ2つ）
function RangeFilter({ axis, value, onChange }: { axis: Axis; value: [number, number]; onChange: (v: [number, number]) => void }) {
  const { color, Icon } = axisMeta(axis.key);
  const [lo, hi] = value;
  const active = lo > 0 || hi < 100;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5 text-xs">
        <span className="w-5 h-5 rounded-md grid place-items-center" style={{ background: `${color}26`, color }}><Icon size={12} /></span>
        <span className={active ? 'font-bold text-white' : 'text-[#b9bedb]'}>{axis.label}</span>
        <span className="ml-auto font-mono tabular-nums" style={{ color: active ? color : '#9aa0c0' }}>{lo}〜{hi}</span>
      </div>
      <div className="relative h-5">
        <div className="absolute left-0 right-0 top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-line" />
        <div className="absolute top-1/2 -translate-y-1/2 h-1.5 rounded-full" style={{ left: `${lo}%`, right: `${100 - hi}%`, background: color }} />
        <input type="range" min={0} max={100} value={lo} aria-label={`${axis.label}の下限`} className="dual"
          style={{ ['--fill' as string]: color }}
          onChange={(e) => onChange([Math.min(Number(e.target.value), hi), hi])} />
        <input type="range" min={0} max={100} value={hi} aria-label={`${axis.label}の上限`} className="dual"
          style={{ ['--fill' as string]: color }}
          onChange={(e) => onChange([lo, Math.max(Number(e.target.value), lo)])} />
      </div>
      <div className="flex justify-between text-[10px] text-sub"><span>{axis.low}</span><span>{axis.high}</span></div>
    </div>
  );
}

// 同梱（外せるが削除できない）か、自分で追加したものか
function OriginBadge({ bundled }: { bundled: boolean }) {
  return bundled ? (
    <span title="同梱のアンカーは外せますが、削除はできません（いつでも戻せます）"
      className="shrink-0 text-[11px] px-1.5 py-0.5 rounded-full inline-flex items-center gap-1 text-[#27e0c4] bg-[#27e0c422]">
      <Package size={11} />同梱
    </span>
  ) : (
    <span className="shrink-0 text-[11px] px-1.5 py-0.5 rounded-full inline-flex items-center gap-1 text-[#f472b6] bg-[#f472b622]">
      <UserPlus size={11} />自分で追加
    </span>
  );
}

function Confirm({ message, label, busy, onYes, onNo }: {
  message: string; label: string; busy: boolean; onYes: () => void; onNo: () => void;
}) {
  return (
    <span className="inline-flex flex-wrap items-center justify-end gap-2 text-xs">
      <span className="text-sub">{message}</span>
      <button disabled={busy} onClick={onYes}
        className="px-2 py-1 rounded bg-[rgba(255,92,124,0.15)] text-[#ff8aa3] border border-[rgba(255,92,124,0.3)]">{label}</button>
      <button onClick={onNo} className="px-2 py-1 rounded border border-line text-sub">やめる</button>
    </span>
  );
}
