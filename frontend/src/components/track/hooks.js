import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { fitRect, timeToFrame } from '../../lib/tracking';

// Content rectangle of the media (object-fit: contain) inside `ref`, kept up to date on
// resize and when the intrinsic size becomes known. Rect is relative to the container.
export function useContentRect(ref, mediaW, mediaH) {
  const [rect, setRect] = useState({ x: 0, y: 0, w: 0, h: 0, cw: 0, ch: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const update = () => {
      const cw = el.clientWidth;
      const ch = el.clientHeight;
      setRect({ ...fitRect(cw, ch, mediaW || 16, mediaH || 9), cw, ch });
    };
    update();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', update);
      return () => window.removeEventListener('resize', update);
    }
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, mediaW, mediaH]);
  return rect;
}

// Current frame of a <video>: requestVideoFrameCallback (exact presented frame via
// mediaTime) when available, else rAF + currentTime. Also updates on seeks while paused.
export function useVideoFrame(videoRef, fps, frameCount, deps = []) {
  const [frame, setFrame] = useState(0);
  const last = useRef(-1);
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !(fps > 0)) return undefined;
    let stop = false;
    let handle = null;
    const push = (t) => {
      const f = timeToFrame(t, fps, frameCount || Infinity);
      if (f !== last.current) {
        last.current = f;
        setFrame(f);
      }
    };
    const hasRvfc = typeof v.requestVideoFrameCallback === 'function';
    const tick = (_now, meta) => {
      if (stop) return;
      push(meta && Number.isFinite(meta.mediaTime) ? meta.mediaTime : v.currentTime);
      handle = hasRvfc ? v.requestVideoFrameCallback(tick) : requestAnimationFrame(tick);
    };
    handle = hasRvfc ? v.requestVideoFrameCallback(tick) : requestAnimationFrame(tick);
    const onSeek = () => push(v.currentTime);
    v.addEventListener('seeked', onSeek);
    v.addEventListener('timeupdate', onSeek);
    v.addEventListener('loadeddata', onSeek);
    return () => {
      stop = true;
      if (hasRvfc && v.cancelVideoFrameCallback && handle != null) v.cancelVideoFrameCallback(handle);
      else if (handle != null) cancelAnimationFrame(handle);
      v.removeEventListener('seeked', onSeek);
      v.removeEventListener('timeupdate', onSeek);
      v.removeEventListener('loadeddata', onSeek);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoRef, fps, frameCount, ...deps]);
  return [frame, setFrame];
}

export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (!mq) return undefined;
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return reduced;
}

// Keys typed into form controls never trigger player shortcuts.
export const isTypingTarget = (el) => !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) && el.type !== 'range' && el.type !== 'checkbox';
