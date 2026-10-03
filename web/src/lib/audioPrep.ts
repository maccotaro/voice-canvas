// アップロード前の音声変換: 任意の音声ファイル → モノラル 44.1kHz 16bit WAV（base64 data URI）。
// ブラウザでデコードするので mp3 / m4a / wav など、ブラウザが再生できる形式なら受け付ける。
// 選定に使うのは数分で足りるので先頭 MAX_SEC 秒だけ送る（転送量を抑える。プロキシ上限 30MB）。
import { encodeWav } from '@/lib/wavRecorder';

export const TARGET_SR = 44100;
export const MAX_SEC = 180;
export const MIN_SEC = 8; // サーバーの LIGHT_MIN_SEC と揃える

export interface PreparedAudio {
  b64: string;
  sec: number; // 変換後の長さ（MAX_SEC で切った後）
  originalSec: number;
}

function blobToDataUri(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

export async function prepareAudio(file: File): Promise<PreparedAudio> {
  const buf = await file.arrayBuffer();
  const ctx = new AudioContext();
  let decoded: AudioBuffer;
  try {
    decoded = await ctx.decodeAudioData(buf);
  } finally {
    ctx.close();
  }
  const originalSec = decoded.duration;
  const sec = Math.min(originalSec, MAX_SEC);
  const frames = Math.ceil(sec * TARGET_SR);
  // OfflineAudioContext でモノラル化とリサンプリングを一度に行う
  const off = new OfflineAudioContext(1, frames, TARGET_SR);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start(0, 0, sec);
  const rendered = await off.startRendering();
  const b64 = await blobToDataUri(encodeWav(rendered.getChannelData(0), TARGET_SR));
  return { b64, sec, originalSec };
}
