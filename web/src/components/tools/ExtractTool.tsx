// 音声抽出: 動画や音声のファイルから声を取り出す（ブラウザの中でデコード。ffmpeg は使わない）。
import { useEffect, useState } from 'react';
import { Video, Loader2 } from 'lucide-react';
import { useToolsStore } from '@/stores/toolsStore';
import { decodeMono, toWavDataUri, peaksOf, MAX_SEC } from '@/lib/audioTools';
import { Bars } from '@/components/canva/parts';
import { ToolHead, Primary, LengthTag, toolOf, fmt } from './common';

const C = toolOf('extract').color;

export default function ExtractTool() {
  const add = useToolsStore((s) => s.add);
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [info, setInfo] = useState<{ peaks: number[]; sec: number; originalSec: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  const pick = async (f: File | undefined) => {
    if (!f) return;
    setError(null); setDone(false); setInfo(null);
    setFile(f);
    setUrl(URL.createObjectURL(f));
    try {
      const d = await decodeMono(f);
      setInfo({ peaks: peaksOf(d.data, 90), sec: d.sec, originalSec: d.originalSec });
    } catch {
      setError('このファイルから音声を取り出せませんでした（ブラウザが再生できる形式か確かめてください）');
    }
  };

  const extract = async () => {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const d = await decodeMono(file);
      add({ name: `${file.name.replace(/\.[^.]+$/, '')}（音声）`, b64: await toWavDataUri(d.data), sec: d.sec, color: C,
        trail: [file.type.startsWith('video') ? '動画' : 'ファイル', '抽出'], state: 'ready' });
      setDone(true);
    } catch {
      setError('取り出せませんでした');
    } finally {
      setBusy(false);
    }
  };

  const isVideo = file?.type.startsWith('video');
  return (
    <>
      <ToolHead k="extract" />
      <label
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); void pick(e.dataTransfer.files?.[0]); }}
        className="flex flex-col items-center justify-center gap-2 p-7 rounded-[18px] border-2 border-dashed cursor-pointer transition text-center"
        style={{ borderColor: `${C}88`, background: over ? `${C}26` : `${C}0d` }}>
        <Video size={30} style={{ color: C }} />
        <span className="font-bold">動画や音声のファイルをここに</span>
        <span className="text-xs text-[#b9bedb]">MP4・MOV・WebM・MP3など。ブラウザの中で取り出します（先頭{MAX_SEC / 60}分まで・モノラル）</span>
        <input type="file" accept="video/*,audio/*" className="sr-only" onChange={(e) => { void pick(e.target.files?.[0]); e.target.value = ''; }} />
      </label>

      {file && (
        <div className="grid grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)] gap-4 items-center p-3.5 rounded-2xl bg-panel2 border border-line">
          {isVideo && url ? (
            <video src={url} controls className="w-full rounded-xl bg-black aspect-video" />
          ) : (
            <div className="aspect-video rounded-xl grid place-items-center" style={{ background: `linear-gradient(135deg, ${C}33, #312e81)` }}>
              <Video size={30} className="text-white/80" />
            </div>
          )}
          <div className="flex flex-col gap-2 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-extrabold truncate">{file.name}</span>
              {info && <span className="font-mono text-xs text-sub">{fmt(info.originalSec)}</span>}
              {info && <LengthTag sec={info.sec} />}
            </div>
            {info ? <Bars peaks={info.peaks} color={C} height={40} /> : !error && <Loader2 size={18} className="animate-spin text-sub" />}
            {info && info.originalSec > MAX_SEC && <span className="text-xs text-sub">先頭{MAX_SEC / 60}分だけ取り出します</span>}
          </div>
        </div>
      )}
      {error && <p className="text-sm text-[#ff8aa3]">{error}</p>}
      {done && <p className="text-sm text-[#34d399]">トレイに入れました。右のトレイから次のツールに回せます</p>}

      <div className="mt-auto">
        <Primary color={C} disabled={!info || busy} onClick={extract}>
          {busy && <Loader2 size={18} className="animate-spin" />}音声を取り出してトレイへ
        </Primary>
      </div>
    </>
  );
}
