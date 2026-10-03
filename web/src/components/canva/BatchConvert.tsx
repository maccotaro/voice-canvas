// 複数ファイル一括変換: 選んだ音声を「今の声デザイン(スライダー)＋高度な調整」で
// 順次変換し、結果をまとめて 1 つの ZIP でダウンロードする。
// backend は単一 GPU なので逐次実行（並列は過負荷）。
import { useRef, useState } from 'react';
import { Layers, Download, X } from 'lucide-react';
import { useCanvaStore } from '@/stores/canvaStore';
import { canvaApi } from '@/lib/api/canvaApi';
import { buildZip, dataUriToBytes, type ZipEntry } from '@/lib/zip';

// ガード値:
// - 1ファイル上限: プロキシの bodyParser sizeLimit=25MB(base64) に対応。
//   base64 は約1.33倍に膨らむため、生バイトは約18MBまで。
// - 件数上限: 逐次処理の待ち時間とブラウザメモリを考慮。
const MAX_FILE_BYTES = 18 * 1024 * 1024;
const MAX_FILE_MB = 18;
const MAX_FILES = 50;

type Status = 'wait' | 'run' | 'done' | 'err' | 'skip';
type Item = { file: File; status: Status; result?: string; note?: string };

function blobToB64(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const r = new FileReader();
    r.onloadend = () => resolve(r.result as string);
    r.readAsDataURL(blob);
  });
}

// 出力名 = 元ファイル名(拡張子除去)_converted.wav（重複は連番付与）
function outName(name: string, used: Set<string>): string {
  const base = name.replace(/\.[^./\\]+$/, '');
  let n = `${base}_converted.wav`;
  let i = 2;
  while (used.has(n)) n = `${base}_converted_${i++}.wav`;
  used.add(n);
  return n;
}

export default function BatchConvert() {
  const { sliders, adv } = useCanvaStore();
  const [items, setItems] = useState<Item[]>([]);
  const [running, setRunning] = useState(false);
  const [warn, setWarn] = useState<string | null>(null);
  // 学習素材用の忠実モード（AUTO_F0 off/steps多め/DSP off）。SBV2学習で感情が潰れる
  // 問題への対策のため、一括変換は学習素材用途とみなし既定ON。
  const [faithful, setFaithful] = useState(true);
  const cancelRef = useRef(false);

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    let picked = Array.from(e.target.files ?? []);
    e.target.value = '';
    const warns: string[] = [];

    // 件数ガード: 先頭 MAX_FILES 件のみ対象
    if (picked.length > MAX_FILES) {
      warns.push(`最大${MAX_FILES}件までです。選んだ${picked.length}件のうち、先頭の${MAX_FILES}件を対象にしました。`);
      picked = picked.slice(0, MAX_FILES);
    }

    // サイズガード: 上限超過は「対象外」にして変換からスキップ
    let over = 0;
    const next: Item[] = picked.map((file) => {
      if (file.size > MAX_FILE_BYTES) {
        over++;
        return { file, status: 'skip', note: `${MAX_FILE_MB}MBを超えています` };
      }
      return { file, status: 'wait' };
    });
    if (over > 0) warns.push(`${over}件は${MAX_FILE_MB}MBを超えるため、変換しません。`);

    setItems(next);
    setWarn(warns.length ? warns.join(' ') : null);
  };

  const run = async () => {
    const targets = items.filter((it) => it.status !== 'skip');
    if (!targets.length || running) return;
    setRunning(true);
    cancelRef.current = false;
    // skip は維持し、それ以外は待機へ戻して再実行可能に
    const next: Item[] = items.map((it) =>
      it.status === 'skip' ? it : { file: it.file, status: 'wait' },
    );
    setItems([...next]);
    for (let i = 0; i < next.length; i++) {
      if (cancelRef.current) break;
      if (next[i].status === 'skip') continue;
      next[i] = { ...next[i], status: 'run' };
      setItems([...next]);
      try {
        const b64 = await blobToB64(next[i].file);
        const r = await canvaApi.generate(sliders, b64, adv, faithful);
        next[i] = { ...next[i], status: 'done', result: r.wav_b64 };
      } catch (e) {
        next[i] = { ...next[i], status: 'err', note: String(e) };
      }
      setItems([...next]);
    }
    setRunning(false);
  };

  const downloadZip = () => {
    const used = new Set<string>();
    const entries: ZipEntry[] = items
      .filter((it) => it.status === 'done' && it.result)
      .map((it) => ({ name: outName(it.file.name, used), data: dataUriToBytes(it.result as string) }));
    if (!entries.length) return;
    const url = URL.createObjectURL(buildZip(entries));
    const a = document.createElement('a');
    a.href = url;
    a.download = `voice-canva-batch-${Date.now()}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const targetCount = items.filter((it) => it.status !== 'skip').length;
  const doneCount = items.filter((it) => it.status === 'done').length;
  const errCount = items.filter((it) => it.status === 'err').length;
  // 変換すべきファイルが残っている（未実行/一部のみ完了）状態＝「一括変換」を促す
  const needRun = targetCount > 0 && !running && doneCount < targetCount;
  const badge = (s: Status) =>
    s === 'done' ? '完了' : s === 'run' ? '変換中' : s === 'err' ? '失敗' : s === 'skip' ? '対象外' : '待機';

  return (
    <div className="bg-panel2 border border-line rounded-xl p-3 space-y-2">
      <div className="text-sm text-accent2 font-medium flex items-center gap-1.5">
        <Layers size={15} />まとめて変換
      </div>
      <div className="text-[11px] text-sub">
        選んだ音声をいまの声の設定で順番に変換し、まとめてZIPで保存します（1ファイル{MAX_FILE_MB}MBまで、{MAX_FILES}件まで）。
      </div>
      <label className="flex items-start gap-2 text-[11px] cursor-pointer">
        <input
          type="checkbox"
          checked={faithful}
          disabled={running}
          onChange={(e) => setFaithful(e.target.checked)}
          className="mt-0.5"
        />
        <span>
          <span className="text-accent2 font-medium">学習用（忠実モード）</span>
          <span className="text-sub">
            。感情の抑揚を残します（ピッチ正規化オフ・高精度・後処理オフ）。SBV2などの学習素材を作るときはONがおすすめです。
            ふだんの試聴ならOFFにします。
          </span>
        </span>
      </label>
      <div className="flex gap-2 flex-wrap">
        <label className="btn cursor-pointer text-xs">
          ファイルを選択（複数可）
          <input type="file" accept="audio/*" multiple onChange={onPick} className="hidden" />
        </label>
        <button
          onClick={run}
          disabled={!targetCount || running}
          className={`btn text-xs ${needRun ? 'font-semibold' : ''}`}
          style={needRun ? { background: '#7c5cff', color: '#fff', borderColor: '#7c5cff' } : undefined}
        >
          {running ? `変換中… ${doneCount}/${targetCount}` : `まとめて変換（${targetCount}件）`}
        </button>
        {running && (
          <button onClick={() => { cancelRef.current = true; }} className="btn text-xs text-red-300">
            <X size={14} />中止
          </button>
        )}
        {doneCount > 0 && !running && (
          <button onClick={downloadZip} className="btn text-xs text-accent2">
            <Download size={14} />ZIPで保存（{doneCount}件）
          </button>
        )}
      </div>
      {needRun && (
        <div className="text-[11px] text-accent2">
          紫色の「まとめて変換（{targetCount}件）」を押すと変換が始まります。終わると「ZIPで保存」が出ます。
        </div>
      )}
      {warn && (
        <div className="text-[11px] text-[#ffcf7a] bg-[rgba(255,180,60,0.1)] border border-[rgba(255,180,60,0.3)] rounded-lg p-2">
          {warn}
        </div>
      )}
      {errCount > 0 && !running && (
        <div className="text-[11px] text-[#ff8aa3]">{errCount}件が失敗しました（成功分のみZIPに含まれます）。</div>
      )}
      {items.length > 0 && (
        <ul className="text-[11px] space-y-1 max-h-40 overflow-auto">
          {items.map((it, i) => (
            <li key={i} className="flex justify-between gap-2">
              <span className="truncate" title={it.note || it.file.name}>{it.file.name}</span>
              <span
                className={
                  it.status === 'done'
                    ? 'text-accent2'
                    : it.status === 'err'
                      ? 'text-[#ff8aa3]'
                      : it.status === 'skip'
                        ? 'text-[#ffcf7a]'
                        : 'text-sub'
                }
              >
                {badge(it.status)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
