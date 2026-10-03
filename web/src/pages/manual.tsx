// 使い方（マニュアル）: public/manual/manual.md を読み込んで表示する。GitHub でも同じファイルを読める。
// 左に章の目次（h2 から作る）。/manual#anchors のように章へ直接飛べる。
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, BookOpen } from 'lucide-react';
import { marked } from 'marked';

const BASE = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/manual`;

export default function ManualPage() {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [toc, setToc] = useState<{ id: string; text: string }[]>([]);
  const [cur, setCur] = useState<string | null>(null);
  const box = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fetch(`${BASE}/manual.md`)
      .then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
      .then((md) => {
        // 画像・相対リンクはマニュアルのフォルダ基準（GitHub と同じ書き方のまま表示できるように）
        const out = (marked.parse(md, { async: false }) as string)
          .replace(/(<img[^>]*src=")(?!https?:|\/)([^"]+)"/g, `$1${BASE}/$2"`)
          // README へのリンク（GitHub 用の相対パス）はアプリの中では開けないので、太字の文字にする
          .replace(/<a href="(?:\.\.\/)+README\.md[^"]*">([\s\S]*?)<\/a>/g, '<strong>$1</strong>（リポジトリのREADME.md）')
          // マニュアルのフォルダにある動画などへの相対リンク（#章 と README 以外）
          .replace(/<a href="(?!https?:|#|\/|(?:\.\.\/)+)([^"]+)"/g, `<a href="${BASE}/$1" target="_blank" rel="noreferrer"`)
          // 外のサイトは別タブで開く
          .replace(/<a href="(https?:[^"]+)"/g, '<a href="$1" target="_blank" rel="noreferrer"');
        setHtml(out);
      })
      .catch(() => setError(true));
  }, []);

  // 表示したら章の目次を作り、URL の #章 へ移る。読んでいる章を目次で光らせる
  useEffect(() => {
    if (!html || !box.current) return;
    const hs = Array.from(box.current.querySelectorAll('h2'));
    const items = hs.map((h, i) => {
      const prev = h.previousElementSibling?.querySelector?.('a[id]') ?? (h.previousElementSibling?.matches?.('a[id]') ? h.previousElementSibling : null);
      const id = (prev as HTMLElement | null)?.id || h.id || `section-${i + 1}`;
      if (!h.id) h.id = id;
      return { id, text: h.textContent ?? '' };
    });
    setToc(items);
    // 画像が読み込まれると高さが変わるので、全部そろってから #章 へ移る
    const toHash = () => {
      const hash = decodeURIComponent(window.location.hash.slice(1));
      if (hash && document.getElementById(hash)) { document.getElementById(hash)!.scrollIntoView(); setCur(hash); }
    };
    const imgs = Array.from(box.current.querySelectorAll('img'));
    void Promise.all(imgs.map((im) => (im.complete ? null : new Promise((r) => { im.onload = r; im.onerror = r; })))).then(toHash);
    window.addEventListener('hashchange', toHash);
    const io = new IntersectionObserver((es) => {
      const v = es.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (v) setCur((v.target as HTMLElement).id);
    }, { rootMargin: '0px 0px -70% 0px' });
    hs.forEach((h) => io.observe(h));
    return () => { io.disconnect(); window.removeEventListener('hashchange', toHash); };
  }, [html]);

  return (
    <div className="min-h-screen flex flex-col">
      <header className="px-5 py-3.5 flex flex-wrap items-center justify-between gap-3 border-b border-line">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent grid place-items-center text-white"><BookOpen size={19} /></div>
          <div>
            <h1 className="text-lg font-extrabold leading-tight">使い方</h1>
            <p className="text-sub text-xs">Voice Canvasのマニュアル</p>
          </div>
        </div>
        <nav className="flex gap-2">
          <Link href="/" className="btn whitespace-nowrap"><ArrowLeft size={15} />声のデザイン</Link>
          <Link href="/anchors" className="btn whitespace-nowrap">アンカー管理</Link>
          <Link href="/tools" className="btn whitespace-nowrap">素材ツール</Link>
        </nav>
      </header>
      <main className="flex-1 w-full max-w-[1200px] mx-auto px-5 py-6 grid grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)] gap-8">
        <aside className="hidden lg:block">
          <nav aria-label="目次" className="sticky top-6 flex flex-col gap-0.5 text-sm">
            <span className="text-xs text-sub px-3 pb-2">目次</span>
            {toc.map((t) => (
              <a key={t.id} href={`#${t.id}`}
                className={`px-3 py-1.5 rounded-lg border-l-2 transition ${cur === t.id ? 'border-accent bg-accent/15 text-white font-bold' : 'border-transparent text-[#b9bedb] hover:text-white'}`}>
                {t.text}
              </a>
            ))}
          </nav>
        </aside>
        <article ref={box} className="manual min-w-0">
          {error && <p className="text-[#ff8aa3]">マニュアルを読み込めませんでした（web/public/manual/manual.md）</p>}
          {!html && !error && <p className="text-sub">読み込んでいます…</p>}
          {html && <div dangerouslySetInnerHTML={{ __html: html }} />}
        </article>
      </main>
    </div>
  );
}
