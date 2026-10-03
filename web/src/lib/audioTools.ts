// 素材ツールの音声処理（ブラウザの中で行うもの）。音声はモノラル 44.1kHz の Float32Array で扱う。
// 抽出（動画・音声ファイルのデコード）・切り出し・削除・フェード・結合・ピッチ（soundtouchjs, LGPL-2.1）。
import { SoundTouch, SimpleFilter, WebAudioBufferSource } from 'soundtouchjs';
import { encodeWav } from '@/lib/wavRecorder';

export const SR = 44100;
export const MAX_SEC = 180;

export interface Decoded { data: Float32Array; sec: number; originalSec: number }

// 動画・音声ファイル → モノラル 44.1kHz（先頭 MAX_SEC 秒まで）。ブラウザが再生できる形式なら読める
export async function decodeMono(blob: Blob, maxSec = MAX_SEC): Promise<Decoded> {
  const buf = await blob.arrayBuffer();
  const ctx = new AudioContext();
  let decoded: AudioBuffer;
  try {
    decoded = await ctx.decodeAudioData(buf);
  } finally {
    ctx.close();
  }
  const sec = Math.min(decoded.duration, maxSec);
  const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(sec * SR)), SR);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start(0, 0, sec);
  const out = await off.startRendering();
  return { data: out.getChannelData(0).slice(), sec, originalSec: decoded.duration };
}

export async function decodeDataUri(b64: string): Promise<Float32Array> {
  return (await decodeMono(await (await fetch(b64)).blob(), Infinity)).data;
}

function blobToDataUri(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

// 書き出し: ピークを 0.95 までに収めて 16bit WAV の data URI にする
export async function toWavDataUri(data: Float32Array): Promise<string> {
  let peak = 0;
  for (let i = 0; i < data.length; i++) peak = Math.max(peak, Math.abs(data[i]));
  const out = peak > 0.95 ? data.map((v) => (v / peak) * 0.95) : data;
  return blobToDataUri(encodeWav(out, SR));
}

export const secOf = (data: Float32Array) => data.length / SR;

export function slice(data: Float32Array, a: number, b: number): Float32Array {
  return data.slice(Math.max(0, Math.floor(a * SR)), Math.min(data.length, Math.floor(b * SR)));
}

// a〜b 秒を取り除き、つなぎ目を短く重ねてプツッという音を防ぐ
export function removeRange(data: Float32Array, a: number, b: number, xfade = 0.02): Float32Array {
  return join([slice(data, 0, a), slice(data, b, secOf(data))], xfade);
}

export function fade(data: Float32Array, inSec: number, outSec: number): Float32Array {
  const out = data.slice();
  const fi = Math.min(out.length, Math.floor(inSec * SR));
  const fo = Math.min(out.length, Math.floor(outSec * SR));
  for (let i = 0; i < fi; i++) out[i] *= i / fi;
  for (let i = 0; i < fo; i++) out[out.length - 1 - i] *= i / fo;
  return out;
}

// 順につなぐ。つなぎ目は xfade 秒だけ重ねて直線でクロスフェードする
export function join(parts: Float32Array[], xfade: number): Float32Array {
  const list = parts.filter((p) => p.length > 0);
  if (list.length === 0) return new Float32Array(0);
  let out = list[0];
  for (const p of list.slice(1)) {
    const x = Math.min(Math.floor(xfade * SR), out.length, p.length);
    const next = new Float32Array(out.length + p.length - x);
    next.set(out.subarray(0, out.length - x), 0);
    for (let i = 0; i < x; i++) {
      const t = (i + 1) / (x + 1);
      next[out.length - x + i] = out[out.length - x + i] * (1 - t) + p[i] * t;
    }
    next.set(p.subarray(x), out.length);
    out = next;
  }
  return out;
}

// 高さ（半音）とテンポ（倍）を変える。テンポを変えても高さは変わらない
export function pitchShift(data: Float32Array, semitones: number, tempo: number): Float32Array {
  if (semitones === 0 && tempo === 1) return data.slice();
  const buf = new AudioBuffer({ length: data.length, numberOfChannels: 1, sampleRate: SR });
  buf.copyToChannel(new Float32Array(data), 0);
  const st = new SoundTouch();
  st.pitchSemitones = semitones;
  st.tempo = tempo;
  const filter = new SimpleFilter(new WebAudioBufferSource(buf), st);
  const BLOCK = 8192;
  const tmp = new Float32Array(BLOCK * 2);
  const out = new Float32Array(Math.ceil((data.length / tempo) * 1.05) + BLOCK);
  let n = 0;
  for (;;) {
    const got = filter.extract(tmp, BLOCK);
    if (got <= 0 || n + got > out.length) break;
    for (let i = 0; i < got; i++) out[n + i] = tmp[i * 2];
    n += got;
  }
  return out.slice(0, n);
}

// 波形表示用の山（0..1）
export function peaksOf(data: Float32Array, n: number): number[] {
  const step = Math.max(1, Math.floor(data.length / n));
  const raw = Array.from({ length: n }, (_, i) => {
    let m = 0;
    for (let j = i * step; j < Math.min(data.length, (i + 1) * step); j++) m = Math.max(m, Math.abs(data[j]));
    return m;
  });
  const top = Math.max(...raw, 1e-6);
  return raw.map((v) => 0.1 + 0.9 * (v / top));
}
