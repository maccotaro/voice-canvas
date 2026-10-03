// soundtouchjs（LGPL-2.1）には型定義が無いので、素材ツールで使う部分だけ宣言する
declare module 'soundtouchjs' {
  export class SoundTouch {
    pitchSemitones: number;
    tempo: number;
  }
  export class WebAudioBufferSource {
    constructor(buffer: AudioBuffer);
  }
  export class SimpleFilter {
    constructor(source: WebAudioBufferSource, pipe: SoundTouch, onEnd?: () => void);
    extract(target: Float32Array, numFrames: number): number;
  }
}
