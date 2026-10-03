// 折りたためる欄。開閉はこのブラウザに覚えておく（次に開いたときも同じ状態）。
// 閉じても中身は残す（素材の取り込み中に閉じても進み具合の取得が止まらないように）。
import { useEffect, useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight, type LucideIcon } from 'lucide-react';

export default function Fold({ id, title, Icon, color, badge, children }: {
  id: string; title: string; Icon: LucideIcon; color: string; badge?: ReactNode; children: ReactNode;
}) {
  const key = `voice-canva.fold.${id}`;
  const [open, setOpen] = useState(true);
  useEffect(() => {
    try { const v = localStorage.getItem(key); if (v != null) setOpen(v === '1'); } catch { /* 保存できない環境は開いたまま */ }
  }, [key]);
  const toggle = () => {
    setOpen((o) => {
      try { localStorage.setItem(key, o ? '0' : '1'); } catch { /* noop */ }
      return !o;
    });
  };
  return (
    <section className="bg-panel border border-line rounded-[20px]">
      <button onClick={toggle} aria-expanded={open}
        className="w-full flex items-center gap-3 px-5 py-4 text-left rounded-[20px] hover:bg-panel2/50 transition">
        <span className="w-9 h-9 shrink-0 rounded-xl grid place-items-center" style={{ background: `${color}26`, color }}><Icon size={18} /></span>
        <h2 className="text-lg font-extrabold">{title}</h2>
        {badge}
        <span className="ml-auto text-sub">{open ? <ChevronDown size={20} /> : <ChevronRight size={20} />}</span>
      </button>
      <div hidden={!open} className="px-5 pb-5">{children}</div>
    </section>
  );
}
