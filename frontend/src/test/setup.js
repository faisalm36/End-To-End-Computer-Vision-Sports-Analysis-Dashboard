// Vitest setup: jest-dom matchers, a clean DOM/storage per test, and stubs for
// browser APIs jsdom doesn't have.
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';
import { resetMetricDefsCache } from '../lib/useMetricDefs';
import { resetUploadConfigCache } from '../lib/useUploadConfig';

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  resetMetricDefsCache();
  resetUploadConfigCache();
  // Upload previews use object URLs; jsdom has no implementation.
  URL.createObjectURL = vi.fn(() => 'blob:mock');
  URL.revokeObjectURL = vi.fn();
  // Native <dialog> methods are missing in jsdom.
  if (typeof HTMLDialogElement !== 'undefined') {
    HTMLDialogElement.prototype.showModal ||= function showModal() {
      this.open = true;
    };
    HTMLDialogElement.prototype.close ||= function close() {
      this.open = false;
    };
  }
  window.scrollTo = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
