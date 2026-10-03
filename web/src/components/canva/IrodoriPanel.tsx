// Irodori モード: キャプション文＋seed で声をデザインする(Irodori-TTS VoiceDesign)。
// スライダーの連続調整と違い「キャプション語彙の編集 × seed ガチャ」で探索する。
// 生成音は履歴に積み、同 caption+同 seed でいつでも完全再現できる。
import { useRef, useState } from 'react';
import { Dices, Download, Loader2, Play, Sparkles } from 'lucide-react';

const BASE = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/api/irodori`;
const DEFAULT_TEXT = 'こんにちは！あなたの声をデザインして、理想の音声を作りましょう。';
const PRESETS = [
  '明るく元気な若い女性の声。カフェの店員のように、ハキハキとした少し高めのトーンで話している。',
  '落ち着いた大人の女性の声。丁寧で穏やかな話し方。',
  '深く響く落ち着いた大人の男性の声。フォーマルで信頼感のある話し方。',
  '少し高めの声の少女が、一生懸命だけど少しドジっ子っぽく話している。穏やかだけど時々慌てる。',
];

interface HistItem {
  id: number;
  caption: string;
  seed: number;
  url: string;      // ObjectURL
  genSec: number;
}

export default function IrodoriPanel() {
  const [caption, setCaption] = useState(PRESETS[0]);
  const [seed, setSeed] = useState(1042);
  const [text, setText] = useState(DEFAULT_TEXT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistItem[]>([]);
  const idRef = useRef(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const generate = async (useSeed: number) => {
    if (!caption.trim() || busy) return;
    setBusy(true);
    setError(null);
    const t0 = performance.now();
    try {
      const r = await fetch(`${BASE}/v1/audio/speech`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'irodori-tts',
          input: text.trim() || DEFAULT_TEXT,
          voice: 'none',
          response_format: 'wav',
          irodori: { caption: caption.trim(), seed: useSeed },
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const item: HistItem = {
        id: ++idRef.current,
        caption: caption.trim(),
        seed: useSeed,
        url,
        genSec: (performance.now() - t0) / 1000,
      };
      setHistory((h) => [item, ...h].slice(0, 20));
      // 生成できたら即試聴
      requestAnimationFrame(() => {
        if (audioRef.current) { audioRef.current.src = url; void audioRef.current.play(); }
      });
    } catch (e) {
      setError(`生成に失敗しました: ${String(e)}（初回はモデルロードで数分かかることがあります）`);
    } finally {
      setBusy(false);
    }
  };

  const gacha = () => {
    const s = Math.floor(Math.random() * 999_999) + 1;
    setSeed(s);
    void generate(s);
  };

  const restore = (it: HistItem) => {
    setCaption(it.caption);
    setSeed(it.seed);
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold flex items-center gap-1.5">
          <Sparkles size={18} className="text-accent2" />キャプションで声をデザイン
        </h2>
        <p className="text-sub text-xs mt-0.5">
          声の特徴を文章で書き、seedを変えながら探します。同じキャプションと同じseedなら、同じ声を再現できます。
        </p>
      </div>

      {error && (
        <div className="text-sm text-[#ff8aa3] bg-[rgba(255,92,124,0.1)] border border-[rgba(255,92,124,0.3)] rounded-lg p-2">
          {error}
        </div>
      )}

      <div>
        <label className="text-sm text-sub">キャプション（性別・年齢・声質に加えて性格や振る舞いを書くと効果的）</label>
        <textarea
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
          rows={3}
          className="mt-1 w-full bg-panel2 border border-line rounded-lg p-2.5 text-sm outline-none focus:border-accent resize-y"
        />
        <div className="flex flex-wrap gap-1.5 mt-1.5">
          {PRESETS.map((p) => (
            <button
              key={p}
              onClick={() => setCaption(p)}
              title={p}
              className="px-2 py-1 rounded-md bg-panel2 border border-line text-[11px] text-sub hover:border-accent transition max-w-[180px] truncate"
            >
              {p.slice(0, 14)}…
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="text-sm text-sub">テスト文</label>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="mt-1 w-full bg-panel2 border border-line rounded-lg p-2.5 text-sm outline-none focus:border-accent"
        />
      </div>

      <div className="flex items-end gap-2">
        <div>
          <label className="text-sm text-sub">seed</label>
          <input
            type="number"
            value={seed}
            min={1}
            onChange={(e) => setSeed(Math.max(1, Math.floor(Number(e.target.value) || 1)))}
            className="mt-1 w-28 bg-panel2 border border-line rounded-lg p-2.5 text-sm outline-none focus:border-accent tabular-nums"
          />
        </div>
        <button
          onClick={() => void generate(seed)}
          disabled={busy || !caption.trim()}
          className="flex-1 py-2.5 rounded-lg bg-accent text-white text-sm font-medium inline-flex items-center justify-center gap-1.5 hover:brightness-110 transition disabled:opacity-60"
        >
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
          このseedで生成
        </button>
        <button
          onClick={gacha}
          disabled={busy || !caption.trim()}
          title="seedをランダムに変えて生成"
          className="py-2.5 px-4 rounded-lg bg-panel2 border border-line text-sm inline-flex items-center justify-center gap-1.5 hover:border-accent transition disabled:opacity-60"
        >
          <Dices size={16} />ガチャ
        </button>
      </div>

      {/* この声で学習: 埋め込み元の親ページへ設計値を postMessage で渡すだけ。iframe 自体は
          非認証のため、ジョブ投入・進捗表示は親ページ側が担う。
          単体で開いた場合(parent===window)はボタンを出さない。 */}
      {typeof window !== 'undefined' && window.parent !== window && (
        <button
          onClick={() => {
            window.parent.postMessage(
              {
                type: 'canva:train-request',
                caption: caption.trim(),
                seed,
                suggestedName: caption.trim().slice(0, 12).replace(/[。、．，\s].*$/, '') || 'デザインボイス',
              },
              '*',
            );
          }}
          disabled={busy || !caption.trim()}
          title="このキャプションとseedの声で学習済みボイスを作ります（数十分かかります）"
          className="w-full py-2.5 rounded-lg bg-panel2 border border-accent text-accent text-sm font-medium inline-flex items-center justify-center gap-1.5 hover:bg-accent hover:text-white transition disabled:opacity-60"
        >
          <Sparkles size={16} />この声で学習
        </button>
      )}

      <audio ref={audioRef} className="hidden" />

      {/* 履歴: 気に入った声は「呼び戻す」で caption+seed を復元 */}
      <div>
        <h3 className="text-sm font-semibold text-sub">生成履歴（最新20件）</h3>
        {history.length === 0 && (
          <p className="text-[11px] text-sub mt-1">まだ生成がありません。「ガチャ」で声の探索を始めましょう。</p>
        )}
        <ul className="mt-1.5 space-y-1.5 max-h-[340px] overflow-y-auto pr-1">
          {history.map((it) => (
            <li key={it.id} className="bg-panel2 border border-line rounded-lg p-2 flex items-center gap-2">
              <div className="min-w-0 flex-1">
                <div className="text-[11px] text-sub truncate" title={it.caption}>{it.caption}</div>
                <div className="text-[11px] tabular-nums">
                  seed <span className="text-accent2">{it.seed}</span>
                  <span className="text-sub"> ・ {it.genSec.toFixed(1)}s</span>
                </div>
                <audio controls preload="none" src={it.url} className="w-full h-8 mt-1" />
              </div>
              <div className="shrink-0 flex flex-col gap-1">
                <button
                  onClick={() => restore(it)}
                  className="px-2 py-1 rounded-md bg-panel border border-line text-[11px] hover:border-accent transition"
                >
                  呼び戻す
                </button>
                <a
                  href={it.url}
                  download={`irodori_seed${it.seed}.wav`}
                  className="px-2 py-1 rounded-md bg-panel border border-line text-[11px] inline-flex items-center gap-1 hover:border-accent transition"
                >
                  <Download size={11} />保存
                </a>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
