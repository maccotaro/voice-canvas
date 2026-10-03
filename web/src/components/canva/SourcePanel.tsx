// STEP 1 元の音声: 声を作るもとになる音声を用意する（文章を VOICEVOX で読み上げ／その場で録音／音声ファイル）。
// 変換すると声質だけがデザインした声に置き換わり、話す内容・テンポ・抑揚は元の音声のまま残る。
import { useEffect, useRef, useState } from 'react';
import { AudioLines, MessageSquareText, Mic, FileAudio, ChevronRight, Loader2, Upload, Download } from 'lucide-react';
import { useCanvaStore, type Source, type SourceKind } from '@/stores/canvaStore';
import { WavRecorder } from '@/lib/wavRecorder';
import { prepareAudio } from '@/lib/audioPrep';
import { StepHead, FlowArrow, WavePlayer, fmtSec } from './parts';

const TTS = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/api/tts`;
const SAMPLE = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/api/canva/sample_source`;
const MAX_CHARS = 300;
const WARN = '#f2b84b';

const KINDS: { kind: SourceKind; label: string; sub: string; short: string; color: string; Icon: typeof Mic }[] = [
  { kind: 'tts', label: '文章を入力', sub: 'VOICEVOXが読み上げ', short: 'VOICEVOX', color: '#27e0c4', Icon: MessageSquareText },
  { kind: 'rec', label: 'その場で録音', sub: 'マイクで話す', short: 'マイク', color: '#f472b6', Icon: Mic },
  { kind: 'file', label: '音声ファイル', sub: 'WAV・MP3など', short: 'WAV・MP3', color: '#fbbf24', Icon: FileAudio },
];
const colorOf = (k: SourceKind) => KINDS.find((x) => x.kind === k)!.color;

interface Speaker { id: number; name: string; style: string }

function blobToB64(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const r = new FileReader();
    r.onloadend = () => resolve(r.result as string);
    r.readAsDataURL(blob);
  });
}

export default function SourcePanel() {
  const { source, setSource } = useCanvaStore();
  // 素材ツールの「元の音声に使う」で入ってきたときは、その方法を選んだ状態で開く
  const [kind, setKind] = useState<SourceKind | null>(() => source?.kind ?? null);
  // 方法ごとに最後の音声を覚えておき、切り替えて戻ったら元に戻す
  const saved = useRef<Partial<Record<SourceKind, Source>>>(source ? { [source.kind]: source } : {});
  const [error, setError] = useState<string | null>(null);

  const choose = (k: SourceKind) => {
    setKind(k);
    setError(null);
    setSource(saved.current[k] ?? null);
  };
  const put = (k: SourceKind, s: Source | null) => {
    if (s) saved.current[k] = s; else delete saved.current[k];
    setSource(s);
  };

  // ---- 文章（VOICEVOX）----
  const [speakers, setSpeakers] = useState<Speaker[] | null>(null);
  const [vvDown, setVvDown] = useState(false);
  const [vvWsl, setVvWsl] = useState(false); // Web サーバーが WSL の中で動いている（Windows の VOICEVOX に届かない）
  const [text, setText] = useState('');
  const [speaker, setSpeaker] = useState<number | null>(null);
  const [speed, setSpeed] = useState(1.0);
  const [speaking, setSpeaking] = useState(false);
  const [checking, setChecking] = useState(false);
  const [tries, setTries] = useState(0); // 「つなぐ」を押してもまだ見つからなかった回数
  // VOICEVOX につながるか確かめる。つながったら話者の一覧を取る
  const connect = async (byUser = false) => {
    if (byUser) setChecking(true);
    try {
      const r = await fetch(`${TTS}/speakers`);
      if (!r.ok) {
        try { setVvWsl(!!(await r.json()).wsl); } catch { /* 理由が読めなくても案内は出す */ }
        throw new Error(`HTTP ${r.status}`);
      }
      const list = (await r.json()) as Speaker[];
      setSpeakers(list);
      // 既定は ずんだもん（ノーマル）、無ければ先頭
      const z = list.find((s) => s.name.includes('ずんだもん') && s.style === 'ノーマル') ?? list[0];
      if (z) setSpeaker((cur) => cur ?? z.id);
      setVvDown(false);
      setTries(0);
      setError(null);
    } catch {
      setVvDown(true);
      if (byUser) setTries((t) => t + 1);
    } finally {
      if (byUser) setChecking(false);
    }
  };
  useEffect(() => { void connect(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // 案内を出している間は 5 秒ごとに確かめ、VOICEVOX を起動したら自動でつながるようにする
  useEffect(() => {
    if (!vvDown || kind !== 'tts') return;
    const id = setInterval(() => { void connect(); }, 5000);
    return () => clearInterval(id);
  }, [vvDown, kind]); // eslint-disable-line react-hooks/exhaustive-deps
  // 文章や話者を変えたら、前の読み上げは使えない（受け皿を空に戻す）
  const editTts = (fn: () => void) => {
    fn();
    if (saved.current.tts) put('tts', null);
  };
  const speak = async () => {
    if (speaker == null) return;
    setSpeaking(true); setError(null);
    try {
      const r = await fetch(`${TTS}/synthesize`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, speaker, speed }),
      });
      // 503 = VOICEVOX につながらない（途中で閉じられた など）。エラー文ではなく案内を出す
      if (r.status === 503) { setVvDown(true); return; }
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
      const sp = speakers?.find((s) => s.id === speaker);
      put('tts', { kind: 'tts', b64: j.wav_b64, credit: j.credit, label: sp ? `${sp.name}（${sp.style}）` : '読み上げ' });
    } catch (e) {
      if (e instanceof TypeError) { setVvDown(true); return; }   // 画面のサーバーにも届かない
      setError(`読み上げられませんでした: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSpeaking(false);
    }
  };

  // ---- 録音 ----
  const recRef = useRef<WavRecorder | null>(null);
  const [recording, setRecording] = useState(false);
  const [recSec, setRecSec] = useState(0);
  useEffect(() => {
    if (!recording) return;
    const t0 = Date.now();
    const id = setInterval(() => setRecSec((Date.now() - t0) / 1000), 200);
    return () => clearInterval(id);
  }, [recording]);
  useEffect(() => () => recRef.current?.dispose(), []);
  const startRec = async () => {
    setError(null);
    try {
      recRef.current = new WavRecorder();
      await recRef.current.start();
      setRecSec(0);
      setRecording(true);
      put('rec', null);
    } catch (e) {
      setError(`マイクを使えません（ブラウザでマイクを許可してください）: ${e}`);
    }
  };
  const stopRec = async () => {
    setRecording(false);
    try {
      const blob = await recRef.current?.stop();
      recRef.current = null;
      if (blob) put('rec', { kind: 'rec', b64: await blobToB64(blob), credit: null, label: '録音' });
    } catch (e) {
      setError(`録音を確定できませんでした: ${e}`);
    }
  };

  // ---- ファイル ----
  const [loading, setLoading] = useState(false);
  const [over, setOver] = useState(false);
  const loadFile = async (f: File | undefined) => {
    if (!f) return;
    setLoading(true); setError(null);
    try {
      const a = await prepareAudio(f);
      put('file', { kind: 'file', b64: a.b64, credit: null, label: f.name });
    } catch (e) {
      setError(`このファイルは読み込めませんでした: ${e instanceof Error ? e.message : e}`);
    } finally {
      setLoading(false);
    }
  };

  // 手元に音声が無くても試せるよう、同梱の変換元音声（Common Voice・CC0）を使える
  const useSample = async () => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(SAMPLE);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      put('file', { kind: 'file', b64: await blobToB64(await r.blob()), credit: null, label: 'サンプル音声' });
    } catch (e) {
      setError(`サンプル音声を読み込めませんでした: ${e instanceof Error ? e.message : e}`);
    } finally {
      setLoading(false);
    }
  };

  const ok = !!source;
  const c = kind ? colorOf(kind) : WARN;
  const tag: [string, string] = ok ? ['OK', '#34d399'] : recording ? ['録音中', '#f472b6'] : ['未設定', WARN];

  return (
    <section className="relative bg-panel rounded-[20px] p-5 flex flex-col gap-4 min-w-0"
      style={{ border: `1px solid ${ok || recording ? c : `${WARN}88`}` }}>
      <FlowArrow active={ok} color={source ? colorOf(source.kind) : WARN} />
      <StepHead n={1} title="元の音声" color={ok || recording ? c : WARN} Icon={AudioLines}
        tag={tag[0]} tagColor={tag[1]} empty={!ok} />

      {/* 用意のしかた: まだ選んでいなければ大きなカード、選んだら小さなタイル */}
      {kind == null ? (
        <div role="group" aria-label="元の音声の用意のしかた" className="flex flex-col gap-3">
          {KINDS.map((k) => (
            <button key={k.kind} onClick={() => choose(k.kind)}
              className="flex items-center gap-4 p-4 rounded-[18px] text-left hover:brightness-125 transition"
              style={{ border: `2px solid ${k.color}66`, background: `linear-gradient(135deg, ${k.color}26, ${k.color}08)` }}>
              <span className="w-[60px] h-[60px] shrink-0 rounded-full grid place-items-center text-bg" style={{ background: k.color }}>
                <k.Icon size={28} />
              </span>
              <span className="flex flex-col leading-snug">
                <span className="text-lg font-extrabold">{k.label}</span>
                <span className="text-xs text-[#b9bedb]">{k.sub}</span>
              </span>
              <ChevronRight size={18} className="ml-auto" style={{ color: k.color }} />
            </button>
          ))}
        </div>
      ) : (
        <div role="group" aria-label="元の音声の用意のしかた" className="grid grid-cols-3 gap-2">
          {KINDS.map((k) => {
            const on = k.kind === kind;
            return (
              <button key={k.kind} aria-pressed={on} onClick={() => !recording && choose(k.kind)} disabled={recording && !on}
                className="flex flex-col items-center gap-1.5 pt-3 pb-2 px-1 rounded-2xl transition"
                style={on ? { border: `2px solid ${k.color}`, background: `${k.color}1f` }
                  : { border: '1px solid #2a2f4d', background: '#1b1f36', opacity: 0.7 }}>
                <span className="w-11 h-11 rounded-full grid place-items-center"
                  style={on ? { background: k.color, color: '#0b0d17' } : { background: `${k.color}26`, color: k.color }}>
                  <k.Icon size={20} />
                </span>
                <span className="text-[13px] font-bold leading-tight">{k.label}</span>
                <span className="text-[11px] text-sub leading-tight">{k.short}</span>
              </button>
            );
          })}
        </div>
      )}

      {kind === 'tts' && (
        <div className="flex flex-col gap-3">
          <div className="relative">
            <textarea value={text} maxLength={MAX_CHARS} rows={3} aria-label="読ませる文章"
              onChange={(e) => editTts(() => setText(e.target.value))}
              placeholder="この声で話させたい文章"
              className="w-full rounded-xl bg-panel2 border border-line p-3 text-sm focus:outline-none focus:border-accent2 resize-y" />
            <span className="absolute bottom-2 right-3 text-[11px] text-sub tabular-nums">{text.length}/{MAX_CHARS}</span>
          </div>
          {vvDown ? (
            <VoicevoxHelp checking={checking} tries={tries} wsl={vvWsl} onConnect={() => void connect(true)}
              onRecord={() => choose('rec')} onFile={() => choose('file')}
              onSample={() => { choose('file'); void useSample(); }} />
          ) : (
            <div className="flex flex-col gap-2.5">
              <select value={speaker ?? ''} aria-label="読み上げる話者"
                onChange={(e) => editTts(() => setSpeaker(Number(e.target.value)))}
                className="min-h-[44px] rounded-xl bg-panel2 border border-line px-2.5 text-sm">
                {(speakers ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}（{s.style}）</option>)}
              </select>
              <label className="text-[11px] text-sub flex items-center gap-3">
                <span className="whitespace-nowrap">読む速さ <span className="font-mono text-white">{speed.toFixed(2)}x</span></span>
                <input type="range" min={0.5} max={1.5} step={0.05} value={speed}
                  onChange={(e) => editTts(() => setSpeed(Number(e.target.value)))}
                  className="flex-1 min-w-0" style={{ ['--fill' as string]: '#27e0c4' }} />
              </label>
            </div>
          )}
          {!saved.current.tts && !vvDown && (
            <button onClick={speak} disabled={speaking || vvDown || !text.trim() || speaker == null}
              className="min-h-[44px] rounded-xl font-bold text-bg inline-flex items-center justify-center gap-2 disabled:opacity-40 hover:brightness-110 transition"
              style={{ background: '#27e0c4' }}>
              {speaking ? <Loader2 size={16} className="animate-spin" /> : <MessageSquareText size={16} />}
              {speaking ? '読み上げ中…' : '読み上げる'}
            </button>
          )}
        </div>
      )}

      {kind === 'rec' && (
        <div className="flex flex-col items-center gap-2.5 py-4 rounded-2xl bg-panel2">
          <button onClick={recording ? stopRec : startRec} aria-label={recording ? '録音を止める' : '録音を始める'}
            className="w-[76px] h-[76px] rounded-full grid place-items-center transition"
            style={{ background: '#f472b6', boxShadow: recording ? '0 0 0 8px #f472b633, 0 0 0 16px #f472b614' : 'none' }}>
            {recording ? <span className="w-6 h-6 rounded-md bg-white" /> : <Mic size={30} className="text-bg" />}
          </button>
          <span className="font-mono text-lg tabular-nums">{recording ? fmtSec(recSec) : source ? '録り直す' : '押して話す'}</span>
        </div>
      )}

      {kind === 'file' && (
        <label
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); void loadFile(e.dataTransfer.files?.[0]); }}
          className="flex flex-col items-center gap-1.5 py-5 rounded-2xl cursor-pointer transition"
          style={{ border: '2px dashed #fbbf2488', background: over ? '#fbbf2426' : '#fbbf240d' }}>
          {loading ? <Loader2 size={26} className="animate-spin text-[#fbbf24]" /> : <Upload size={26} className="text-[#fbbf24]" />}
          <span className="text-[13px]">{source ? '別のファイルにする' : <>ここにドロップ ・ <span className="text-accent2 underline">選ぶ</span></>}</span>
          <input type="file" accept="audio/*" className="sr-only" onChange={(e) => { void loadFile(e.target.files?.[0]); e.target.value = ''; }} />
        </label>
      )}
      {kind === 'file' && (
        <button onClick={useSample} disabled={loading} className="self-start text-xs text-accent2 underline disabled:opacity-50">
          手元に無ければ、サンプル音声を使う
        </button>
      )}

      {error && <p className="text-sm text-[#ff8aa3]">{error}</p>}

      {/* 受け皿: 元の音声が入っているかをひと目で見せる */}
      <div className="mt-auto">
        {source ? (
          <div className="p-3 rounded-2xl" style={{ border: `2px solid ${colorOf(source.kind)}`, background: `${colorOf(source.kind)}14` }}>
            <WavePlayer src={source.b64} color={colorOf(source.kind)} label={
              <span className="inline-flex items-center gap-2">
                {source.label}
                {source.kind === 'rec' && (
                  <a href={source.b64} download={`recording-${Date.now()}.wav`} aria-label="録音を保存" className="text-sub hover:text-white">
                    <Download size={13} />
                  </a>
                )}
              </span>
            } />
          </div>
        ) : (
          <div aria-label="元の音声は未設定" className="flex items-center gap-2.5 p-3 rounded-2xl"
            style={{ border: `2px dashed ${recording ? '#f472b6' : WARN}99`, background: `${recording ? '#f472b6' : WARN}0d` }}>
            <span className="w-10 h-10 shrink-0 rounded-full" style={{ border: `2px dashed ${recording ? '#f472b6' : WARN}99` }} />
            <div className="flex-1 h-0.5" style={{ background: `repeating-linear-gradient(90deg, ${WARN}88 0 6px, transparent 6px 12px)` }} />
            <span className="text-[11px] font-bold px-2 py-0.5 rounded-full" style={{ color: tag[1], background: `${tag[1]}22` }}>{tag[0]}</span>
          </div>
        )}
      </div>
    </section>
  );
}

// VOICEVOX が見つからないときの案内: 入手 → 起動 → つなぐ。待たずに使える別の方法も出す
function VoicevoxHelp({ checking, tries, wsl, onConnect, onRecord, onFile, onSample }: {
  checking: boolean; tries: number; wsl: boolean; onConnect: () => void; onRecord: () => void; onFile: () => void; onSample: () => void;
}) {
  const step = (n: number, body: React.ReactNode) => (
    <li className="flex items-start gap-2.5">
      <span className="w-6 h-6 shrink-0 rounded-full grid place-items-center text-xs font-extrabold text-bg" style={{ background: WARN }}>{n}</span>
      <div className="flex-1 text-[13px] leading-relaxed pt-0.5">{body}</div>
    </li>
  );
  return (
    <div className="flex flex-col gap-3 p-3.5 rounded-2xl bg-[#2a2412] border border-[#5a4a1a]">
      <div className="flex items-center gap-2">
        <span className="w-2.5 h-2.5 rounded-full animate-pulse" style={{ background: WARN }} />
        <strong className="text-[#f2d58b]">VOICEVOXが見つかりません</strong>
      </div>
      <p className="text-xs text-[#e8e0c8] -mt-1.5">文章の読み上げには、無料の読み上げソフトVOICEVOXを使います。</p>
      <ol className="flex flex-col gap-2.5">
        {step(1, <>
          <a href="https://voicevox.hiroshiba.jp/" target="_blank" rel="noreferrer" className="text-accent2 underline font-bold">VOICEVOXをダウンロード</a>
          してインストールする（Windows・Mac・Linux。入っていれば飛ばす）
        </>)}
        {step(2, <>VOICEVOXを起動して、<b>開いたままにする</b>（閉じると読み上げできません）</>)}
        {step(3, <div className="flex flex-col gap-1.5">
          <span>起動すれば自動でつながる。つながらなければ下のボタンを押す</span>
          <button onClick={onConnect} disabled={checking} className="btn self-start">
            {checking ? <Loader2 size={14} className="animate-spin" /> : null}つなぐ
          </button>
          {tries > 0 && !checking && (
            <span className="text-xs text-[#f2d58b]">まだ見つかりません。VOICEVOXの画面が開いているか確かめてください。起動した直後は、つながるまで少しかかります</span>
          )}
        </div>)}
      </ol>
      {wsl && (
        <p className="text-xs leading-relaxed text-[#f2d58b] p-2.5 rounded-lg bg-black/20">
          このアプリはWSLの中で動いています。Windowsで起動したVOICEVOXには、WSLの設定を変えるまでつながりません。
          READMEの「Windows（WSL2）で使う」の手順（networkingMode=mirrored）を見てください。
        </p>
      )}
      <div className="flex flex-col gap-2 pt-2.5 border-t border-[#5a4a1a]">
        <span className="text-xs text-[#e8e0c8]">VOICEVOXなしで続けるなら</span>
        <div className="flex flex-wrap gap-2">
          <button onClick={onRecord} className="btn"><Mic size={14} className="text-[#f472b6]" />その場で録音</button>
          <button onClick={onFile} className="btn"><FileAudio size={14} className="text-[#fbbf24]" />音声ファイル</button>
          <button onClick={onSample} className="btn"><AudioLines size={14} className="text-accent2" />サンプル音声を使う</button>
        </div>
      </div>
    </div>
  );
}
