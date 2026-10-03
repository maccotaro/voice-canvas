// 素材ツールの共通部品: ツールの一覧（色・アイコン）・見出し・入力の選択・大きなボタン。
import type { ReactNode } from 'react';
import { Video, Sparkles, Scissors, Music, Merge, Mic, type LucideIcon } from 'lucide-react';
import { useToolsStore, type ToolKey, type Clip } from '@/stores/toolsStore';

export const TOOLS: { key: ToolKey; label: string; short: string; sub: string; color: string; Icon: LucideIcon }[] = [
  { key: 'extract', label: '音声抽出', short: '抽出', sub: '動画から声を取り出す', color: '#60a5fa', Icon: Video },
  { key: 'separate', label: 'BGM・雑音の除去', short: 'BGM除去', sub: '声だけを残す', color: '#a78bfa', Icon: Sparkles },
  { key: 'cut', label: 'カット', short: 'カット', sub: '使う区間を選ぶ', color: '#fb923c', Icon: Scissors },
  { key: 'pitch', label: 'ピッチ', short: 'ピッチ', sub: '高さとテンポを変える', color: '#e879f9', Icon: Music },
  { key: 'join', label: '結合', short: '結合', sub: '短い録音をつなぐ', color: '#34d399', Icon: Merge },
  { key: 'record', label: '録音', short: '録音', sub: 'マイクで録る', color: '#f472b6', Icon: Mic },
];
export const toolOf = (k: ToolKey) => TOOLS.find((t) => t.key === k)!;

// アンカーにできる最低の長さ（サーバーの LIGHT_MIN_SEC と同じ）
export const ANCHOR_MIN_SEC = 8;

export const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export function ToolHead({ k, children }: { k: ToolKey; children?: ReactNode }) {
  const t = toolOf(k);
  return (
    <div className="flex items-center gap-3">
      <span className="w-12 h-12 shrink-0 rounded-[14px] grid place-items-center text-bg" style={{ background: t.color }}>
        <t.Icon size={24} />
      </span>
      <div className="leading-tight">
        <h2 className="text-[22px] font-extrabold">{t.label}</h2>
        <span className="text-xs text-[#b9bedb]">{t.sub}</span>
      </div>
      {children}
    </div>
  );
}

// 使う素材（トレイから選ぶ）
export function InputPick({ clip, label = '使う素材' }: { clip: Clip | undefined; label?: string }) {
  const { clips, setInput } = useToolsStore();
  const ready = clips.filter((c) => c.state === 'ready');
  return (
    <div className="flex flex-wrap items-center gap-3 px-3.5 py-3 rounded-2xl bg-panel2 border border-line">
      <span className="text-xs text-sub whitespace-nowrap">{label}</span>
      {ready.length === 0 ? (
        <span className="text-sm text-sub">まだ素材がありません。右のトレイにファイルを置くか、音声抽出・録音で作ってください</span>
      ) : (
        <select value={clip?.id ?? ''} onChange={(e) => setInput(e.target.value || null)} aria-label={label}
          className="flex-1 min-w-[200px] min-h-[40px] rounded-xl bg-panel border border-line px-2.5 text-sm">
          <option value="">トレイから選ぶ…</option>
          {ready.map((c) => <option key={c.id} value={c.id}>{c.name}（{fmt(c.sec)}）</option>)}
        </select>
      )}
    </div>
  );
}

export function Primary({ color, disabled, onClick, children }: {
  color: string; disabled?: boolean; onClick: () => void; children: ReactNode;
}) {
  return (
    <button onClick={onClick} disabled={disabled}
      className="min-h-[52px] px-6 rounded-[14px] text-base font-bold text-bg inline-flex items-center justify-center gap-2 hover:brightness-110 transition disabled:opacity-45"
      style={{ background: color }}>
      {children}
    </button>
  );
}

// 長さの目安（アンカーにできるか）
export function LengthTag({ sec }: { sec: number }) {
  const ok = sec >= ANCHOR_MIN_SEC;
  const c = ok ? '#34d399' : '#f2b84b';
  return (
    <span className="text-xs font-bold px-2 py-0.5 rounded-full whitespace-nowrap" style={{ color: c, background: `${c}22` }}>
      {sec.toFixed(1)}秒 ・ {ok ? 'アンカーに使える長さ' : `アンカーには${ANCHOR_MIN_SEC}秒以上`}
    </span>
  );
}
